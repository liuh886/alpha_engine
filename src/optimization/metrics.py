"""Standardized metrics and gate checking for model optimization.

All metrics computed identically regardless of model type or runner.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class WindowResult:
    """Single-window evaluation result."""
    window: str
    relative_excess: float
    max_drawdown: float
    strategy_compound: float
    benchmark_compound: float
    n_periods: int
    positive_periods: int = 0
    cost_bps: float = 20.0
    total_cost: float = 0.0
    total_turnover: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateResult:
    """Aggregated cross-window result for one candidate."""
    candidate_id: str
    windows: dict[str, WindowResult]
    compounded_relative_excess: float
    worst_drawdown: float
    positive_windows: int
    total_windows: int
    strongest_window_share: float
    cost_stress: dict[int, float] = field(default_factory=dict)  # cost_bps -> compounded excess
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def all_windows_positive(self) -> bool:
        return self.positive_windows == self.total_windows


@dataclass
class GateResult:
    """Gate checking result for a single candidate."""
    candidate_id: str
    gates: dict[str, bool]
    all_pass: bool
    selection_score: float


def compound_returns(returns: list[float]) -> float:
    """Compound a sequence of period returns."""
    return math.prod(1.0 + r for r in returns) - 1.0


def relative_excess(strategy_compound: float, benchmark_compound: float) -> float:
    """Compute geometric relative excess: strategy_nav / benchmark_nav - 1."""
    if benchmark_compound <= -1.0:
        return 0.0
    return (1.0 + strategy_compound) / (1.0 + benchmark_compound) - 1.0


def max_drawdown(equity_curve: list[float]) -> float:
    """Compute maximum drawdown from equity curve."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < worst:
            worst = dd
    return float(worst)


def strongest_window_share(window_excesses: list[float]) -> float:
    """Share of total positive excess from the strongest window."""
    positive = [e for e in window_excesses if e > 0]
    if not positive:
        return 1.0
    return max(positive) / sum(positive)


def aggregate_windows(window_results: list[WindowResult]) -> CandidateResult:
    """Aggregate per-window results into a candidate result."""
    if not window_results:
        raise ValueError("no window results to aggregate")

    wr_by_label = {w.window: w for w in window_results}
    ordered = [wr_by_label[w] for w in sorted(wr_by_label)]

    strategy_nav = compound_returns([w.strategy_compound for w in ordered])
    benchmark_nav = compound_returns([w.benchmark_compound for w in ordered])
    compounded_re = relative_excess(strategy_nav, benchmark_nav)

    worst_dd = min(w.max_drawdown for w in ordered)
    positive = sum(1 for w in ordered if w.relative_excess > 0)
    strongest = strongest_window_share([w.relative_excess for w in ordered])

    # Cost stress
    cost_stress: dict[int, float] = {}
    for cost in sorted(set(w.cost_bps for w in ordered)):
        cost_ordered = [w for w in ordered if w.cost_bps == cost]
        if len(cost_ordered) == len(ordered):
            sn = compound_returns([w.strategy_compound for w in cost_ordered])
            bn = compound_returns([w.benchmark_compound for w in cost_ordered])
            cost_stress[int(cost)] = relative_excess(sn, bn)

    return CandidateResult(
        candidate_id=ordered[0].candidate_id if hasattr(ordered[0], 'candidate_id') else "unknown",
        windows=wr_by_label,
        compounded_relative_excess=compounded_re,
        worst_drawdown=worst_dd,
        positive_windows=positive,
        total_windows=len(ordered),
        strongest_window_share=strongest,
        cost_stress=cost_stress,
        metadata=ordered[0].metadata,
    )


def check_gates(
    candidate: CandidateResult,
    baseline: CandidateResult,
    gate_profile: str = "ten_day_model_gates_v1",
) -> GateResult:
    """Check all gates for a candidate against the baseline.

    Standard gates:
    1. DD improves 3pp OR stays above -22%
    2. All windows have positive excess
    3. Strongest window share < 55%
    4. Retain at least 90% of baseline compounded excess (20bps)
    5. Positive 60bps stress excess
    6. Mean Rank IC not materially weaker (optional — only for rankers)
    """
    gates: dict[str, bool] = {}

    # Gate 1: Drawdown
    dd_improvement = baseline.worst_drawdown - candidate.worst_drawdown
    gates["dd_improves_3pp_or_above_m22"] = (
        dd_improvement >= 0.03 or candidate.worst_drawdown >= -0.22
    )

    # Gate 2: All windows positive
    gates["all_windows_positive_excess"] = candidate.all_windows_positive

    # Gate 3: Concentration
    gates["strongest_window_share_below_55pct"] = candidate.strongest_window_share < 0.55

    # Gate 4: Retain baseline excess
    gates["retain_90pct_baseline_excess"] = (
        candidate.compounded_relative_excess >= 0.90 * baseline.compounded_relative_excess
    )

    # Gate 5: 60bps stress
    exc_60 = candidate.cost_stress.get(60)
    gates["positive_60bps_excess"] = exc_60 is not None and exc_60 > 0

    # Gate 6: Rank IC (optional — only fail if explicitly provided and worse)
    baseline_ic = baseline.metadata.get("mean_rank_ic")
    candidate_ic = candidate.metadata.get("mean_rank_ic")
    if baseline_ic is not None and candidate_ic is not None:
        gates["rank_ic_not_materially_weaker"] = candidate_ic >= max(0.0, baseline_ic - 0.005)
    else:
        gates["rank_ic_not_materially_weaker"] = True  # Not applicable

    all_pass = all(gates.values())

    # Selection score (same formula used across USx experiments)
    penalty = max(0.0, -candidate.worst_drawdown - 0.22)
    selection_score = (
        candidate.compounded_relative_excess
        - 1.5 * penalty
        + 0.15 * candidate.metadata.get("mean_icir", 0.0)
        + 0.10 * candidate.metadata.get("mean_rank_ic", 0.0)
        + 0.10 * (1.0 - candidate.strongest_window_share)
    )

    return GateResult(
        candidate_id=candidate.candidate_id,
        gates=gates,
        all_pass=all_pass,
        selection_score=selection_score,
    )
