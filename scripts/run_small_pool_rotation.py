#!/usr/bin/env python3
"""Run the deterministic small-pool basket rotation engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.small_pool_rotation import run_small_pool_rotation


DEFAULT_SPEC = Path(
    "configs/research_paradigms/us_small_pool_sector_rotation_v1.yaml"
)
DEFAULT_OUTPUT = Path("artifacts/evidence/small_pool_sector_rotation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-csv",
        type=Path,
        required=True,
        help=(
            "Long-form date,symbol,open,high,low,close[,volume] CSV for every "
            "pool candidate plus QQQ and ^SOX/SOX."
        ),
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_small_pool_rotation(
        spec_path=args.spec,
        prices_csv=args.prices_csv,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return (
        0
        if decision["decision"] == "rotation_implementation_contract_passed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
