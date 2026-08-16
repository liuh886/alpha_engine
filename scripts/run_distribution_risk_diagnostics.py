#!/usr/bin/env python3
"""Run Issue #966 Phase-4 distribution-state diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.distribution_risk_diagnostics import evaluate_distribution_risk


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = evaluate_distribution_risk(args.spec, output_path=args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
