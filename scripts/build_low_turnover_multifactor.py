#!/usr/bin/env python3
"""Build the frozen low-turnover multi-factor diagnostic candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.low_turnover_multifactor import run_low_turnover_multifactor

DEFAULT_CONTRACT = Path("configs/factors/us_low_turnover_multifactor_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/us_low_turnover_multifactor_v1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fundamental-scores", type=Path, required=True)
    parser.add_argument("--basket-scores", type=Path, required=True)
    parser.add_argument("--relationship-map", type=Path, required=True)
    parser.add_argument("--prices-csv", type=Path, required=True)
    parser.add_argument("--registry-db", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    decision = run_low_turnover_multifactor(
        contract_path=args.contract,
        fundamental_scores_path=args.fundamental_scores,
        basket_scores_path=args.basket_scores,
        relationship_map_path=args.relationship_map,
        prices_csv=args.prices_csv,
        registry_db=args.registry_db,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
