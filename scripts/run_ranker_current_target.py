#!/usr/bin/env python3
"""Resolve and build the governed CN x1.1 10-session current target."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.market_session_clock import completed_market_date
from src.research.ranker_current_target import (
    CN_MODEL_ID,
    load_previous_state,
    merge_governed_market_sessions,
    next_due_session,
    score_cn_current_target,
)

ROOT = Path(__file__).resolve().parents[1]
MARKET = "cn"
BENCHMARK = "000300"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _formal_portfolio(formal_root: Path) -> Path:
    catalog_path = formal_root / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    records = [
        row
        for row in catalog.get("records", [])
        if isinstance(row, dict) and row.get("model_version_id") == CN_MODEL_ID
    ]
    if len(records) != 1:
        raise ValueError(f"formal catalog must contain exactly one {CN_MODEL_ID} record")
    record = records[0]
    if record.get("publication_status") != "accepted_formal_baseline":
        raise ValueError(f"formal model is not accepted: {CN_MODEL_ID}")
    manifest_path = record.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ValueError(f"formal manifest path is missing: {CN_MODEL_ID}")
    portfolio = formal_root / Path(manifest_path).parent / "portfolio.json"
    if not portfolio.is_file():
        raise ValueError(f"formal portfolio is missing: {portfolio}")
    return portfolio


def _due(args: argparse.Namespace) -> int:
    formal_package = _formal_portfolio(args.formal_root)
    anchor, _ = load_previous_state(
        formal_package=formal_package,
        ledger_dir=args.ledger_dir,
    )
    completed_as_of = completed_market_date(MARKET, args.as_of)
    evidence_path = (
        ROOT
        / "data"
        / "research"
        / "market_evidence"
        / MARKET
        / "symbols"
        / f"{BENCHMARK}.json"
    )
    sessions = merge_governed_market_sessions(
        evidence_path=evidence_path,
        live_sessions=pd.DatetimeIndex([]),
        as_of=completed_as_of,
    )
    due = next_due_session(anchor=anchor, sessions=sessions)
    payload = {
        "market": MARKET,
        "model_version_id": CN_MODEL_ID,
        "anchor": anchor,
        "requested_as_of": args.as_of,
        "as_of": completed_as_of,
        "due": due is not None,
        "signal_date": due,
        "calendar_provider": "completed_session_gate+governed_market_evidence",
        "research_only": True,
        "trade_ready": False,
    }
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _build(args: argparse.Namespace) -> int:
    formal_package = _formal_portfolio(args.formal_root)
    signal = score_cn_current_target(
        provider_dir=args.provider_dir,
        formal_package=formal_package,
        ledger_dir=args.ledger_dir,
        signal_date=args.signal_date,
        market_cutoff=args.market_cutoff,
        repository_root=ROOT,
    )
    _write(args.output, signal)
    print(json.dumps(signal, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    due = subparsers.add_parser("due")
    due.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    due.add_argument("--ledger-dir", type=Path, required=True)
    due.add_argument("--as-of", required=True)
    due.add_argument("--output", type=Path, required=True)
    due.set_defaults(func=_due)

    build = subparsers.add_parser("build")
    build.add_argument("--provider-dir", type=Path, required=True)
    build.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    build.add_argument("--ledger-dir", type=Path, required=True)
    build.add_argument("--signal-date", required=True)
    build.add_argument("--market-cutoff", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
