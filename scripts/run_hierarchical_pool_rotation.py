#!/usr/bin/env python3
"""Run hierarchical cross-sectional rotation for one versioned market pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.hierarchical_pool_rotation import run_hierarchical_pool_rotation


DEFAULT_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2_draft.yaml"
)
DEFAULT_OUTPUT = Path("artifacts/evidence/hierarchical_pool_rotation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-csv",
        type=Path,
        required=True,
        help="Long-form date,symbol,open,high,low,close[,volume] CSV.",
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--authoritative-mode",
        action="store_true",
        help="Require a frozen pool and an authoritative validation-enabled spec.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_hierarchical_pool_rotation(
        spec_path=args.spec,
        prices_csv=args.prices_csv,
        output_dir=args.output_dir,
        authoritative_mode=args.authoritative_mode,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
