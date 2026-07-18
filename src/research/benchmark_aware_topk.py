"""Benchmark-aware Top-K / Bottom-K / Top-K-minus-Bottom-K portfolio evidence.

This module evaluates a single score frame against canonical raw forward 10D
returns and an actual benchmark return frame, producing three labelled outputs:

* **Top-K long-only** — executable-style research portfolio (cost-aware, equal-weight).
* **Bottom-K long-only** — ranked by negated score (cost-aware, equal-weight).
* **Top-K-minus-Bottom-K** — diagnostic-only long-short spread derived from aligned
  net period returns.  It does **not** model borrow availability, borrow cost,
  or short-sale feasibility and is not trade-ready.

All three outputs share the same non-overlapping ``PortfolioIntent`` / vectorized
backtest economics so the arithmetic is consistent across legs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.research.portfolio_intent import (
    PortfolioIntent,
    SignalFrame,
    evaluate_portfolio_intent,
    score_to_equal_weight_intent,
)


# ── validation helpers ──────────────────────────────────────────────────────


def _validate_raw_10d_returns(returns: pd.DataFrame) -> None:
    """Fail closed if *returns* are not canonical raw forward 10D returns."""
    if list(returns.columns) != ["return"]:
        raise ValueError("returns must contain exactly one 'return' column")
    if not isinstance(returns.index, pd.MultiIndex):
        raise ValueError("returns frame must use a MultiIndex")
    if set(returns.index.names) != {"datetime", "instrument"}:
        raise ValueError(
            "returns frame index levels must be named 'datetime' and 'instrument'"
        )
    if returns.empty:
        raise ValueError("returns frame must not be empty")
    if returns.index.duplicated().any():
        raise ValueError("returns frame index contains duplicate entries")
    provenance = returns.attrs.get("provenance")
    if provenance != "raw_forward_return":
        raise ValueError(
            f"returns provenance must be 'raw_forward_return', got {provenance!r}"
        )
    horizon = returns.attrs.get("horizon")
    if horizon != 10:
        raise ValueError(f"returns horizon must be 10, got {horizon!r}")
    if returns.dropna().empty:
        raise ValueError("returns frame has no usable (non-NaN) data")


def _validate_benchmark_returns(benchmark: pd.DataFrame) -> None:
    """Fail closed if *benchmark* is not canonical raw forward 10D returns."""
    if benchmark.empty:
        raise ValueError("benchmark_returns must not be empty")
    if len(benchmark.columns) != 1:
        raise ValueError(
            "benchmark_returns must have exactly one column, "
            f"got {len(benchmark.columns)}"
        )
    if not isinstance(benchmark.index, pd.DatetimeIndex):
        raise ValueError(
            "benchmark_returns must have a DatetimeIndex, "
            f"got {type(benchmark.index).__name__}"
        )
    if benchmark.index.duplicated().any():
        raise ValueError("benchmark_returns index contains duplicate dates")
    provenance = benchmark.attrs.get("provenance")
    if provenance != "raw_forward_return":
        raise ValueError(
            f"benchmark_returns provenance must be 'raw_forward_return', "
            f"got {provenance!r}"
        )
    horizon = benchmark.attrs.get("horizon")
    if horizon != 10:
        raise ValueError(
            f"benchmark_returns horizon must be 10, got {horizon!r}"
        )
    if benchmark.dropna().empty:
        raise ValueError("benchmark_returns has no usable (non-NaN) data")


def _validate_scores(scores: pd.DataFrame) -> None:
    """Fail closed if *scores* do not look like a research score frame."""
    if list(scores.columns) != ["score"]:
        raise ValueError("score frame must contain exactly one 'score' column")
    if not isinstance(scores.index, pd.MultiIndex):
        raise ValueError("score frame must use a MultiIndex")
    if set(scores.index.names) != {"datetime", "instrument"}:
        raise ValueError(
            "score frame index levels must be named 'datetime' and 'instrument'"
        )
    if scores.empty:
        raise ValueError("score frame must not be empty")
    if scores.index.duplicated().any():
        raise ValueError("score frame index contains duplicate entries")
    if scores.dropna().empty:
        raise ValueError("score frame has no usable (non-NaN) data")


# ── evaluation helpers ──────────────────────────────────────────────────────


def _aligned_common_dates(
    scores: pd.DataFrame, returns: pd.DataFrame, benchmark: pd.DataFrame
) -> tuple[pd.Timestamp, ...]:
    score_dates = set(scores.index.get_level_values("datetime").unique())
    return_dates = set(returns.index.get_level_values("datetime").unique())
    bench_dates = set(benchmark.index)
    common = sorted(score_dates & return_dates & bench_dates)
    if not common:
        raise ValueError("no common dates across scores, returns, and benchmark")
    return tuple(common)


def _evaluate_one_leg(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    *,
    top_n: int,
    rebalance_days: int,
    initial_capital: float,
    cost_bps: float,
    evaluation_dates: tuple[pd.Timestamp, ...],
) -> dict[str, Any]:
    """Run one PortfolioIntent evaluation and return a dict of metrics."""
    signal = SignalFrame(
        scores=scores,
        rebalance_days=rebalance_days,
        provenance={"source": "benchmark_aware_topk"},
    )
    intent = score_to_equal_weight_intent(
        signal,
        top_n=top_n,
        evaluation_dates=evaluation_dates,
    )
    report = evaluate_portfolio_intent(
        intent,
        returns,
        benchmark_returns=benchmark_returns,
        initial_capital=initial_capital,
        cost_bps=cost_bps,
    )

    returns_array = np.asarray(report.period_returns, dtype=float)
    positive_ratio = (
        float((returns_array > 0).mean()) if len(returns_array) > 0 else 0.0
    )

    # Derive benchmark per-period returns from cumulative benchmark values
    bv = list(report.benchmark_values)
    benchmark_period_returns = (
        [bv[i + 1] / bv[i] - 1.0 for i in range(len(bv) - 1)] if len(bv) > 1 else []
    )

    return {
        "total_return": report.total_return,
        "benchmark_return": report.benchmark_return,
        "excess_return": report.excess_return,
        "max_drawdown": report.max_drawdown,
        "sharpe_ratio": report.sharpe_ratio,
        "annual_return": report.annual_return,
        "volatility": report.volatility,
        "turnover": report.turnover,
        "costs": report.costs,
        "information_ratio": report.information_ratio,
        "n_periods": report.n_periods,
        "test_start": report.test_start,
        "test_end": report.test_end,
        "positive_period_ratio": positive_ratio,
        "period_returns": list(report.period_returns),
        "portfolio_values": list(report.portfolio_values),
        "benchmark_values": list(report.benchmark_values),
        "benchmark_period_returns": benchmark_period_returns,
    }


# ── derived diagnostic ──────────────────────────────────────────────────────


def _compute_top_minus_bottom_diagnostic(
    top_period_returns: list[float],
    bottom_period_returns: list[float],
    rebalance_days: int,
) -> dict[str, Any]:
    """Derive the Top-K-minus-Bottom-K spread from aligned net period returns."""
    if len(top_period_returns) != len(bottom_period_returns):
        raise ValueError(
            "top and bottom period returns must have the same length; "
            f"got {len(top_period_returns)} vs {len(bottom_period_returns)}"
        )
    n = len(top_period_returns)
    if n == 0:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "volatility": 0.0,
            "positive_period_ratio": 0.0,
            "n_periods": 0,
        }

    spread = np.asarray(top_period_returns, dtype=float) - np.asarray(
        bottom_period_returns, dtype=float
    )
    if np.any(spread <= -1.0 + 1e-12):
        raise ValueError(
            "Top-minus-Bottom spread contains value(s) <= -1.0, "
            "invalid for compounding"
        )

    # Cumulative return via compounding (NAV includes initial 1.0)
    cumulative = np.cumprod(1.0 + spread)
    nav = np.concatenate([[1.0], cumulative])
    total_return = float(cumulative[-1] - 1.0)

    # Max drawdown on the spread NAV (initial 1.0 included in peak tracking)
    peak = np.maximum.accumulate(nav)
    max_drawdown = float((nav / peak - 1.0).min())

    std = float(spread.std(ddof=0))
    periods_per_year = 252.0 / rebalance_days
    sharpe = (
        float(spread.mean() / std * np.sqrt(periods_per_year))
        if std > 1e-10
        else 0.0
    )

    years = n * rebalance_days / 252.0
    annual_return = (
        float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    )
    volatility = float(std * np.sqrt(periods_per_year)) if n > 0 else 0.0
    positive_ratio = float((spread > 0).mean()) if n > 0 else 0.0

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "volatility": volatility,
        "positive_period_ratio": positive_ratio,
        "n_periods": n,
    }


# ── public API ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BenchmarkAwareTopKResult:
    """Complete benchmark-aware Top-K / Bottom-K / spread evidence for one window.

    Labels distinguish executable-style research from diagnostic-only outputs.
    """

    top_k_long: dict[str, Any]
    bottom_k_long: dict[str, Any]
    top_minus_bottom: dict[str, Any]
    config: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "top_k_long": {
                **self.top_k_long,
                "label": "executable_style_research_portfolio",
                "description": (
                    "Cost-aware Top-K long-only equal-weight portfolio "
                    "evaluated against the benchmark."
                ),
            },
            "bottom_k_long": {
                **self.bottom_k_long,
                "label": "cost_aware_bottom_k_long_only",
                "description": (
                    "Cost-aware Bottom-K long-only equal-weight portfolio "
                    "(ranked by negated score) evaluated against the benchmark."
                ),
            },
            "top_minus_bottom": {
                **self.top_minus_bottom,
                "label": "research_only_diagnostic",
                "description": (
                    "Top-K-minus-Bottom-K spread derived from aligned net period "
                    "returns. NOT trade-ready: does not model borrow availability, "
                    "borrow cost, or short-sale feasibility."
                ),
                "caveats": self.caveats,
            },
        }


def evaluate_benchmark_aware_topk(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    *,
    top_n: int = 3,
    rebalance_days: int = 10,
    initial_capital: float = 10_000.0,
    cost_bps: float = 20.0,
) -> BenchmarkAwareTopKResult:
    """Evaluate one score frame with benchmark-aware Top-K / Bottom-K / spread.

    All three legs (Top-K long, Bottom-K long, Top-minus-Bottom) share the same
    evaluation dates and cost assumptions.  The Top-K-minus-Bottom-K spread is
    diagnostic-only and includes explicit caveats.

    Parameters
    ----------
    scores:
        Research score frame with ``(datetime, instrument)`` MultiIndex and a
        single ``"score"`` column.  Higher scores indicate stronger expected
        forward returns.
    returns:
        Canonical raw forward 10D returns with ``attrs["provenance"] ==
        "raw_forward_return"`` and ``attrs["horizon"] == 10``.
    benchmark_returns:
        Actual benchmark return frame.  Must be non-empty with a single column.
    top_n:
        Number of instruments selected in each leg.
    rebalance_days:
        Rebalance frequency in trading days.
    initial_capital:
        Starting capital for each leg.
    cost_bps:
        One-way transaction cost in basis points.

    Returns
    -------
    BenchmarkAwareTopKResult
        Labelled Top-K, Bottom-K, and Top-minus-Bottom metrics with caveats.
    """
    _validate_scores(scores)
    _validate_raw_10d_returns(returns)
    _validate_benchmark_returns(benchmark_returns)

    dates = _aligned_common_dates(scores, returns, benchmark_returns)

    # ── Top-K long-only (original scores, descending) ────────────────────
    top_k_metrics = _evaluate_one_leg(
        scores,
        returns,
        benchmark_returns,
        top_n=top_n,
        rebalance_days=rebalance_days,
        initial_capital=initial_capital,
        cost_bps=cost_bps,
        evaluation_dates=dates,
    )

    # ── Bottom-K long-only (negated scores → original worst performers) ──
    bottom_scores = scores.copy()
    bottom_scores["score"] = -bottom_scores["score"].astype(float)
    bottom_k_metrics = _evaluate_one_leg(
        bottom_scores,
        returns,
        benchmark_returns,
        top_n=top_n,
        rebalance_days=rebalance_days,
        initial_capital=initial_capital,
        cost_bps=cost_bps,
        evaluation_dates=dates,
    )

    # ── Top-K-minus-Bottom-K diagnostic ──────────────────────────────────
    tmb = _compute_top_minus_bottom_diagnostic(
        top_k_metrics["period_returns"],
        bottom_k_metrics["period_returns"],
        rebalance_days=rebalance_days,
    )

    caveats = [
        "Top-K-minus-Bottom-K is a research-only diagnostic derived from "
        "aligned net period returns of two independent long-only legs.",
        "It does NOT model borrow availability, borrow cost, short-sale "
        "feasibility, or margin requirements.",
        "It is NOT trade-ready and must not be used for live position sizing.",
        "Top-K long-only is the stronger research candidate for any future "
        "executable path.",
    ]

    return BenchmarkAwareTopKResult(
        top_k_long=top_k_metrics,
        bottom_k_long=bottom_k_metrics,
        top_minus_bottom=tmb,
        config={
            "top_n": top_n,
            "rebalance_days": rebalance_days,
            "initial_capital": initial_capital,
            "cost_bps": cost_bps,
            "n_common_dates": len(dates),
        },
        caveats=caveats,
    )
