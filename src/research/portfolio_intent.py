"""Explicit score-to-portfolio contracts for fixed-10D research.

This module extracts TOP-N equal-weight portfolio construction from the legacy
score-based backtest path.  It deliberately models target weights, not broker
orders.  The legacy API remains available while parity is proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SignalFrame:
    """Dated cross-sectional research scores with stable provenance."""

    scores: pd.DataFrame
    research_contract_id: str = ""
    strategy_id: str = "top_n_equal_weight"
    benchmark: str = ""
    rebalance_days: int = 10
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rebalance_days <= 0:
            raise ValueError("rebalance_days must be positive")
        if list(self.scores.columns) != ["score"]:
            raise ValueError("SignalFrame scores must contain exactly one 'score' column")
        if not isinstance(self.scores.index, pd.MultiIndex):
            raise ValueError("SignalFrame scores must use a MultiIndex")
        if set(self.scores.index.names) != {"datetime", "instrument"}:
            raise ValueError(
                "SignalFrame index levels must be named 'datetime' and 'instrument'"
            )


@dataclass(frozen=True)
class PortfolioIntent:
    """Dated target weights produced from a research signal.

    Missing target rows on a scheduled rebalance date mean "hold the previous
    portfolio", matching the legacy score-based backtest semantics.
    """

    target_weights: pd.DataFrame
    evaluation_dates: tuple[pd.Timestamp, ...]
    rebalance_dates: tuple[pd.Timestamp, ...]
    research_contract_id: str
    strategy_id: str
    benchmark: str
    top_n: int
    rebalance_days: int
    constraints: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.top_n <= 0:
            raise ValueError("top_n must be positive")
        if self.rebalance_days <= 0:
            raise ValueError("rebalance_days must be positive")
        if not self.evaluation_dates:
            raise ValueError("evaluation_dates must not be empty")
        if list(self.target_weights.columns) != ["target_weight"]:
            raise ValueError(
                "PortfolioIntent target_weights must contain one 'target_weight' column"
            )
        if not isinstance(self.target_weights.index, pd.MultiIndex):
            raise ValueError("PortfolioIntent target_weights must use a MultiIndex")
        if set(self.target_weights.index.names) != {"datetime", "instrument"}:
            raise ValueError(
                "PortfolioIntent index levels must be named 'datetime' and 'instrument'"
            )
        if not self.target_weights.empty:
            values = self.target_weights["target_weight"]
            if (values < -1e-15).any():
                raise ValueError("long-only equal-weight intent cannot contain negative weights")
            totals = values.groupby(level="datetime").sum()
            if not np.allclose(totals.to_numpy(dtype=float), 1.0, rtol=0.0, atol=1e-12):
                raise ValueError("target weights must sum to 1 on every populated rebalance date")

    def weights_for(self, date: pd.Timestamp) -> dict[str, float] | None:
        """Return target weights for one date, or ``None`` to hold existing weights."""
        try:
            row = self.target_weights.xs(date, level="datetime")["target_weight"]
        except KeyError:
            return None
        if isinstance(row, pd.Series):
            return {str(symbol): float(weight) for symbol, weight in row.items()}
        return None


@dataclass(frozen=True)
class EvaluationReport:
    """Portfolio economics produced by evaluating one intent."""

    total_return: float
    benchmark_return: float
    excess_return: float
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": self.total_return,
            "benchmark_return": self.benchmark_return,
            "excess_return": self.excess_return,
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
        }


def _empty_target_weights() -> pd.DataFrame:
    index = pd.MultiIndex.from_arrays(
        [pd.DatetimeIndex([]), pd.Index([], dtype=object)],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame({"target_weight": pd.Series(dtype=float)}, index=index)


def score_to_equal_weight_intent(
    signal_frame: SignalFrame,
    *,
    top_n: int,
    evaluation_dates: list[pd.Timestamp] | tuple[pd.Timestamp, ...] | None = None,
) -> PortfolioIntent:
    """Convert scores into deterministic long-only TOP-N target weights."""
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    if evaluation_dates is None:
        dates = tuple(
            sorted(signal_frame.scores.index.get_level_values("datetime").unique())
        )
    else:
        dates = tuple(pd.Timestamp(item) for item in evaluation_dates)
    if not dates:
        raise ValueError("evaluation_dates must not be empty")

    rebalance_dates = dates[:: signal_frame.rebalance_days]
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for date in rebalance_dates:
        try:
            daily_scores = signal_frame.scores.xs(date, level="datetime")["score"]
        except KeyError:
            continue
        if len(daily_scores) < top_n:
            continue
        selected = daily_scores.nlargest(top_n)
        weight = 1.0 / top_n
        rows.extend((date, str(symbol), weight) for symbol in selected.index)

    if rows:
        index = pd.MultiIndex.from_tuples(
            [(date, symbol) for date, symbol, _ in rows],
            names=["datetime", "instrument"],
        )
        target_weights = pd.DataFrame(
            {"target_weight": [weight for _, _, weight in rows]},
            index=index,
        )
    else:
        target_weights = _empty_target_weights()

    return PortfolioIntent(
        target_weights=target_weights,
        evaluation_dates=dates,
        rebalance_dates=rebalance_dates,
        research_contract_id=signal_frame.research_contract_id,
        strategy_id=signal_frame.strategy_id,
        benchmark=signal_frame.benchmark,
        top_n=top_n,
        rebalance_days=signal_frame.rebalance_days,
        constraints={"long_only": True, "fully_invested": True},
        provenance={
            **dict(signal_frame.provenance),
            "construction": "top_n_equal_weight",
        },
    )


def _returns_map(returns: pd.DataFrame) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    dates = sorted(returns.index.get_level_values("datetime").unique())
    for date in dates:
        try:
            row = returns.loc[date]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[:, 0]
            result[str(date)[:10]] = {
                str(symbol): float(value)
                for symbol, value in row.items()
                if not np.isnan(value)
            }
        except (KeyError, TypeError):
            result[str(date)[:10]] = {}
    return result


def evaluate_portfolio_intent(
    intent: PortfolioIntent,
    returns: pd.DataFrame,
    *,
    benchmark_returns: pd.DataFrame | None = None,
    initial_capital: float = 10_000.0,
    cost_bps: float = 20.0,
) -> EvaluationReport:
    """Evaluate non-overlapping target weights using legacy-equivalent economics."""
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    if list(returns.columns) != ["return"]:
        raise ValueError("returns must contain exactly one 'return' column")

    return_lookup = _returns_map(returns)
    benchmark_series = None
    if benchmark_returns is not None:
        benchmark_series = benchmark_returns[benchmark_returns.columns[0]]

    portfolio_values = [float(initial_capital)]
    benchmark_values = [float(initial_capital)]
    period_returns: list[float] = []
    benchmark_period_returns: list[float] = []
    current_holdings: dict[str, float] = {}
    total_turnover = 0.0
    total_cost = 0.0

    for date in intent.rebalance_dates:
        target = intent.weights_for(date)
        period_turnover = 0.0
        cost = 0.0
        if target is not None:
            symbols = set(current_holdings) | set(target)
            period_turnover = (
                sum(
                    abs(target.get(symbol, 0.0) - current_holdings.get(symbol, 0.0))
                    for symbol in symbols
                )
                / 2.0
            )
            cost = period_turnover * cost_bps / 10_000.0
            current_holdings = target

        total_turnover += period_turnover
        total_cost += cost
        daily = return_lookup.get(str(date)[:10], {})
        if current_holdings and daily:
            valid = {
                symbol: weight
                for symbol, weight in current_holdings.items()
                if symbol in daily
            }
            if valid:
                total_weight = sum(valid.values())
                portfolio_return = (
                    sum((valid[symbol] / total_weight) * daily[symbol] for symbol in valid)
                    - cost
                )
            else:
                portfolio_return = 0.0
        else:
            portfolio_return = 0.0

        portfolio_values.append(portfolio_values[-1] * (1.0 + portfolio_return))
        period_returns.append(portfolio_return)

        benchmark_return = 0.0
        if benchmark_series is not None and date in benchmark_series.index:
            raw = float(benchmark_series.loc[date])
            benchmark_return = 0.0 if np.isnan(raw) else raw
        benchmark_values.append(benchmark_values[-1] * (1.0 + benchmark_return))
        benchmark_period_returns.append(benchmark_return)

    total_return = portfolio_values[-1] / portfolio_values[0] - 1.0
    benchmark_return = benchmark_values[-1] / benchmark_values[0] - 1.0
    excess_return = total_return - benchmark_return

    portfolio_array = np.asarray(portfolio_values, dtype=float)
    max_drawdown = float(
        (portfolio_array / np.maximum.accumulate(portfolio_array) - 1.0).min()
    )
    returns_array = np.asarray(period_returns, dtype=float)
    return_std = float(returns_array.std())
    periods_per_year = 252.0 / intent.rebalance_days
    sharpe_ratio = (
        float(returns_array.mean() / return_std * np.sqrt(periods_per_year))
        if return_std > 1e-10
        else 0.0
    )
    n_periods = len(period_returns)
    years = n_periods * intent.rebalance_days / 252.0
    annual_return = (
        float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    )
    volatility = (
        float(returns_array.std() * np.sqrt(periods_per_year))
        if n_periods > 0
        else 0.0
    )

    information_ratio = 0.0
    if benchmark_period_returns and len(benchmark_period_returns) == n_periods:
        excess = returns_array - np.asarray(benchmark_period_returns, dtype=float)
        tracking_error = float(excess.std() * np.sqrt(periods_per_year))
        annual_benchmark = (
            float((1.0 + benchmark_return) ** (1.0 / years) - 1.0)
            if years > 0
            else 0.0
        )
        if tracking_error > 1e-10:
            information_ratio = (annual_return - annual_benchmark) / tracking_error

    return EvaluationReport(
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
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
        test_start=str(intent.evaluation_dates[0].date()),
        test_end=str(intent.evaluation_dates[-1].date()),
    )


def run_score_backtest_via_intent(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame | None = None,
    *,
    top_n: int = 15,
    rebalance_days: int = 10,
    initial_capital: float = 10_000.0,
    cost_bps: float = 20.0,
    require_raw_10d_returns: bool = False,
):
    """Compatibility proof: produce the legacy BacktestResult through intent.

    The import is intentionally local so the new domain module does not create an
    import cycle with ``vectorized_backtest`` during migration.
    """
    from src.research.vectorized_backtest import (  # noqa: PLC0415
        BacktestResult,
        compute_ic_vectorized,
    )

    if require_raw_10d_returns:
        if list(returns.columns) != ["return"]:
            raise ValueError("Economic evaluation requires a single 'return' column")
        if returns.attrs.get("provenance") != "raw_forward_return":
            raise ValueError(
                "Economic evaluation requires provenance='raw_forward_return'; "
                "processed training labels are not valid returns"
            )
        if returns.attrs.get("horizon") != 10:
            raise ValueError("Canonical 10D evaluation requires returns attrs horizon=10")

    prediction_dates = set(predictions.index.get_level_values("datetime").unique())
    return_dates = set(returns.index.get_level_values("datetime").unique())
    common_dates = tuple(sorted(prediction_dates & return_dates))
    if not common_dates:
        return BacktestResult(
            total_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            annual_return=0.0,
            volatility=0.0,
            mean_ic=0.0,
            ic_ir=0.0,
            positive_ic_ratio=0.0,
        )

    signal = SignalFrame(
        scores=predictions,
        rebalance_days=rebalance_days,
        provenance={"source": "legacy_score_backtest"},
    )
    intent = score_to_equal_weight_intent(
        signal,
        top_n=top_n,
        evaluation_dates=common_dates,
    )
    report = evaluate_portfolio_intent(
        intent,
        returns,
        benchmark_returns=benchmark_returns,
        initial_capital=initial_capital,
        cost_bps=cost_bps,
    )
    mean_ic, ic_ir, positive_ic_ratio, ic_series = compute_ic_vectorized(
        predictions,
        returns,
    )
    return BacktestResult(
        total_return=report.total_return,
        benchmark_return=report.benchmark_return,
        excess_return=report.excess_return,
        max_drawdown=report.max_drawdown,
        sharpe_ratio=report.sharpe_ratio,
        annual_return=report.annual_return,
        volatility=report.volatility,
        mean_ic=mean_ic,
        ic_ir=ic_ir,
        positive_ic_ratio=positive_ic_ratio,
        portfolio_values=list(report.portfolio_values),
        benchmark_values=list(report.benchmark_values),
        daily_returns=list(report.period_returns),
        ic_series=ic_series,
        topk=top_n,
        rebalance_days=rebalance_days,
        n_periods=report.n_periods,
        test_start=report.test_start,
        test_end=report.test_end,
        turnover=report.turnover,
        costs=report.costs,
        net_return=report.total_return,
        information_ratio=report.information_ratio,
    )
