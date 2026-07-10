"""Vectorized backtest engine for fast strategy evaluation.

This module provides high-performance backtesting using vectorized NumPy/Pandas
operations instead of Qlib's per-day strategy framework. It's designed for
rapid iteration during model development.

Key optimizations:
- Data loaded once, reused across all calculations
- Vectorized IC computation (no Python loops over stocks)
- Vectorized portfolio return computation
- Pre-computed signal ranks for fast TOP N selection
"""

from __future__ import annotations

import pickle
import time
import tracemalloc
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdapterBacktestConfig:
    """Frozen execution inputs shared by ordinary and vectorized adapters."""

    calendar: tuple[pd.Timestamp, ...]
    topk: int
    rebalance_steps: int
    initial_capital: float
    buy_cost_bps: float
    sell_cost_bps: float

    def __post_init__(self) -> None:
        if not self.calendar:
            raise ValueError("calendar must not be empty")
        if self.topk <= 0:
            raise ValueError("topk must be positive")
        if self.rebalance_steps <= 0:
            raise ValueError("rebalance_steps must be positive")

    @property
    def rebalance_dates(self) -> tuple[pd.Timestamp, ...]:
        return self.calendar[:: self.rebalance_steps]


@dataclass(frozen=True)
class AdapterOrder:
    """Target-weight order emitted by the Qlib-compatible adapter harness."""

    date: pd.Timestamp
    instrument: str
    side: str
    weight_delta: float
    target_weight: float


@dataclass
class AdapterBacktestResult:
    """Golden trace used to compare execution semantics."""

    orders: list[AdapterOrder]
    holdings: list[dict[str, float]]
    nav: list[float]
    metrics: dict[str, float]


@dataclass
class AdapterBenchmarkMeasurement:
    """One measured adapter run with incremental source-fetch count."""

    wall_seconds: float
    peak_memory_bytes: int
    fetch_count: int
    result: AdapterBacktestResult


def _rank_predictions(scores: pd.Series, topk: int) -> list[str] | None:
    available = scores.dropna().rename("score").reset_index()
    if available.empty:
        return None
    instrument_col = "instrument" if "instrument" in available.columns else available.columns[0]
    ranked = available.sort_values(
        ["score", instrument_col],
        ascending=[False, True],
        kind="mergesort",
    )
    return ranked[instrument_col].head(topk).astype(str).tolist()


def _returns_matrix(returns: pd.DataFrame, calendar: Sequence[pd.Timestamp]) -> pd.DataFrame:
    values = returns.iloc[:, 0]
    return values.unstack(level="instrument").reindex(index=pd.DatetimeIndex(calendar))


def _compute_adapter_metrics(
    nav: list[float], daily_returns: list[float], turnover: float, transaction_cost: float
) -> dict[str, float]:
    nav_arr = np.asarray(nav, dtype=float)
    ret_arr = np.asarray(daily_returns, dtype=float)
    total_return = float(nav_arr[-1] / nav_arr[0] - 1.0)
    max_drawdown = float((nav_arr / np.maximum.accumulate(nav_arr) - 1.0).min())
    std = float(ret_arr.std()) if ret_arr.size else 0.0
    years = ret_arr.size / 252.0
    return {
        "total_return": total_return,
        "annual_return": float((1.0 + total_return) ** (1.0 / years) - 1.0)
        if years > 0 and total_return > -1.0
        else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": float(ret_arr.mean() / std * np.sqrt(252.0)) if std > 1e-12 else 0.0,
        "volatility": float(std * np.sqrt(252.0)),
        "turnover": float(turnover),
        "transaction_cost": float(transaction_cost),
    }


