#!/usr/bin/env python3
"""Generate deterministic focus signals without evaluating forward performance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.focus_watchlist_signal import run_focus_watchlist_signal


DEFAULT_SPEC = Path("configs/research_paradigms/us_focus_watchlist_cycle_signal_v1.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/focus_watchlist_cycle_signal")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-csv",
        type=Path,
        required=True,
        help="Long-form CSV with date,symbol,open,high,low,close[,volume].",
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run_focus_watchlist_signal(
        spec_path=args.spec,
        prices_csv=args.prices_csv,
        output_dir=args.output_dir,
    )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if decision["decision"] == "implementation_contract_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
