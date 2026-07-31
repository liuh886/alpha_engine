#!/usr/bin/env python3
"""Run the governed US low-turnover multifactor decision pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.decision_support.us_low_turnover_decision_pipeline import (
    run_us_low_turnover_decision_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--prices-csv", type=Path, required=True)
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
        "--fundamentals-csv",
        type=Path,
        default=None,
        help=(
            "Optional source-bound fundamentals CSV. When omitted, the pipeline "
            "uses SEC Company Facts and requires SEC_USER_AGENT."
        ),
    )
    args = parser.parse_args()
    manifest = run_us_low_turnover_decision_pipeline(
        as_of_date=args.as_of_date,
        prices_csv=args.prices_csv,
        registry_db=args.registry_db,
        ledger_dir=args.ledger_dir,
        workspace_dir=args.workspace_dir,
        fundamentals_csv=args.fundamentals_csv,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