def _run_adapter_backtest(
    returns: pd.DataFrame,
    config: AdapterBacktestConfig,
    select: Callable[[pd.Timestamp], list[str] | None],
) -> AdapterBacktestResult:
    return_matrix = _returns_matrix(returns, config.calendar)
    rebalance_dates = set(config.rebalance_dates)
    current_holdings: dict[str, float] = {}
    orders: list[AdapterOrder] = []
    holdings: list[dict[str, float]] = []
    nav = [float(config.initial_capital)]
    daily_returns: list[float] = []
    total_turnover = 0.0
    total_cost = 0.0

    for date in config.calendar:
        cost = 0.0
        if date in rebalance_dates:
            selected = select(date)
            if selected is not None:
                target = {instrument: 1.0 / len(selected) for instrument in selected}
                for instrument in sorted(set(current_holdings) | set(target)):
                    previous_weight = current_holdings.get(instrument, 0.0)
                    target_weight = target.get(instrument, 0.0)
                    delta = target_weight - previous_weight
                    if abs(delta) <= 1e-15:
                        continue
                    side = "buy" if delta > 0 else "sell"
                    weight_delta = abs(delta)
                    orders.append(AdapterOrder(date, instrument, side, weight_delta, target_weight))
                    cost_bps = config.buy_cost_bps if side == "buy" else config.sell_cost_bps
                    cost += weight_delta * cost_bps / 10_000.0
                    total_turnover += weight_delta
                current_holdings = target

        asset_return = 0.0
        if date in return_matrix.index:
            day_returns = return_matrix.loc[date]
            for instrument, weight in current_holdings.items():
                value = day_returns.get(instrument, np.nan)
                if pd.notna(value):
                    asset_return += weight * float(value)
        net_return = asset_return - cost
        total_cost += cost
        daily_returns.append(net_return)
        nav.append(nav[-1] * (1.0 + net_return))
        holdings.append(dict(sorted(current_holdings.items())))

    metrics = _compute_adapter_metrics(nav, daily_returns, total_turnover / 2.0, total_cost)
    return AdapterBacktestResult(orders=orders, holdings=holdings, nav=nav, metrics=metrics)


def run_ordinary_adapter_backtest(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    config: AdapterBacktestConfig,
) -> AdapterBacktestResult:
    """Execute the ordinary per-rebalance prediction lookup path."""

    def select(date: pd.Timestamp) -> list[str] | None:
        try:
            day = predictions.xs(date, level="datetime").iloc[:, 0]
        except KeyError:
            return None
        return _rank_predictions(day, config.topk)

    return _run_adapter_backtest(returns, config, select)


def run_vectorized_adapter_backtest(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    config: AdapterBacktestConfig,
) -> AdapterBacktestResult:
    """Execute the batch materialization path with Qlib-shaped inputs."""
    score_matrix = (
        predictions.iloc[:, 0]
        .unstack(level="instrument")
        .reindex(index=pd.DatetimeIndex(config.calendar))
    )

    def select(date: pd.Timestamp) -> list[str] | None:
        if date not in score_matrix.index:
            return None
        return _rank_predictions(score_matrix.loc[date], config.topk)

    return _run_adapter_backtest(returns, config, select)


class _CountingPredictionSource:
    def __init__(self, predictions: pd.DataFrame):
        self.predictions = predictions
        self.fetch_count = 0

    def fetch(self, dates: Sequence[pd.Timestamp]) -> pd.DataFrame:
        self.fetch_count += 1
        mask = self.predictions.index.get_level_values("datetime").isin(dates)
        return self.predictions.loc[mask].copy()


class _PredictionCache:
    def __init__(self) -> None:
        self._values: dict[tuple[pd.Timestamp, ...], pd.DataFrame] = {}

    def get(self, source: _CountingPredictionSource, dates: Sequence[pd.Timestamp]) -> pd.DataFrame:
        key = tuple(dates)
        if key not in self._values:
            self._values[key] = source.fetch(dates)
        return self._values[key].copy()


def _measure_adapter_run(
    source: _CountingPredictionSource,
    run: Callable[[], AdapterBacktestResult],
) -> AdapterBenchmarkMeasurement:
    before_fetches = source.fetch_count
    tracemalloc.start()
    started = time.perf_counter()
    result = run()
    wall_seconds = time.perf_counter() - started
    _, peak_memory_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return AdapterBenchmarkMeasurement(
        wall_seconds=wall_seconds,
        peak_memory_bytes=peak_memory_bytes,
        fetch_count=source.fetch_count - before_fetches,
        result=result,
    )


