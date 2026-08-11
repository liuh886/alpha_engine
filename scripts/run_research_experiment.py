#!/usr/bin/env python3
"""Run one committed Alpha Research Loop experiment spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from src.research.cross_sectional_experiment_runner import (
    RUNNER_ID as CROSS_SECTIONAL_RUNNER,
    run_cross_sectional_experiment,
)
from src.research.formal_baseline_onboarding import (
    RUNNER_ID as FORMAL_BASELINE_RUNNER,
    run_formal_baseline_onboarding,
)
from src.research.research_receipt import write_research_receipt
from src.research.rules_based_allocation_experiment_runner import (
    RUNNER_ID as RULES_BASED_ALLOCATION_RUNNER,
    run_rules_based_allocation_experiment,
)


def _runner(path: Path) -> str:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research experiment spec must be a mapping")
    return str(payload.get("runner", ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one committed research experiment")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    runner = _runner(args.spec)
    if runner == CROSS_SECTIONAL_RUNNER:
        receipt = run_cross_sectional_experiment(args.spec, output_dir=args.output_dir)
    elif runner == FORMAL_BASELINE_RUNNER:
        receipt = run_formal_baseline_onboarding(args.spec, output_dir=args.output_dir)
    elif runner == RULES_BASED_ALLOCATION_RUNNER:
        receipt = run_rules_based_allocation_experiment(args.spec)
    else:
        raise ValueError(f"unsupported runner: {runner!r}")
    receipt = write_research_receipt(
        args.spec,
        receipt,
        output_dir=args.output_dir,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
