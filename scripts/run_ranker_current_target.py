#!/usr/bin/env python3
"""Resolve and build current targets for the active 10-session rankers."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import load_active_strategy_runtime_capabilities
from src.research.cn_x1_2_current_target import score_cn_x1_2_current_target
from src.research.market_session_clock import completed_market_date
from src.research.ranker_current_target import (
    load_previous_state,
    next_due_session,
)
from src.research.us_x1_3_current_target import score_us_x1_3_current_target

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {
    "us_x1_3_current_target_v1": score_us_x1_3_current_target,
    "cn_x1_2_current_target_v1": score_cn_x1_2_current_target,
}
EXCHANGE_CALENDAR_IDS = {"us": "XNYS", "cn": "XSHG"}


class RankerCurrentTargetCommandError(ValueError):
    """Raised when an active ranker cannot be resolved exactly."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RankerCurrentTargetCommandError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _strategy(market: str):
    active = load_active_strategy_catalog()
    matches = [
        row
        for row in active.strategies
        if row.market == market and row.model_kind == "cross_sectional_ranker"
    ]
    if len(matches) != 1:
        raise RankerCurrentTargetCommandError(
            f"expected one active {market} ranker, found {len(matches)}"
        )
    strategy = matches[0]
    capability = load_active_strategy_runtime_capabilities(active=active)[
        strategy.strategy_id
    ].current_target
    if capability.status != "available" or capability.adapter_id not in ADAPTERS:
        raise RankerCurrentTargetCommandError(
            capability.reason
            or f"current-target adapter unavailable for {strategy.model_version_id}"
        )
    return strategy, capability.adapter_id


def resolve_formal_bundle(formal_root: Path, *, market: str) -> tuple[Path, Path, Any, str]:
    strategy, adapter_id = _strategy(market)
    formal_root = formal_root.resolve()
    catalog = _read(formal_root / "catalog.json")
    records = [
        row
        for row in catalog.get("records", [])
        if isinstance(row, dict)
        and row.get("model_family_id") == strategy.model_family_id
        and row.get("model_version_id") == strategy.model_version_id
        and row.get("publication_status") == "accepted_formal_baseline"
    ]
    if len(records) != 1:
        raise RankerCurrentTargetCommandError(
            f"expected one accepted formal {strategy.model_version_id} record, found {len(records)}"
        )
    record = records[0]
    manifest = formal_root / str(record.get("manifest_path") or "")
    if not manifest.is_file() or _sha256(manifest) != record.get("manifest_sha256"):
        raise RankerCurrentTargetCommandError("formal manifest identity mismatch")
    payload = _read(manifest)
    if (
        payload.get("publication_channel") != "formal"
        or payload.get("publication_status") != "accepted_formal_baseline"
        or payload.get("bundle_id") != record.get("bundle_id")
        or payload.get("research_only") is not True
        or payload.get("trade_ready") is not False
    ):
        raise RankerCurrentTargetCommandError("formal publication boundary changed")
    portfolio_rows = [
        row
        for row in payload.get("sections", [])
        if isinstance(row, dict) and row.get("section_id") == "portfolio"
    ]
    if len(portfolio_rows) != 1 or portfolio_rows[0].get("availability_status") != "available":
        raise RankerCurrentTargetCommandError("formal portfolio section is unavailable")
    section = portfolio_rows[0]
    portfolio = manifest.parent / str(section.get("path") or "")
    if (
        not portfolio.is_file()
        or _sha256(portfolio) != section.get("sha256")
        or portfolio.stat().st_size != section.get("byte_size")
    ):
        raise RankerCurrentTargetCommandError("formal portfolio identity mismatch")
    return manifest, portfolio, strategy, adapter_id