def benchmark_adapter_paths(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    config: AdapterBacktestConfig,
) -> dict[str, AdapterBenchmarkMeasurement]:
    """Measure deterministic offline ordinary, vectorized-cold, and warm runs."""
    ordinary_source = _CountingPredictionSource(predictions)

    def run_ordinary() -> AdapterBacktestResult:
        parts = [ordinary_source.fetch((date,)) for date in config.rebalance_dates]
        materialized = pd.concat(parts).sort_index() if parts else predictions.iloc[0:0]
        return run_ordinary_adapter_backtest(materialized, returns, config)

    ordinary = _measure_adapter_run(ordinary_source, run_ordinary)

    vectorized_source = _CountingPredictionSource(predictions)
    cache = _PredictionCache()

    def run_vectorized() -> AdapterBacktestResult:
        materialized = cache.get(vectorized_source, config.calendar)
        return run_vectorized_adapter_backtest(materialized, returns, config)

    vectorized_cold = _measure_adapter_run(vectorized_source, run_vectorized)
    vectorized_warm = _measure_adapter_run(vectorized_source, run_vectorized)
    return {
        "ordinary_cold": ordinary,
        "vectorized_cold": vectorized_cold,
        "vectorized_warm": vectorized_warm,
    }


@dataclass
class BacktestResult:
    """Results from a vectorized backtest."""

    total_return: float
    benchmark_return: float
    excess_return: float
    max_drawdown: float
    sharpe_ratio: float
    annual_return: float
    volatility: float
    mean_ic: float
    ic_ir: float
    positive_ic_ratio: float
    portfolio_values: list[float] = field(default_factory=list)
    benchmark_values: list[float] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    ic_series: list[float] = field(default_factory=list)
    topk: int = 0
    rebalance_days: int = 0
    n_periods: int = 0
    test_start: str = ""
    test_end: str = ""
    turnover: float = 0.0
    costs: float = 0.0
    net_return: float | None = None
    information_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return": round(self.total_return, 4),
            "benchmark_return": round(self.benchmark_return, 4),
            "excess_return": round(self.excess_return, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "annual_return": round(self.annual_return, 4),
            "volatility": round(self.volatility, 4),
            "mean_ic": round(self.mean_ic, 4),
            "ic_ir": round(self.ic_ir, 4),
            "positive_ic_ratio": round(self.positive_ic_ratio, 4),
            "turnover": round(self.turnover, 4),
            "costs": round(self.costs, 6),
            "net_return": round(
                self.total_return if self.net_return is None else self.net_return,
                4,
            ),
            "information_ratio": round(self.information_ratio, 4),
            "topk": self.topk,
            "rebalance_days": self.rebalance_days,
            "n_periods": self.n_periods,
            "test_start": self.test_start,
            "test_end": self.test_end,
        }


def compute_ic_vectorized(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
) -> tuple[float, float, float, list[float]]:
    """Compute IC between predictions and returns using vectorized operations."""
    common_dates = sorted(
        set(predictions.index.get_level_values("datetime"))
        & set(returns.index.get_level_values("datetime"))
    )

    ics = []
    for date in common_dates:
        try:
            pred_day = predictions.loc[date]["score"]
            ret_day = returns.loc[date]
            if isinstance(ret_day, pd.DataFrame):
                ret_day = ret_day.iloc[:, 0]
        except KeyError:
            continue

        common_inst = pred_day.index.intersection(ret_day.index)
        if len(common_inst) < 10:
            continue

        p = pred_day.loc[common_inst].values
        r = ret_day.loc[common_inst].values
        mask = ~(np.isnan(p) | np.isnan(r))
        if mask.sum() < 10:
            continue

        p_clean = p[mask]
        r_clean = r[mask]
        p_std = p_clean.std()
        r_std = r_clean.std()
        if p_std < 1e-10 or r_std < 1e-10:
            continue

        ic = np.corrcoef(p_clean, r_clean)[0, 1]
        if not np.isnan(ic):
            ics.append(ic)

    if not ics:
        return 0.0, 0.0, 0.0, []

    mean_ic = float(np.mean(ics))
    ic_std = float(np.std(ics))
    ic_ir = mean_ic / ic_std if ic_std > 1e-10 else 0.0
    positive_ratio = sum(1 for ic in ics if ic > 0) / len(ics)
    return mean_ic, ic_ir, positive_ratio, ics


