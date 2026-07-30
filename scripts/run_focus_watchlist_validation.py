#!/usr/bin/env python3
"""Validate frozen focus signals on observed evidence without opening 2026H2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.focus_watchlist_validation import run_focus_watchlist_validation


DEFAULT_SPEC = Path("configs/research_paradigms/us_focus_watchlist_cycle_signal_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/focus_watchlist_cycle_validation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-csv",
        type=Path,
        required=True,
        help="Long-form OHLCV CSV containing every frozen target plus QQQ and ^SOX/SOX.",
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_focus_watchlist_validation(
        spec_path=args.spec,
        prices_csv=args.prices_csv,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
