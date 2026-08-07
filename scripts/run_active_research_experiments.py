#!/usr/bin/env python3
"""Run every active committed Alpha Research Loop mission."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cross_sectional_experiment_runner import (
    RUNNER_ID as CROSS_SECTIONAL_RUNNER,
    run_cross_sectional_experiment,
)

EXPERIMENT_ROOT = PROJECT_ROOT / "configs" / "research_experiments"


def _load(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def active_specs() -> list[Path]:
    result: list[Path] = []
    for path in sorted(EXPERIMENT_ROOT.glob("*.yaml")):
        payload = _load(path)
        if payload.get("active") is True:
            result.append(path)
    return result


def run_spec(path: Path) -> dict[str, Any]:
    payload = _load(path)
    runner = str(payload.get("runner", ""))
    if runner == CROSS_SECTIONAL_RUNNER:
        return run_cross_sectional_experiment(path)
    raise ValueError(f"active experiment {path} declares unsupported runner {runner!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run active research experiment specs")
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()

    specs = [args.spec.resolve()] if args.spec else active_specs()
    if not specs:
        raise ValueError("no active research experiments found")

    receipts: list[dict[str, Any]] = []
    failed = False
    for spec in specs:
        receipt = run_spec(spec)
        receipts.append(receipt)
        if receipt.get("status") != "completed":
            failed = True
    print(json.dumps(receipts, indent=2, sort_keys=True))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
