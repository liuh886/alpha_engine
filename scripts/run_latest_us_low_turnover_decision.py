#!/usr/bin/env python3
"""Refresh US pool prices and run the latest complete low-turnover decision cycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.decision_support.latest_us_low_turnover_run import (
    run_latest_us_low_turnover_decision,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requested-through", default=None)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument(
        "--registry-db",
        type=Path,
        default=Path("artifacts/factor_registry.db"),
    )
    parser.add_argument(
        "--ledger-dir",
        type=Path,
        default=Path("artifacts/decision_ledger"),
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=Path("artifacts/forward_shadow_runs"),
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path("artifacts/market_snapshots/us_small_pool_v1"),
    )
    parser.add_argument(
        "--fundamentals-csv",
        type=Path,
        default=None,
        help="Optional source-bound fundamentals; otherwise SEC_USER_AGENT is required.",
    )
    args = parser.parse_args()
    manifest = run_latest_us_low_turnover_decision(
        registry_db=args.registry_db,
        ledger_dir=args.ledger_dir,
        workspace_dir=args.workspace_dir,
        snapshot_root=args.snapshot_root,
        requested_through=args.requested_through,
        start_date=args.start_date,
        fundamentals_csv=args.fundamentals_csv,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