def run_vectorized_backtest(
    predictions: pd.DataFrame,
    returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame | None = None,
    topk: int = 15,
    rebalance_days: int = 10,
    initial_capital: float = 10000.0,
    cost_bps: float = 20.0,
    non_overlapping: bool = True,
    require_raw_10d_returns: bool = False,
) -> BacktestResult:
    """Run a TOP-N equal-weight research backtest.

    Canonical ``non_overlapping=True`` evaluation delegates to the explicit
    ``SignalFrame -> PortfolioIntent -> EvaluationReport`` path. The layered
    ``non_overlapping=False`` implementation remains a compatibility surface.
    """
    if non_overlapping:
        from src.research.portfolio_intent import (  # noqa: PLC0415
            run_score_backtest_via_intent,
        )

        return run_score_backtest_via_intent(
            predictions,
            returns,
            benchmark_returns=benchmark_returns,
            top_n=topk,
            rebalance_days=rebalance_days,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            require_raw_10d_returns=require_raw_10d_returns,
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

    pred_dates = sorted(predictions.index.get_level_values("datetime").unique())
    ret_dates = sorted(returns.index.get_level_values("datetime").unique())
    common_dates = sorted(set(pred_dates) & set(ret_dates))
    if not common_dates:
        return BacktestResult(
            total_return=0,
            benchmark_return=0,
            excess_return=0,
            max_drawdown=0,
            sharpe_ratio=0,
            annual_return=0,
            volatility=0,
            mean_ic=0,
            ic_ir=0,
            positive_ic_ratio=0,
        )

    mean_ic, ic_ir, pos_ratio, ic_series = compute_ic_vectorized(predictions, returns)
    bench_series = None
    if benchmark_returns is not None:
        bench_series = benchmark_returns[benchmark_returns.columns[0]]

    ret_map: dict[str, dict[str, float]] = {}
    for date in common_dates:
        try:
            row = returns.loc[date]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[:, 0]
            ret_map[str(date)[:10]] = {
                str(symbol): float(value)
                for symbol, value in row.items()
                if not np.isnan(value)
            }
        except (KeyError, TypeError):
            ret_map[str(date)[:10]] = {}

    layer_capital = initial_capital / rebalance_days
    active_layers: list[tuple[float, dict[str, float], int]] = []
    portfolio_values = [initial_capital]
    benchmark_values = [initial_capital]
    returns_list: list[float] = []

    for day_idx, date in enumerate(common_dates):
        ret_lookup = ret_map.get(str(date)[:10], {})

        matured_cash = 0.0
        surviving: list[tuple[float, dict[str, float], int]] = []
        for layer_value, holdings, maturity_idx in active_layers:
            if day_idx >= maturity_idx:
                matured_cash += layer_value
            else:
                surviving.append((layer_value, holdings, maturity_idx))
        active_layers = surviving

        for index in range(len(active_layers)):
            layer_value, holdings, maturity_idx = active_layers[index]
            valid_weights = {
                symbol: weight
                for symbol, weight in holdings.items()
                if symbol in ret_lookup
            }
            growth = 0.0
            if valid_weights:
                total_weight = sum(valid_weights.values())
                growth = sum(
                    (valid_weights[symbol] / total_weight) * ret_lookup[symbol]
                    for symbol in valid_weights
                )
            active_layers[index] = (
                layer_value * (1 + growth),
                holdings,
                maturity_idx,
            )

        try:
            daily_scores = predictions.loc[date]["score"]
            if len(daily_scores) >= topk:
                selected = daily_scores.nlargest(topk)
                holdings = {str(symbol): 1.0 / topk for symbol in selected.index}
                entry_value = layer_capital * (1 - cost_bps / 10_000)
                active_layers.append((entry_value, holdings, day_idx + rebalance_days))
        except KeyError:
            pass

        total_active = sum(value for value, _, _ in active_layers)
        cash = initial_capital - layer_capital * len(active_layers)
        total_value = matured_cash + cash + total_active
        portfolio_values.append(total_value)

        previous = portfolio_values[-2] if len(portfolio_values) >= 2 else initial_capital
        returns_list.append((total_value / previous) - 1 if previous > 0 else 0.0)

        if bench_series is not None and date in bench_series.index:
            benchmark_value = float(bench_series.loc[date])
            benchmark_values.append(
                benchmark_values[-1]
                * (1 + (0.0 if np.isnan(benchmark_value) else benchmark_value))
            )
        else:
            benchmark_values.append(benchmark_values[-1])

    total_return = portfolio_values[-1] / portfolio_values[0] - 1
    benchmark_return = benchmark_values[-1] / benchmark_values[0] - 1
    excess_return = total_return - benchmark_return
    portfolio_array = np.array(portfolio_values)
    max_drawdown = float(
        (portfolio_array / np.maximum.accumulate(portfolio_array) - 1).min()
    )
    return_array = np.array(returns_list)
    return_std = float(return_array.std())
    periods_per_year = 252 / rebalance_days if rebalance_days > 0 else 252
    sharpe_ratio = (
        float(return_array.mean() / return_std * np.sqrt(periods_per_year))
        if return_std > 1e-10
        else 0.0
    )
    n_periods = len(returns_list)
    years = n_periods * rebalance_days / 252 if rebalance_days > 0 else n_periods / 252
    annual_return = (
        float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0
    )
    volatility = (
        float(return_array.std() * np.sqrt(periods_per_year)) if n_periods > 0 else 0.0
    )

    return BacktestResult(
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        annual_return=annual_return,
        volatility=volatility,
        mean_ic=mean_ic,
        ic_ir=ic_ir,
        positive_ic_ratio=pos_ratio,
        portfolio_values=portfolio_values,
        benchmark_values=benchmark_values,
        daily_returns=returns_list,
        ic_series=ic_series,
        topk=topk,
        rebalance_days=rebalance_days,
        n_periods=n_periods,
        test_start=str(common_dates[0].date()),
        test_end=str(common_dates[-1].date()),
        turnover=0.0,
        costs=0.0,
        net_return=total_return,
        information_ratio=0.0,
    )


def load_predictions(pred_path: str | Path) -> pd.DataFrame:
    """Load predictions from a pickle file."""
    with open(pred_path, "rb") as file:
        return pickle.load(file)


def load_returns(
    symbols: list[str],
    label_expr: str = "Ref($close, -10) / Ref($close, -1) - 1",
    start_time: str = "2025-01-01",
    end_time: str = "2026-06-18",
) -> pd.DataFrame:
    """Load returns using Qlib."""
    from qlib.data import D

    frame = D.features(symbols, [label_expr], start_time=start_time, end_time=end_time)
    frame = frame.unstack(level="instrument")
    frame.columns = [column[1] for column in frame.columns]
    return frame


def load_benchmark(
    symbol: str = "000300",
    label_expr: str = "Ref($close, -10) / Ref($close, -1) - 1",
    start_time: str = "2025-01-01",
    end_time: str = "2026-06-18",
) -> pd.DataFrame:
    """Load benchmark returns using Qlib."""
    from qlib.data import D

    frame = D.features([symbol], [label_expr], start_time=start_time, end_time=end_time)
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.xs(symbol, level="instrument")
    return frame
