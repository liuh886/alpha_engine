#!/usr/bin/env python3
"""Model Optimizer CLI — v2 with Ranker, Rotator, and Timer support.

Usage:
    # Ranker (cross-sectional stock ranking):
    python scripts/run_model_optimizer.py --spec configs/optimization/example_usx_grid.yaml

    # Rotator (ETF rotation like QQQR):
    python scripts/run_model_optimizer.py --spec configs/optimization/qqqr_grid.yaml

    # Timer (single-stock timing like BYD):
    python scripts/run_model_optimizer.py --spec configs/optimization/byd_grid.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src.optimization.contracts import (
    CandidateSpec, CostStructure, ExperimentContract,
    GateProfile, ModelType, WindowSpec,
)
from src.optimization.runner import BaseOptimizationRunner
from src.optimization.ranker_runner import RankerOptimizer
from src.optimization.rotator_runner import RotatorOptimizer
from src.optimization.timer_runner import TimerOptimizer


def load_spec(path: str | Path) -> ExperimentContract:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("spec must be a YAML mapping")

    mt = ModelType(raw.get("model_type", "ranker"))

    cost_raw = raw.get("cost_structure", {})
    cost = CostStructure(
        base_cost_bps=float(cost_raw.get("base_cost_bps", 20.0)),
        stress_cost_bps=tuple(float(x) for x in cost_raw.get("stress_cost_bps", [40.0, 60.0])),
        annual_financing_rate=cost_raw.get("annual_financing_rate"),
    )

    win_raw = raw.get("windows", {})
    windows = WindowSpec(
        labels=tuple(str(w) for w in win_raw.get("labels", ["2024H1", "2024H2", "2025H1", "2025H2"])),
        train_start=str(win_raw.get("train_start", "2021-01-01")),
        first_test_year=int(win_raw.get("first_test_year", 2024)),
        last_test_year=int(win_raw.get("last_test_year", 2025)),
        horizon_sessions=int(win_raw.get("horizon_sessions", 10)),
        cadence_sessions=int(win_raw.get("cadence_sessions", 10)),
        min_complete_windows=int(win_raw.get("min_complete_windows", 3)),
        partial_window_policy=str(win_raw.get("partial_window_policy", "complete_windows_only")),
        reporting_windows=tuple(str(w) for w in win_raw.get("reporting_windows", [])),
    )

    candidates = []
    for c in raw.get("candidates", []):
        candidates.append(CandidateSpec(
            candidate_id=str(c["candidate_id"]),
            role=str(c.get("role", "challenger")),
            params=dict(c.get("params", {})),
            description=str(c.get("description", "")),
        ))

    gp = GateProfile(raw.get("gate_profile", "ten_day_model_gates_v1"))

    contract = ExperimentContract(
        experiment_id=str(raw.get("experiment_id", Path(path).stem)),
        model_type=mt, market=str(raw.get("market", "us")),
        benchmark=str(raw.get("benchmark", "QQQ")),
        cost_structure=cost, windows=windows,
        candidates=tuple(candidates),
        baseline_candidate_id=str(raw.get("baseline_candidate_id", candidates[0].candidate_id if candidates else "baseline")),
        gate_profile=gp,
        provider_uri=raw.get("provider_uri"),
        universe_config=raw.get("universe_config"),
        factor_library=raw.get("factor_library"),
        sector_config=raw.get("sector_config"),
        metadata=dict(raw.get("metadata", {})),
    )
    return contract


def get_runner(contract: ExperimentContract, output_dir: str) -> BaseOptimizationRunner:
    """Factory: select runner by model type."""
    runners = {
        ModelType.RANKER: RankerOptimizer,
        ModelType.ROTATOR: RotatorOptimizer,
        ModelType.TIMER: TimerOptimizer,
    }
    cls = runners.get(contract.model_type)
    if cls is None:
        print(f"[optimizer] Model type '{contract.model_type.value}' requires CUSTOM runner.")
        print("[optimizer] Subclass BaseOptimizationRunner and implement _evaluate_candidate().")
        sys.exit(1)
    return cls(contract, output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=str, default="artifacts/optimization")
    args = parser.parse_args()

    contract = load_spec(str(args.spec))
    print(f"[optimizer] {contract.experiment_id}")
    print(f"[optimizer] Type: {contract.model_type.value} | Market: {contract.market} | Benchmark: {contract.benchmark}")
    print(f"[optimizer] Cost: {contract.cost_structure.base_cost_bps}bps | Windows: {contract.windows.labels}")
    print(f"[optimizer] Candidates: {len(contract.candidates)}")

    runner = get_runner(contract, args.output_dir)
    result = runner.run()

    passing = [g for g in result["gates"] if g.all_pass]
    if passing:
        best = max(passing, key=lambda g: g.selection_score)
        print(f"\n[optimizer] BEST: {best.candidate_id} (score={best.selection_score:.4f})")
        print(f"[optimizer] Passing: {[g.candidate_id for g in passing]}")
    else:
        print(f"\n[optimizer] No candidate passed all gates.")


if __name__ == "__main__":
    main()