def _exchange_sessions(*, market: str, start: str, end: str) -> pd.DatetimeIndex:
    calendar_id = EXCHANGE_CALENDAR_IDS.get(market)
    if calendar_id is None:
        raise RankerCurrentTargetCommandError(f"unsupported exchange calendar market: {market}")
    try:
        sessions = xcals.get_calendar(calendar_id).sessions_in_range(start, end)
    except Exception as exc:
        raise RankerCurrentTargetCommandError(
            f"unable to resolve {calendar_id} sessions from {start} through {end}: {exc}"
        ) from exc
    return pd.DatetimeIndex(sessions).tz_localize(None).normalize()


def _validated_governed_sessions(
    *, evidence_path: Path, market: str, benchmark: str
) -> pd.DatetimeIndex:
    catalog_path = evidence_path.parent.parent / "catalog.json"
    if not catalog_path.is_file() or not evidence_path.is_file():
        raise RankerCurrentTargetCommandError("governed benchmark evidence is unavailable")
    catalog = _read(catalog_path)
    evidence = _read(evidence_path)
    expected_instrument = f"{market}:{benchmark}"
    if (
        catalog.get("evidence_type") != "market_evidence_catalog"
        or catalog.get("market") != market
        or catalog.get("benchmark") != benchmark
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
        or not _is_sha256(catalog.get("provider_identity_sha256"))
        or not _is_sha256(catalog.get("input_identity_sha256"))
        or not _is_sha256(catalog.get("provider_manifest_sha256"))
    ):
        raise RankerCurrentTargetCommandError("governed market evidence catalog identity mismatch")
    records = [
        row
        for row in catalog.get("symbols", [])
        if isinstance(row, dict) and row.get("symbol") == benchmark
    ]
    relative_path = evidence_path.relative_to(catalog_path.parent).as_posix()
    if (
        len(records) != 1
        or records[0].get("path") != relative_path
        or records[0].get("sha256") != _sha256(evidence_path)
        or records[0].get("instrument_id") != expected_instrument
    ):
        raise RankerCurrentTargetCommandError("governed benchmark catalog record mismatch")
    if (
        evidence.get("evidence_type") != "security_market_evidence"
        or evidence.get("market") != market
        or evidence.get("symbol") != benchmark
        or evidence.get("instrument_id") != expected_instrument
        or evidence.get("research_only") is not True
        or evidence.get("trade_ready") is not False
        or evidence.get("provider_manifest_sha256") != catalog.get("provider_manifest_sha256")
        or not _is_sha256(evidence.get("source_csv_sha256"))
    ):
        raise RankerCurrentTargetCommandError("governed benchmark evidence identity mismatch")
    bars = evidence.get("bars")
    if not isinstance(bars, list) or not bars:
        raise RankerCurrentTargetCommandError("governed benchmark evidence has no bars")
    raw_dates = [row.get("time") for row in bars if isinstance(row, dict)]
    if len(raw_dates) != len(bars):
        raise RankerCurrentTargetCommandError("governed benchmark evidence contains invalid bars")
    parsed = pd.to_datetime(raw_dates, errors="coerce")
    if pd.isna(parsed).any():
        raise RankerCurrentTargetCommandError("governed benchmark evidence contains invalid dates")
    sessions = pd.DatetimeIndex(parsed).tz_localize(None).normalize()
    if sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise RankerCurrentTargetCommandError(
            "governed benchmark evidence sessions are not unique and ordered"
        )
    boundaries = pd.to_datetime([evidence.get("start"), evidence.get("cutoff")], errors="coerce")
    if pd.isna(boundaries).any():
        raise RankerCurrentTargetCommandError(
            "governed benchmark evidence contains invalid boundaries"
        )
    start, cutoff = (pd.Timestamp(value).normalize() for value in boundaries)
    if (
        start != sessions.min()
        or cutoff != sessions.max()
        or records[0].get("cutoff") != cutoff.strftime("%Y-%m-%d")
        or catalog.get("cutoff") != cutoff.strftime("%Y-%m-%d")
    ):
        raise RankerCurrentTargetCommandError("governed benchmark evidence cutoff mismatch")
    expected = _exchange_sessions(
        market=market,
        start=start.strftime("%Y-%m-%d"),
        end=cutoff.strftime("%Y-%m-%d"),
    )
    if not sessions.equals(expected):
        raise RankerCurrentTargetCommandError(
            "governed benchmark evidence does not match the exchange calendar"
        )
    return sessions


