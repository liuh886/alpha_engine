#!/usr/bin/env python3
"""Run selection-window factor redundancy diagnostics for one research spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.factor_redundancy import evaluate_factor_redundancy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = evaluate_factor_redundancy(args.spec, output_path=args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
