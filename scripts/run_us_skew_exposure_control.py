#!/usr/bin/env python3
"""Run Issue #966 Phase-4 single-use US skew exposure-control test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.us_skew_exposure_control import run_us_skew_exposure_control


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt = run_us_skew_exposure_control(args.spec, output_path=args.output)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
