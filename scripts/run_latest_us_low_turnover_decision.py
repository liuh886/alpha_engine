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
        default=Path("artifacts/market_snapshots/us_small_pool_v3"),
    )
    parser.add_argument(
        "--pool",
        type=Path,
        default=Path("configs/pools/us_small_pool_v3.yaml"),
        help="Reviewed pool version whose symbols must all carry quarterly fundamentals.",
    )
    parser.add_argument(
        "--sec-contract",
        type=Path,
        default=Path("configs/providers/sec_companyfacts_fundamentals_v3.yaml"),
    )
    parser.add_argument(
        "--fundamental-contract",
        type=Path,
        default=Path("configs/factors/us_fundamental_acceleration_v3.yaml"),
    )
    parser.add_argument(
        "--rotation-spec",
        type=Path,
        default=Path(
            "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v4.yaml"
        ),
    )
    parser.add_argument(
        "--multifactor-contract",
        type=Path,
        default=Path("configs/factors/us_low_turnover_multifactor_v2.yaml"),
    )
    parser.add_argument(
        "--cutover-contract",
        type=Path,
        default=Path("configs/operations/prospective_shadow_cutover_v2.yaml"),
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
        pool_path=args.pool,
        sec_contract=args.sec_contract,
        fundamental_contract=args.fundamental_contract,
        rotation_spec=args.rotation_spec,
        multifactor_contract=args.multifactor_contract,
        cutover_contract=args.cutover_contract,
        requested_through=args.requested_through,
        start_date=args.start_date,
        fundamentals_csv=args.fundamentals_csv,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
