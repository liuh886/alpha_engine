#!/usr/bin/env python3
"""Run the frozen medium-frequency fundamental validation once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.minimal_fundamental_validation import (
    run_minimal_fundamental_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/factors/us_fundamental_acceleration_v1.yaml"),
    )
    parser.add_argument("--fundamentals-csv", type=Path, required=True)
    parser.add_argument("--prices-csv", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_fundamental_acceleration_validation"),
    )
    parser.add_argument(
        "--registry-db",
        type=Path,
        default=Path("artifacts/factor_registry.db"),
    )
    args = parser.parse_args()
    decision = run_minimal_fundamental_validation(
        contract_path=args.contract,
        fundamentals_csv=args.fundamentals_csv,
        prices_csv=args.prices_csv,
        output_dir=args.output_dir,
        registry_db=args.registry_db,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
