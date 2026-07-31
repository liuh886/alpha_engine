#!/usr/bin/env python3
"""Build point-in-time fundamental acceleration scores and selections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.fundamental_acceleration import run_fundamental_acceleration

DEFAULT_CONTRACT = Path("configs/factors/us_fundamental_acceleration_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/us_fundamental_acceleration")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fundamentals-csv", type=Path, required=True)
    parser.add_argument("--prices-csv", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--registry-db", type=Path, default=None)
    args = parser.parse_args()
    decision = run_fundamental_acceleration(
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
