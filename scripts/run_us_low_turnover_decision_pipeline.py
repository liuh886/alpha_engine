#!/usr/bin/env python3
"""Run the complete US low-turnover diagnostic decision pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.decision_support.us_low_turnover_decision_pipeline import (
    run_us_low_turnover_decision_pipeline,
)

DEFAULT_PIPELINE = Path(
    "configs/operations/us_low_turnover_decision_pipeline_v1.yaml"
)
DEFAULT_REGISTRY = Path("artifacts/factor_registry.db")
DEFAULT_WORKSPACE = Path("artifacts/us_low_turnover_decision_pipeline")
DEFAULT_LEDGER = Path("artifacts/decision_ledger")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--prices-csv", type=Path, required=True)
    parser.add_argument("--pipeline-contract", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--registry-db", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    decision = run_us_low_turnover_decision_pipeline(
        pipeline_contract_path=args.pipeline_contract,
        as_of_date=args.as_of_date,
        prices_csv=args.prices_csv,
        registry_db=args.registry_db,
        workspace_dir=args.workspace_dir,
        ledger_dir=args.ledger_dir,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision.get("decision") == "us_low_turnover_diagnostic_ticket_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
