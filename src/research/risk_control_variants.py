"""Risk-control variants for benchmark-aware Top-K research.

This module intentionally evaluates portfolio-construction variants without
changing the frozen research score.  It is used to test whether drawdown can be
reduced while preserving benchmark-relative excess.

Supported variants:

* ``top5_equal_weight`` — concentration reduction.
* ``top3_inverse_vol20_weight`` — risk-scaled Top-3 using inverse 20D vol.
* ``top3_benchmark_trend_filter`` — Top-3 equal weight with 50% gross exposure
  when the benchmark 20D trend is negative.

The evaluator allows gross exposure below 1.0 so the trend-filter variant can
hold cash.  It remains research-only and does not model borrowing, leverage,
execution slippage beyond the configured turnover cost, or broker constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


VARIANT_TOP5_EQUAL = "top5_equal_weight"
VARIANT_TOP3_INVERSE_VOL20 = "top3_inverse_vol20_weight"
VARIANT_TOP3_BENCHMARK_TREND = "top3_benchmark_trend_filter"
SUPPORTED_VARIANTS = (
    VARIANT_TOP5_EQUAL,
    VARIANT_TOP3_INVERSE_VOL20,
    VARIANT_TOP3_BENCHMARK_TREND,
)


@dataclass(frozen=True)
class RiskVariantSpec:
    """Configuration for one portfolio-construction variant."""

    variant_id: str
    top_n: int
    construction: str
    gross_exposure: float = 1.0
    negative_benchmark_trend_exposure: float | None = None


@dataclass(frozen=True)
class RiskVariantReport:
    """Cost-aware benchmark-relative metrics for one variant/window."""

    variant_id: str
    total_return: float
    benchmark_return: float
    excess_return: float
    relative_excess_return: float
    max_drawdown: float
    sharpe_ratio: float
    annual_return: float
    volatility: float
    turnover: float
    costs: float
    information_ratio: float
    portfolio_values: tuple[float, ...]
    benchmark_values: tuple[float, ...]
    period_returns: tuple[float, ...]
    benchmark_period_returns: tuple[float, ...]
    n_periods: int
    test_start: str
    test_end: str
    mean_gross_exposure: float
    min_gross_exposure: float
    max_gross_exposure: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "label": "research_only_risk_control_variant",
            "research_only": True,
            "trade_ready": False,
            "total_return": self.total_return,
            "benchmark_return": self.benchmark_return,
            "excess_return": self.excess_return,
            "relative_excess_return": self.relative_excess_return,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "annual_return": self.annual_return,
            "volatility": self.volatility,
            "turnover": self.turnover,
            "costs": self.costs,
            "information_ratio": self.information_ratio,
            "portfolio_values": list(self.portfolio_values),
            "benchmark_values": list(self.benchmark_values),
            "period_returns": list(self.period_returns),
            "benchmark_period_returns": list(self.benchmark_period_returns),
            "n_periods": self.n_periods,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "mean_gross_exposure": self.mean_gross_exposure,
            "min_gross_exposure": self.min_gross_exposure,
            "max_gross_exposure": self.max_gross_exposure,
        }


def default_variant_specs() -> tuple[RiskVariantSpec, ...]:
    """Return the fixed, non-tuned variant set approved for baseline_v1."""
    return (
        RiskVariantSpec(
            variant_id=VARIANT_TOP5_EQUAL,
            top_n=5,
            construction="equal_weight",
        ),
        RiskVariantSpec(
            variant_id=VARIANT_TOP3_INVERSE_VOL20,
            top_n=3,
            construction="inverse_vol20_weight",
        ),
        RiskVariantSpec(
            variant_id=VARIANT_TOP3_BENCHMARK_TREND,
            top_n=3,
            construction="equal_weight_with_benchmark_trend_filter",
            negative_benchmark_trend_exposure=0.5,
        ),
    )


def _validate_score_frame(scores: pd.DataFrame) -> None:
    if list(scores.columns) != ["score"]:
        raise ValueError("scores must contain exactly one 'score' column")
    if not isinstance(scores.index, pd.MultiIndex):
        raise ValueError("scores must use a MultiIndex")
    if set(scores.index.names) != {"datetime", "instrument"}:
        raise ValueError("scores index levels must be datetime and instrument")
    if scores.empty or scores.dropna().empty:
        raise ValueError("scores must contain usable non-NaN values")


def _validate_returns_frame(returns: pd.DataFrame) -> None:
    if list(returns.columns) != ["return"]:
        raise ValueError("returns must contain exactly one 'return' column")
    if not isinstance(returns.index, pd.MultiIndex):
        raise ValueError("returns must use a MultiIndex")
    if set(returns.index.names) != {"datetime", "instrument"}:
        raise ValueError("returns index levels must be datetime and instrument")
    if returns.attrs.get("provenance") != "raw_forward_return":
        raise ValueError("returns provenance must be raw_forward_return")
    if returns.attrs.get("horizon") != 10:
        raise ValueError("returns horizon must be 10")
    if returns.empty or returns.dropna().empty:
        raise ValueError("returns must contain usable non-NaN values")


def _validate_benchmark_frame(benchmark_returns: pd.DataFrame) -> None:
    if len(benchmark_returns.columns) != 1:
        raise ValueError("benchmark_returns must contain exactly one column")
    if not isinstance(benchmark_returns.index, pd.DatetimeIndex):
        raise ValueError("benchmark_returns must use a DatetimeIndex")
    if benchmark_returns.attrs.get("provenance") != "raw_forward_return":
        raise ValueError("benchmark provenance must be raw_forward_return")
    if benchmark_returns.attrs.get("horizon") != 10:
        raise ValueError("benchmark horizon must be 10")
    if benchmark_returns.empty or benchmark_returns.dropna().empty:
        raise ValueError("benchmark_returns must contain usable non-NaN values")


def _common_dates(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
) -> tuple[pd.Timestamp, ...]:
    score_dates = set(scores.index.get_level_values("datetime"))
    return_dates = set(returns.index.get_level_values("datetime"))
    benchmark_dates = set(benchmark_returns.index)
    dates = tuple(sorted(score_dates & return_dates & benchmark_dates))
    if not dates:
        raise ValueError("no common dates across scores, returns, benchmark")
    return dates


def _vol_row(
    vol20: pd.DataFrame | None,
    date: pd.Timestamp,
    selected: pd.Index,
) -> pd.Series | None:
    if vol20 is None:
        return None
    if list(vol20.columns) != ["vol20"]:
        raise ValueError("vol20 frame must contain exactly one 'vol20' column")
    try:
        row = vol20.xs(date, level="datetime")["vol20"].reindex(selected)
    except KeyError:
        return None
    row = row.replace([np.inf, -np.inf], np.nan).astype(float)
    row = row.where(row > 1e-12)
    if row.dropna().empty:
        return None
    fill = float(row.dropna().median())
    return row.fillna(fill)


def _gross_exposure_for_date(
    spec: RiskVariantSpec,
    date: pd.Timestamp,
    benchmark_trend: pd.DataFrame | None,
) -> float:
    if spec.negative_benchmark_trend_exposure is None:
        return spec.gross_exposure
    if benchmark_trend is None:
        raise ValueError("benchmark_trend is required for benchmark trend filter")
    if list(benchmark_trend.columns) != ["trend_return_20d"]:
        raise ValueError("benchmark_trend must contain trend_return_20d")
    try:
        value = float(benchmark_trend.loc[date, "trend_return_20d"])
    except KeyError:
        return spec.gross_exposure
    if np.isnan(value):
        return spec.gross_exposure
    if value < 0:
        return float(spec.negative_benchmark_trend_exposure)
    return spec.gross_exposure


def build_variant_target_weights(
    scores: pd.DataFrame,
    *,
    spec: RiskVariantSpec,
    evaluation_dates: tuple[pd.Timestamp, ...],
    rebalance_days: int = 10,
    vol20: pd.DataFrame | None = None,
    benchmark_trend: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construct dated long-only target weights for one risk-control variant."""
    _validate_score_frame(scores)
    if spec.variant_id not in SUPPORTED_VARIANTS:
        raise ValueError(f"unsupported variant: {spec.variant_id}")
    if spec.top_n <= 0:
        raise ValueError("top_n must be positive")
    if rebalance_days <= 0:
        raise ValueError("rebalance_days must be positive")

    rows: list[tuple[pd.Timestamp, str, float]] = []
    for date in evaluation_dates[::rebalance_days]:
        try:
            daily_scores = scores.xs(date, level="datetime")["score"].dropna()
        except KeyError:
            continue
        if len(daily_scores) < spec.top_n:
            continue
        selected = daily_scores.nlargest(spec.top_n).index
        exposure = _gross_exposure_for_date(spec, date, benchmark_trend)
        if exposure < -1e-12 or exposure > 1.0 + 1e-12:
            raise ValueError("gross exposure must be between 0 and 1")

        if spec.construction == "inverse_vol20_weight":
            vol = _vol_row(vol20, date, selected)
            if vol is None:
                weights = pd.Series(1.0 / spec.top_n, index=selected)
            else:
                inv = 1.0 / vol
                weights = inv / inv.sum()
        else:
            weights = pd.Series(1.0 / spec.top_n, index=selected)

        for symbol, weight in weights.items():
            rows.append((date, str(symbol), float(weight) * exposure))

    index = pd.MultiIndex.from_tuples(
        [(date, symbol) for date, symbol, _ in rows],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame({"target_weight": [w for _, _, w in rows]}, index=index)


def _returns_lookup(returns: pd.DataFrame) -> dict[str, dict[str, float]]:
    lookup: dict[str, dict[str, float]] = {}
    for date in sorted(returns.index.get_level_values("datetime").unique()):
        row = returns.loc[date]
        if isinstance(row, pd.DataFrame):
            series = row.iloc[:, 0]
        else:
            series = row
        lookup[str(pd.Timestamp(date).date())] = {
            str(symbol): float(value)
            for symbol, value in series.items()
            if not np.isnan(float(value))
        }
    return lookup


def evaluate_variant_weights(
    target_weights: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    *,
    variant_id: str,
    evaluation_dates: tuple[pd.Timestamp, ...],
    rebalance_days: int = 10,
    initial_capital: float = 10_000.0,
    cost_bps: float = 20.0,
) -> RiskVariantReport:
    """Evaluate target weights while allowing partial gross exposure/cash."""
    _validate_returns_frame(returns)
    _validate_benchmark_frame(benchmark_returns)
    if list(target_weights.columns) != ["target_weight"]:
        raise ValueError("target_weights must contain target_weight")
    if not isinstance(target_weights.index, pd.MultiIndex):
        raise ValueError("target_weights must use a MultiIndex")
    if set(target_weights.index.names) != {"datetime", "instrument"}:
        raise ValueError("target_weights index levels must be datetime/instrument")
    if (target_weights["target_weight"] < -1e-12).any():
        raise ValueError("risk variants are long-only and cannot use negative weights")
    gross = target_weights["target_weight"].groupby(level="datetime").sum()
    if (gross > 1.0 + 1e-12).any():
        raise ValueError("gross exposure cannot exceed 1.0")

    returns_lookup = _returns_lookup(returns)
    benchmark_series = benchmark_returns[benchmark_returns.columns[0]]
    dates = tuple(pd.Timestamp(d) for d in evaluation_dates)
    rebalance_dates = dates[::rebalance_days]

    portfolio_values = [float(initial_capital)]
    benchmark_values = [float(initial_capital)]
    period_returns: list[float] = []
    benchmark_period_returns: list[float] = []
    current_holdings: dict[str, float] = {}
    total_turnover = 0.0
    total_cost = 0.0
    gross_exposures: list[float] = []

    for date in rebalance_dates:
        try:
            row = target_weights.xs(date, level="datetime")["target_weight"]
            target = {str(symbol): float(weight) for symbol, weight in row.items()}
        except KeyError:
            target = current_holdings

        symbols = set(current_holdings) | set(target)
        turnover = sum(
            abs(target.get(symbol, 0.0) - current_holdings.get(symbol, 0.0))
            for symbol in symbols
        ) / 2.0
        cost = turnover * cost_bps / 10_000.0
        total_turnover += turnover
        total_cost += cost
        current_holdings = target
        gross_exposures.append(sum(current_holdings.values()))

        daily = returns_lookup.get(str(date.date()), {})
        portfolio_return = sum(
            weight * daily.get(symbol, 0.0)
            for symbol, weight in current_holdings.items()
        ) - cost
        portfolio_values.append(portfolio_values[-1] * (1.0 + portfolio_return))
        period_returns.append(portfolio_return)

        benchmark_return = 0.0
        if date in benchmark_series.index:
            raw = float(benchmark_series.loc[date])
            benchmark_return = 0.0 if np.isnan(raw) else raw
        benchmark_values.append(benchmark_values[-1] * (1.0 + benchmark_return))
        benchmark_period_returns.append(benchmark_return)

    total_return = portfolio_values[-1] / portfolio_values[0] - 1.0
    benchmark_return = benchmark_values[-1] / benchmark_values[0] - 1.0
    excess_return = total_return - benchmark_return
    relative_excess_return = (1.0 + total_return) / (1.0 + benchmark_return) - 1.0
    portfolio_array = np.asarray(portfolio_values, dtype=float)
    max_drawdown = float(
        (portfolio_array / np.maximum.accumulate(portfolio_array) - 1.0).min()
    )
    returns_array = np.asarray(period_returns, dtype=float)
    periods_per_year = 252.0 / rebalance_days
    std = float(returns_array.std())
    sharpe_ratio = (
        float(returns_array.mean() / std * np.sqrt(periods_per_year))
        if std > 1e-10
        else 0.0
    )
    n_periods = len(period_returns)
    years = n_periods * rebalance_days / 252.0
    annual_return = (
        float((1.0 + total_return) ** (1.0 / years) - 1.0)
        if years > 0 and total_return > -1.0
        else 0.0
    )
    volatility = float(std * np.sqrt(periods_per_year)) if n_periods > 0 else 0.0
    information_ratio = 0.0
    if n_periods > 0:
        benchmark_array = np.asarray(benchmark_period_returns, dtype=float)
        annual_benchmark = (
            float((1.0 + benchmark_return) ** (1.0 / years) - 1.0)
            if years > 0 and benchmark_return > -1.0
            else 0.0
        )
        tracking_error = float((returns_array - benchmark_array).std() * np.sqrt(periods_per_year))
        if tracking_error > 1e-10:
            information_ratio = (annual_return - annual_benchmark) / tracking_error

    return RiskVariantReport(
        variant_id=variant_id,
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        relative_excess_return=relative_excess_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        annual_return=annual_return,
        volatility=volatility,
        turnover=total_turnover,
        costs=total_cost,
        information_ratio=information_ratio,
        portfolio_values=tuple(portfolio_values),
        benchmark_values=tuple(benchmark_values),
        period_returns=tuple(period_returns),
        benchmark_period_returns=tuple(benchmark_period_returns),
        n_periods=n_periods,
        test_start=str(dates[0].date()),
        test_end=str(dates[-1].date()),
        mean_gross_exposure=float(np.mean(gross_exposures)) if gross_exposures else 0.0,
        min_gross_exposure=float(np.min(gross_exposures)) if gross_exposures else 0.0,
        max_gross_exposure=float(np.max(gross_exposures)) if gross_exposures else 0.0,
    )


def evaluate_risk_control_variant(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    *,
    spec: RiskVariantSpec,
    vol20: pd.DataFrame | None = None,
    benchmark_trend: pd.DataFrame | None = None,
    rebalance_days: int = 10,
    initial_capital: float = 10_000.0,
    cost_bps: float = 20.0,
) -> RiskVariantReport:
    """Build and evaluate one approved risk-control variant."""
    _validate_score_frame(scores)
    _validate_returns_frame(returns)
    _validate_benchmark_frame(benchmark_returns)
    evaluation_dates = _common_dates(scores, returns, benchmark_returns)
    weights = build_variant_target_weights(
        scores,
        spec=spec,
        evaluation_dates=evaluation_dates,
        rebalance_days=rebalance_days,
        vol20=vol20,
        benchmark_trend=benchmark_trend,
    )
    return evaluate_variant_weights(
        weights,
        returns,
        benchmark_returns,
        variant_id=spec.variant_id,
        evaluation_dates=evaluation_dates,
        rebalance_days=rebalance_days,
        initial_capital=initial_capital,
        cost_bps=cost_bps,
    )


def aggregate_variant_reports(
    per_window: dict[str, list[RiskVariantReport]],
    *,
    min_positive_excess_windows: int = 3,
    min_relative_excess_return: float = 0.30,
    max_drawdown_gate: float = -0.15,
) -> dict[str, Any]:
    """Aggregate variant reports and apply the conservative candidate_v2 gate."""
    variants: dict[str, Any] = {}
    selected: str | None = None
    selected_relative_excess = -np.inf

    for variant_id, reports in sorted(per_window.items()):
        if not reports:
            continue
        all_period_returns = [r for report in reports for r in report.period_returns]
        all_benchmark_returns = [
            r for report in reports for r in report.benchmark_period_returns
        ]
        compounded_portfolio = float(np.prod(1.0 + np.asarray(all_period_returns)) - 1.0)
        compounded_benchmark = float(
            np.prod(1.0 + np.asarray(all_benchmark_returns)) - 1.0
        )
        compounded_relative_excess = (
            (1.0 + compounded_portfolio) / (1.0 + compounded_benchmark) - 1.0
        )
        positive_excess_windows = sum(report.excess_return > 0 for report in reports)
        worst_drawdown = min(report.max_drawdown for report in reports)
        passes = (
            positive_excess_windows >= min_positive_excess_windows
            and compounded_relative_excess > min_relative_excess_return
            and worst_drawdown >= max_drawdown_gate
        )
        variants[variant_id] = {
            "research_only": True,
            "trade_ready": False,
            "n_windows": len(reports),
            "positive_excess_windows": positive_excess_windows,
            "compounded_portfolio_return": compounded_portfolio,
            "compounded_benchmark_return": compounded_benchmark,
            "compounded_relative_excess_return": compounded_relative_excess,
            "mean_window_sharpe": float(np.mean([r.sharpe_ratio for r in reports])),
            "worst_drawdown": float(worst_drawdown),
            "mean_turnover": float(np.mean([r.turnover for r in reports])),
            "mean_gross_exposure": float(
                np.mean([r.mean_gross_exposure for r in reports])
            ),
            "passes_candidate_v2_gate": passes,
        }
        if passes and compounded_relative_excess > selected_relative_excess:
            selected = variant_id
            selected_relative_excess = compounded_relative_excess

    return {
        "schema_version": "1.0",
        "evidence_type": "risk_control_variants",
        "baseline_id": "us_top3_blend_v1",
        "research_only": True,
        "trade_ready": False,
        "gate": {
            "min_positive_excess_windows": min_positive_excess_windows,
            "min_compounded_relative_excess_return": min_relative_excess_return,
            "max_drawdown_gate": max_drawdown_gate,
        },
        "variants": variants,
        "candidate_v2_selected": selected,
        "candidate_v2_decision": "stronger_research_candidate" if selected else "rejected",
    }
