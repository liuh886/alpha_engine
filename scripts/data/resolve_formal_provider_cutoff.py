"""Resolve the latest complete provider session available for formal refresh."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.data.refresh_selected_pool_prices_v2 import build_hardened_router
from src.data.router import MarketDataRouter
from src.research.market_session_clock import completed_market_date

BENCHMARKS = {"us": "QQQ", "cn": "000300"}


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


def resolve_formal_provider_cutoff(
    *,
    market: str,
    requested_cutoff: str,
    seed_cutoff: str,
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
    data_router = router or build_hardened_router(market_key)
    response = data_router.fetch_daily_bars(
        symbol=benchmark,
        market=market_key,
        start=seed,
        end=requested,
        validate=True,
    )
    attempts = [attempt.to_dict() for attempt in response.attempts]
    base = {
        "schema_version": "1.0",
        "evidence_type": "formal_provider_readiness_v1",
        "market": market_key,
        "benchmark": benchmark,
        "requested_cutoff": requested,
        "seed_cutoff": seed,
        "attempts": attempts,
        "research_only": True,
        "trade_ready": False,
    }
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

    effective = min(observed, requested)
    return {
        **base,
        "status": "current" if effective == requested else "delayed",
        "observed_cutoff": observed,
        "effective_cutoff": effective,
        "effective_seed_cutoff": _previous_completed(market_key, effective),
        "blocker": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--requested-cutoff", required=True)
    parser.add_argument("--seed-cutoff", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    payload = resolve_formal_provider_cutoff(
        market=args.market,
        requested_cutoff=args.requested_cutoff,
        seed_cutoff=args.seed_cutoff,
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
