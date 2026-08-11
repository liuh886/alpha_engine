"""Model optimization runner — base class and model-type-specific implementations.

Provides a unified interface for running optimization experiments across
ranker, rotator, and timer model types.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.optimization.contracts import CandidateSpec, CostStructure, ExperimentContract, ModelType
from src.optimization.metrics import (
    CandidateResult,
    GateResult,
    WindowResult,
    aggregate_windows,
    check_gates,
)
from src.optimization.receipts import save_receipt

# ---- Abstract Runner ----


class BaseOptimizationRunner(ABC):
    """Abstract base for all model-type-specific optimization runners.

    Subclasses implement _evaluate_candidate() for their model type.
    The base class handles window iteration, aggregation, gate checking,
    and receipt generation.
    """

    def __init__(self, contract: ExperimentContract, output_dir: Path | str = "artifacts/optimization"):
        self.contract = contract
        self.output_dir = Path(output_dir) / contract.experiment_id
        self._provider_identity: str | None = None

    @abstractmethod
    def _initialize(self) -> None:
        """Initialize runtime, load data, verify provider."""

    @abstractmethod
    def _evaluate_candidate(
        self, candidate: CandidateSpec, window_label: str, cost_bps: float
    ) -> WindowResult | None:
        """Evaluate one candidate on one window at one cost level.

        Returns None if evaluation fails (e.g., data missing).
        """

    def run(self) -> dict[str, Any]:
        """Execute the full experiment and return results."""
        print(f"[optimizer] Starting: {self.contract.experiment_id}")
        print(f"[optimizer] Type: {self.contract.model_type.value} | Market: {self.contract.market}")
        print(f"[optimizer] Candidates: {len(self.contract.candidates)} | Windows: {len(self.contract.windows.labels)}")

        self._initialize()

        windows = self.contract.windows.labels
        cost_levels = (self.contract.cost_structure.base_cost_bps,) + self.contract.cost_structure.stress_cost_bps

        # Per-candidate per-window results
        all_windows: dict[str, dict[str, list[WindowResult]]] = defaultdict(lambda: defaultdict(list))

        for win in windows:
            for candidate in self.contract.candidates:
                for cost in cost_levels:
                    result = self._evaluate_candidate(candidate, win, cost)
                    if result is not None:
                        result.cost_bps = cost
                        all_windows[candidate.candidate_id][win].append(result)

            # Show top-3 for this window
            w20 = []
            for cid, wr_dict in all_windows.items():
                if win in wr_dict:
                    for wr in wr_dict[win]:
                        if wr.cost_bps == self.contract.cost_structure.base_cost_bps:
                            w20.append((cid, wr.relative_excess, wr.max_drawdown))
            w20.sort(key=lambda x: x[1], reverse=True)
            if w20:
                print(f"  [{win}] top-3: " + " | ".join(
                    f"{c}: exc={e:.3f} dd={d:.3f}" for c, e, d in w20[:3]
                ))

        # Aggregate per candidate
        candidates: list[CandidateResult] = []
        for candidate in self.contract.candidates:
            cid = candidate.candidate_id
            base_results = [
                wr for wr_list in all_windows[cid].values()
                for wr in wr_list
                if wr.cost_bps == self.contract.cost_structure.base_cost_bps
            ]
            if len(base_results) < len(windows):
                print(f"[optimizer] WARNING: {cid} has {len(base_results)}/{len(windows)} windows — skipping")
                continue

            # Use one result per window (take first if multiple per cost)
            best_per_win = {}
            for wr in base_results:
                if wr.window not in best_per_win or wr.relative_excess > best_per_win[wr.window].relative_excess:
                    best_per_win[wr.window] = wr

            cr = aggregate_windows(list(best_per_win.values()))
            cr.candidate_id = cid

            # Add cost stress
            for cost in cost_levels:
                cost_wrs = [
                    wr for wr_list in all_windows[cid].values()
                    for wr in wr_list
                    if wr.cost_bps == cost
                ]
                if len(cost_wrs) >= len(windows):
                    best = {}
                    for wr in cost_wrs:
                        if wr.window not in best or wr.relative_excess > best[wr.window].relative_excess:
                            best[wr.window] = wr
                    ordered = [best[w] for w in windows if w in best]
                    sn = math.prod(1.0 + w.strategy_compound for w in ordered)
                    bn = math.prod(1.0 + w.benchmark_compound for w in ordered)
                    cr.cost_stress[int(cost)] = (1.0 + sn) / (1.0 + bn) - 1.0

            cr.metadata["params"] = candidate.params
            cr.metadata["description"] = candidate.description
            candidates.append(cr)

        # Gate check
        baseline = next((c for c in candidates if c.candidate_id == self.contract.baseline_candidate_id), None)
        if baseline is None:
            raise ValueError(f"baseline '{self.contract.baseline_candidate_id}' not found in results")

        gates = []
        for cr in candidates:
            gates.append(check_gates(cr, baseline, self.contract.gate_profile.value))

        passing = [g for g in gates if g.all_pass]
        print(f"[optimizer] Done: {len(passing)}/{len(gates)} candidates pass all gates")

        # Save receipt
        receipt_path = save_receipt(
            self.contract, candidates, gates, self.output_dir,
            provider_identity=self._provider_identity,
        )
        print(f"[optimizer] Receipt: {receipt_path}")

        return {
            "experiment_id": self.contract.experiment_id,
            "candidates": candidates,
            "gates": gates,
            "receipt_path": str(receipt_path),
        }
