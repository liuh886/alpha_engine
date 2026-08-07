#!/usr/bin/env python3
"""Run one committed Alpha Research Loop experiment spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cross_sectional_experiment_runner import (
    RUNNER_ID,
    load_cross_sectional_experiment_spec,
    run_cross_sectional_experiment,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one committed research experiment")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    spec = load_cross_sectional_experiment_spec(args.spec)
    if str(spec.raw.get("runner")) != RUNNER_ID:
        raise ValueError(f"unsupported runner: {spec.raw.get('runner')!r}")
    receipt = run_cross_sectional_experiment(
        args.spec,
        output_dir=args.output_dir,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