def _resolve_market_sessions(
    *,
    evidence_path: Path,
    market: str,
    benchmark: str,
    as_of: str,
) -> tuple[pd.DatetimeIndex, str]:
    """Resolve an exact exchange calendar bound to governed benchmark identity."""

    governed = _validated_governed_sessions(
        evidence_path=evidence_path,
        market=market,
        benchmark=benchmark,
    )
    sessions = _exchange_sessions(
        market=market,
        start=pd.Timestamp(governed.min()).strftime("%Y-%m-%d"),
        end=as_of,
    )
    calendar_id = EXCHANGE_CALENDAR_IDS[market]
    version = importlib.metadata.version("exchange-calendars")
    return (
        sessions,
        "completed_session_gate+"
        f"exchange_calendars@{version}:{calendar_id}+governed_market_evidence_identity",
    )


def _due(args: argparse.Namespace) -> int:
    _, portfolio, strategy, _ = resolve_formal_bundle(args.formal_root, market=args.market)
    ledger_dir = Path(strategy.signal_ledger)
    anchor, _ = load_previous_state(formal_package=portfolio, ledger_dir=ledger_dir)
    completed_as_of = completed_market_date(args.market, args.as_of)
    evidence_path = (
        ROOT
        / "data"
        / "research"
        / "market_evidence"
        / args.market
        / "symbols"
        / f"{strategy.benchmark_id}.json"
    )
    sessions, calendar_provider = _resolve_market_sessions(
        evidence_path=evidence_path,
        market=args.market,
        benchmark=strategy.benchmark_id,
        as_of=completed_as_of,
    )
    if not (ledger_dir / "latest.json").is_file():
        due = pd.Timestamp(sessions.max()).strftime("%Y-%m-%d") if len(sessions) else None
    else:
        due = next_due_session(anchor=anchor, sessions=sessions)
    payload = {
        "market": args.market,
        "strategy_id": strategy.strategy_id,
        "model_version_id": strategy.model_version_id,
        "anchor": anchor,
        "requested_as_of": args.as_of,
        "as_of": completed_as_of,
        "due": due is not None,
        "signal_date": due,
        "calendar_provider": calendar_provider,
        "research_only": True,
        "trade_ready": False,
    }
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _build(args: argparse.Namespace) -> int:
    manifest, portfolio, strategy, adapter_id = resolve_formal_bundle(
        args.formal_root, market=args.market
    )
    common = {
        "provider_dir": args.provider_dir,
        "formal_manifest": manifest,
        "formal_portfolio": portfolio,
        "ledger_dir": Path(strategy.signal_ledger),
        "signal_date": args.signal_date,
        "market_cutoff": args.market_cutoff,
        "repository_root": ROOT,
    }
    signal = ADAPTERS[adapter_id](**common)
    if signal.get("model_version_id") != strategy.model_version_id:
        raise RankerCurrentTargetCommandError("current-target adapter changed model identity")
    _write(args.output, signal)
    print(json.dumps(signal, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    due = subparsers.add_parser("due")
    due.add_argument("--market", choices=("us", "cn"), required=True)
    due.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    due.add_argument("--as-of", required=True)
    due.add_argument("--output", type=Path, required=True)
    due.set_defaults(func=_due)

    build = subparsers.add_parser("build")
    build.add_argument("--market", choices=("us", "cn"), required=True)
    build.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    build.add_argument("--provider-dir", type=Path, required=True)
    build.add_argument("--signal-date", required=True)
    build.add_argument("--market-cutoff", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
