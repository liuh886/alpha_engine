#!/usr/bin/env python3
"""Run canonical online Stage-B validation for one US ranker research spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.us_ranker_exact_portfolio_replay import (
    run_exact_us_ranker_portfolio_replay,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    receipt = run_exact_us_ranker_portfolio_replay(
        args.spec,
        output_dir=args.output_dir,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if receipt.get("status") != "completed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
