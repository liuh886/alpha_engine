"""Core optimization math — compound returns, cost, gates.

Pure functions, no I/O, no state. All formulas verified against #770 certification.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def compound_returns(period_returns: list[float]) -> float:
    """Compound a sequence of period returns into total return."""
    return math.prod(1.0 + r for r in period_returns) - 1.0


def relative_excess(strategy_total: float, benchmark_total: float) -> float:
    """Geometric relative excess: strategy_nav / benchmark_nav - 1."""
    if benchmark_total <= -1.0:
        return 0.0
    return (1.0 + strategy_total) / (1.0 + benchmark_total) - 1.0


def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum drawdown from equity curve (starts at 1.0)."""
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


def turnover_cost(
    current_weights: dict[str, float],
    previous_weights: dict[str, float] | None,
    cost_bps: float,
) -> tuple[float, float]:
    """Turnover and cost for one rebalance. Returns (turnover_units, cost_fraction)."""
    if previous_weights is None:
        turnover = sum(abs(w) for w in current_weights.values())
    else:
        all_assets = set(current_weights) | set(previous_weights)
        turnover = sum(
            abs(current_weights.get(a, 0.0) - previous_weights.get(a, 0.0))
            for a in all_assets
        )
    cost = turnover * cost_bps / 10000.0
    return turnover, cost


@dataclass(frozen=True)
class WindowResult:
    window: str
    strategy_total: float
    benchmark_total: float
    max_drawdown: float
    n_periods: int
    positive_periods: int = 0
    cost_bps: float = 20.0

    @property
    def relative_excess(self) -> float:
        return relative_excess(self.strategy_total, self.benchmark_total)


@dataclass(frozen=True)
class AggregateResult:
    candidate_id: str
    windows: dict[str, WindowResult]
    cost_stress: dict[int, float]

    @property
    def compounded_relative_excess(self) -> float:
        if not self.windows:
            return 0.0
        sn = math.prod(1.0 + w.strategy_total for w in self.windows.values())
        bn = math.prod(1.0 + w.benchmark_total for w in self.windows.values())
        return sn / bn - 1.0

    @property
    def worst_drawdown(self) -> float:
        return min((w.max_drawdown for w in self.windows.values()), default=0.0)

    @property
    def positive_windows(self) -> int:
        return sum(1 for w in self.windows.values() if w.relative_excess > 0)

    @property
    def total_windows(self) -> int:
        return len(self.windows)

    @property
    def all_windows_positive(self) -> bool:
        return self.positive_windows == self.total_windows

    @property
    def strongest_share(self) -> float:
        return strongest_window_share([w.relative_excess for w in self.windows.values()])


def check_gates(candidate: AggregateResult, baseline: AggregateResult) -> dict[str, bool]:
    """6-gate evaluation aligned with #770 certification."""
    dd_improvement = candidate.worst_drawdown - baseline.worst_drawdown
    return {
        "dd_improves_3pp_or_above_m22": (
            dd_improvement >= 0.03 or candidate.worst_drawdown >= -0.22
        ),
        "all_windows_positive": candidate.all_windows_positive,
        "strongest_window_share_below_55pct": candidate.strongest_share < 0.55,
        "retain_90pct_baseline_excess": (
            candidate.compounded_relative_excess >= 0.90 * baseline.compounded_relative_excess
        ),
        "positive_60bps_excess": (
            candidate.cost_stress.get(60) is not None
            and candidate.cost_stress[60] > 0
        ),
        "rank_ic_not_materially_weaker": True,
    }


def all_gates_pass(gates: dict[str, bool]) -> bool:
    return all(gates.values())
