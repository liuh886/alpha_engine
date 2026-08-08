#!/usr/bin/env python3
"""Resolve and build governed 10-session current targets for formal rankers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.research.ranker_current_target import (
    CN_MODEL_ID,
    US_MODEL_ID,
    load_previous_state,
    next_due_session,
    score_cn_current_target,
    score_us_current_target,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _due(args: argparse.Namespace) -> int:
    anchor, _ = load_previous_state(
        formal_package=args.formal_package,
        ledger_dir=args.ledger_dir,
    )
    benchmark = "QQQ" if args.market == "us" else "000300"
    bars = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(
            symbol=benchmark,
            market=args.market,
            start=anchor,
            end=args.as_of,
        )
    ).df
    sessions = pd.DatetimeIndex(pd.to_datetime(bars["date"]))
    due = next_due_session(anchor=anchor, sessions=sessions)
    payload = {
        "market": args.market,
        "model_version_id": US_MODEL_ID if args.market == "us" else CN_MODEL_ID,
        "anchor": anchor,
        "as_of": args.as_of,
        "due": due is not None,
        "signal_date": due,
        "calendar_provider": "yfinance_benchmark_session_probe",
        "research_only": True,
        "trade_ready": False,
    }
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _build(args: argparse.Namespace) -> int:
    scorer = score_us_current_target if args.market == "us" else score_cn_current_target
    signal = scorer(
        provider_dir=args.provider_dir,
        formal_package=args.formal_package,
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
    due.add_argument("--market", choices=("us", "cn"), required=True)
    due.add_argument("--formal-package", type=Path, required=True)
    due.add_argument("--ledger-dir", type=Path, required=True)
    due.add_argument("--as-of", required=True)
    due.add_argument("--output", type=Path, required=True)
    due.set_defaults(func=_due)

    build = subparsers.add_parser("build")
    build.add_argument("--market", choices=("us", "cn"), required=True)
    build.add_argument("--provider-dir", type=Path, required=True)
    build.add_argument("--formal-package", type=Path, required=True)
    build.add_argument("--ledger-dir", type=Path, required=True)
    build.add_argument("--signal-date", required=True)
    build.add_argument("--market-cutoff", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
