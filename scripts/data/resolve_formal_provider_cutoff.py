"""Resolve the latest complete provider session available for formal refresh."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.data.refresh_selected_pool_prices_v2 import (
    _terminal_listing_entries,
    build_hardened_router,
)
from src.data.router import MarketDataRouter, RouterResponse
from src.research.market_session_clock import completed_market_date

BENCHMARKS = {"us": "QQQ", "cn": "000300"}
# Strategy pools whose members must be complete before the market cutoff is
# blessed: the benchmark-only probe over-promised when members lagged the
# benchmark (vendor EOD delays), melting the whole market build. Symbols are
# derived from pool files, never hand-listed here.
STRATEGY_POOL_PATHS = {"cn": "configs/pools/cn_all_weather_alpha_rotation_v1.yaml"}
SELECTED_UNIVERSE_PATHS = {
    "us": "configs/research_universes/us_selected_equities_v2.yaml",
}
PROBE_DELAY_SECONDS = 1.0
# Vendor EOD endpoints answer intermittently. A single transient failure must
# not block a whole market, so each symbol is probed a bounded number of times
# with linear backoff before it is recorded as failed.
PROBE_ATTEMPTS = 3
PROBE_RETRY_DELAY_SECONDS = 4.0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_github_output(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def _previous_completed(market: str, cutoff: str) -> str:
    requested = (date.fromisoformat(cutoff) - timedelta(days=1)).isoformat()
    return completed_market_date(market, requested)


def _strategy_probe_symbols(root: Path, market_key: str) -> list[str]:
    """Derive strategy-critical symbols that gate the market cutoff."""
    symbols: list[str] = []
    relative = STRATEGY_POOL_PATHS.get(market_key)
    if relative:
        pool = yaml.safe_load((root / relative).read_text(encoding="utf-8"))
        for entry in pool.get("symbols", []):
            symbol = entry.get("symbol") if isinstance(entry, dict) else entry
            if str(symbol or "").strip():
                symbols.append(str(symbol).strip().upper())
        references = pool.get("references", {})
        if isinstance(references, dict):
            for key, entry in references.items():
                if not isinstance(entry, Mapping):
                    continue
                role = str(entry.get("role") or "")
                if "benchmark" in role.lower():
                    continue
                symbol = entry.get("symbol") or entry.get("provider_symbol") or key
                if str(symbol or "").strip():
                    symbols.append(
                        str(symbol).strip().upper().lstrip("^").split(".", 1)[0]
                    )
    universe_relative = SELECTED_UNIVERSE_PATHS.get(market_key)
    if universe_relative:
        universe = yaml.safe_load((root / universe_relative).read_text(encoding="utf-8"))
        for value in universe.get("symbols", []):
            if str(value or "").strip():
                symbols.append(str(value).strip().upper())
    return sorted(set(symbols))


def _fetch_with_retries(
    data_router: MarketDataRouter,
    *,
    market_key: str,
    symbol: str,
    start: str,
    end: str,
) -> "RouterResponse":
    """Fetch one symbol, retrying transient vendor failures with linear backoff."""

    response: RouterResponse | None = None
    for attempt in range(PROBE_ATTEMPTS):
        response = data_router.fetch_daily_bars(
            symbol=symbol, market=market_key, start=start, end=end, validate=True
        )
        if response.ok and response.result is not None:
            return response
        time.sleep(PROBE_RETRY_DELAY_SECONDS * (attempt + 1))
    assert response is not None
    return response


def _probe_watermark(
    data_router: MarketDataRouter,
    *,
    market_key: str,
    symbol: str,
    start: str,
    end: str,
) -> str | None:
    response = _fetch_with_retries(
        data_router, market_key=market_key, symbol=symbol, start=start, end=end
    )
    if not response.ok or response.result is None:
        return None
    dates = pd.to_datetime(response.result.df.get("date"), errors="coerce").dropna()
    if dates.empty:
        return None
    return pd.Timestamp(dates.max()).tz_localize(None).date().isoformat()


def resolve_formal_provider_cutoff(
    *,
    market: str,
    requested_cutoff: str,
    seed_cutoff: str,
    published_cutoff: str | None = None,
    router: MarketDataRouter | None = None,
) -> dict[str, Any]:
    market_key = str(market).strip().lower()
    if market_key not in BENCHMARKS:
        raise ValueError(f"unsupported market: {market}")
    requested = date.fromisoformat(str(requested_cutoff)).isoformat()
    seed = date.fromisoformat(str(seed_cutoff)).isoformat()
    if seed > requested:
        raise ValueError("seed cutoff cannot exceed requested cutoff")

    benchmark = BENCHMARKS[market_key]
    base = {
        "schema_version": "1.1",
        "evidence_type": "formal_provider_readiness_v1",
        "market": market_key,
        "benchmark": benchmark,
        "requested_cutoff": requested,
        "seed_cutoff": seed,
        "attempts": [],
        "research_only": True,
        "trade_ready": False,
    }
    # The governed catalog already published this session, which validated member
    # coverage when it was sealed. Reuse it without any network probe: this keeps
    # push-triggered refreshes free of vendor availability risk.
    published_raw = str(published_cutoff or "").strip()
    if published_raw:
        published = date.fromisoformat(published_raw).isoformat()
        if published >= requested:
            return {
                **base,
                "status": "current" if published == requested else "delayed",
                "observed_cutoff": published,
                "published_cutoff": published,
                "watermark_source": "published_catalog",
                "member_watermarks": {},
                "terminal_excluded_symbols": [],
                "effective_cutoff": requested,
                "effective_seed_cutoff": _previous_completed(market_key, requested),
                "blocker": None,
            }

    data_router = router or build_hardened_router(market_key)
    response = _fetch_with_retries(
        data_router, market_key=market_key, symbol=benchmark, start=seed, end=requested
    )
    base["attempts"] = [attempt.to_dict() for attempt in response.attempts]
    if not response.ok or response.result is None:
        return {
            **base,
            "status": "blocked",
            "effective_cutoff": None,
            "effective_seed_cutoff": None,
            "blocker": "benchmark provider fetch failed",
        }

    dates = pd.to_datetime(response.result.df.get("date"), errors="coerce").dropna()
    if dates.empty:
        return {
            **base,
            "status": "blocked",
            "effective_cutoff": None,
            "effective_seed_cutoff": None,
            "blocker": "benchmark provider returned no complete session",
        }
    observed = pd.Timestamp(dates.max()).tz_localize(None).date().isoformat()
    if observed < seed:
        return {
            **base,
            "status": "blocked",
            "observed_cutoff": observed,
            "effective_cutoff": None,
            "effective_seed_cutoff": None,
            "blocker": "provider complete-session watermark regressed behind governed seed",
        }

    # Strategy-critical members gate the cutoff: blessing a session the
    # strategies cannot consume melts the market build downstream. The
    # watermark read is vendor-independent (dates only), so fallback vendors
    # stay representative even when their adjustment differs.
    # (US has no strategy pool file: its floor stays the benchmark watermark,
    # preserving benchmark-only behavior there.)
    repository_root = Path(__file__).resolve().parents[2]
    probe_symbols = [
        symbol
        for symbol in _strategy_probe_symbols(repository_root, market_key)
        if symbol != benchmark
    ]
    # Lifecycle-declared terminals (delisted/taken-private) carry governed
    # retained history and need no fresh vendor session: probing them would
    # block every run forever after delisting.
    terminals = set(_terminal_listing_entries(market_key, requested))
    terminal_excluded = sorted(set(probe_symbols) & terminals)
    probe_symbols = [symbol for symbol in probe_symbols if symbol not in terminals]
    watermarks: dict[str, str | None] = {}
    for symbol in probe_symbols:
        watermarks[symbol] = _probe_watermark(
            data_router,
            market_key=market_key,
            symbol=symbol,
            start=seed,
            end=requested,
        )
        time.sleep(PROBE_DELAY_SECONDS)
    failed = sorted(symbol for symbol, mark in watermarks.items() if mark is None)
    if failed:
        return {
            **base,
            "status": "blocked",
            "observed_cutoff": observed,
            "member_watermarks": watermarks,
            "terminal_excluded_symbols": terminal_excluded,
            "effective_cutoff": None,
            "effective_seed_cutoff": None,
            "blocker": "strategy-critical provider fetch failed: " + ", ".join(failed),
        }
    member_floor = min([observed] + [str(mark) for mark in watermarks.values() if mark])
    effective = min(member_floor, requested)
    return {
        **base,
        "status": "current" if effective == requested else "delayed",
        "observed_cutoff": observed,
        "member_watermarks": watermarks,
        "terminal_excluded_symbols": terminal_excluded,
        "effective_cutoff": effective,
        "effective_seed_cutoff": _previous_completed(market_key, effective),
        "blocker": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--requested-cutoff", required=True)
    parser.add_argument("--seed-cutoff", required=True)
    parser.add_argument(
        "--published-cutoff",
        default="",
        help=(
            "Governed catalog cutoff for the market. When it already covers the "
            "requested session, readiness is reused without any network probe."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    payload = resolve_formal_provider_cutoff(
        market=args.market,
        requested_cutoff=args.requested_cutoff,
        seed_cutoff=args.seed_cutoff,
        published_cutoff=args.published_cutoff,
    )
    _write_json(args.output, payload)
    if payload["status"] == "blocked":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    _write_github_output(
        args.github_output,
        {
            "provider_status": str(payload["status"]),
            "effective_cutoff": str(payload["effective_cutoff"]),
            "effective_seed_cutoff": str(payload["effective_seed_cutoff"]),
        },
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
