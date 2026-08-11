#!/usr/bin/env python3
"""Run the single active committed Alpha Research Loop mission."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cross_sectional_experiment_runner import (
    RUNNER_ID as CROSS_SECTIONAL_RUNNER,
    load_cross_sectional_experiment_spec,
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

EXPERIMENT_ROOT = PROJECT_ROOT / "configs" / "research_experiments"
TERMINAL_RESEARCH_STATUSES = {
    "completed",
    "completed_not_supported",
    "promoted",
    "retired",
    "superseded",
}


def _load(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload = payload if isinstance(payload, dict) else {}
    status = str(payload.get("status") or "")
    if payload.get("active") is True and status in TERMINAL_RESEARCH_STATUSES:
        raise ValueError(
            f"research experiment {path} cannot be active with terminal status {status!r}"
        )
    return payload


def active_specs() -> list[Path]:
    specs = [
        path
        for path in sorted(EXPERIMENT_ROOT.glob("*.yaml"))
        if _load(path).get("active") is True
    ]
    if len(specs) > 1:
        raise ValueError(
            "Alpha Research Loop permits exactly one active mission at a time: "
            + ", ".join(path.name for path in specs)
        )
    return specs


def run_spec(path: Path) -> dict[str, Any]:
    payload = _load(path)
    if payload.get("active") is not True:
        raise ValueError(f"research experiment {path} must be active")
    runner = str(payload.get("runner", ""))
    if runner == CROSS_SECTIONAL_RUNNER:
        receipt = run_cross_sectional_experiment(path)
    elif runner == FORMAL_BASELINE_RUNNER:
        receipt = run_formal_baseline_onboarding(path)
    elif runner == RULES_BASED_ALLOCATION_RUNNER:
        receipt = run_rules_based_allocation_experiment(path)
    else:
        raise ValueError(f"active experiment {path} declares unsupported runner {runner!r}")
    return write_research_receipt(path, receipt)


def validate_spec(path: Path) -> dict[str, Any]:
    """Validate one active mission without loading providers or running models."""

    payload = _load(path)
    if payload.get("active") is not True:
        raise ValueError(f"research experiment {path} must be active")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise ValueError(f"research experiment {path} violates the research-only boundary")
    runner = str(payload.get("runner", ""))
    if runner == CROSS_SECTIONAL_RUNNER:
        parsed = load_cross_sectional_experiment_spec(path)
        experiment_id = parsed.experiment_id
    elif runner in {FORMAL_BASELINE_RUNNER, RULES_BASED_ALLOCATION_RUNNER}:
        experiment_id = str(payload.get("experiment_id") or "")
        if not experiment_id:
            raise ValueError(f"active experiment {path} has no experiment_id")
    else:
        raise ValueError(f"active experiment {path} declares unsupported runner {runner!r}")
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "experiment_id": experiment_id,
        "runner": runner,
        "status": "valid",
        "models_executed": False,
        "providers_rebuilt": False,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the active research experiment spec")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    specs = [args.spec.resolve()] if args.spec else active_specs()
    if not specs:
        print("[]")
        return 0

    if args.validate_only:
        print(json.dumps([validate_spec(path) for path in specs], indent=2, sort_keys=True))
        return 0

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
