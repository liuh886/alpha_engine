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

    # Cumulative returns
    total_return: float
    benchmark_return: float
    excess_return: float

    # Risk metrics
    max_drawdown: float
    sharpe_ratio: float
    annual_return: float
    volatility: float

    # Signal quality
    mean_ic: float
    ic_ir: float
    positive_ic_ratio: float

    # Time series
    portfolio_values: list[float] = field(default_factory=list)
    benchmark_values: list[float] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    ic_series: list[float] = field(default_factory=list)

    # Metadata
    topk: int = 0
    rebalance_days: int = 0
    n_periods: int = 0
    test_start: str = ""
    test_end: str = ""

    # Exposed engine economics (set during run_vectorized_backtest)
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
    """Compute IC between predictions and returns using vectorized operations.

    Parameters
    ----------
    predictions : pd.DataFrame
        Prediction scores, index=(datetime, instrument), columns=['score'].
    returns : pd.DataFrame
        Actual returns, index=(datetime, instrument), columns=['return'].

    Returns
    -------
    tuple[float, float, float, list[float]]
        (mean_ic, ic_ir, positive_ic_ratio, ic_series)
    """
    # Align on common dates and instruments
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

        # Align on common instruments
        common_inst = pred_day.index.intersection(ret_day.index)
        if len(common_inst) < 10:
            continue

        p = pred_day.loc[common_inst].values
        r = ret_day.loc[common_inst].values

        # Remove NaN
        mask = ~(np.isnan(p) | np.isnan(r))
        if mask.sum() < 10:
            continue

        # Vectorized Pearson correlation
        p_clean = p[mask]
        r_clean = r[mask]
        p_clean.mean()
        r_clean.mean()
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
) -> BacktestResult:
    """Run a vectorized backtest using TOP N equal-weight strategy.

    Parameters
    ----------
    predictions : pd.DataFrame
        Prediction scores, index=(datetime, instrument), columns=['score'].
    returns : pd.DataFrame
        Actual returns, index=(datetime, instrument), columns=['return'].
    benchmark_returns : pd.DataFrame, optional
        Benchmark returns, index=(datetime,), columns=['return'].
    topk : int
        Number of top stocks to hold.
    rebalance_days : int
        Rebalance every N days.
    initial_capital : float
        Starting capital.
    cost_bps : float
        Transaction cost in basis points (round-trip).
    non_overlapping : bool
        If True, use non-overlapping returns (rebalance_days intervals).
        This avoids inflated cumulative returns from overlapping periods.

    Returns
    -------
    BacktestResult
        Backtest results with all metrics.
    """
    # Get sorted dates
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

    # Compute IC (always on full set)
    mean_ic, ic_ir, pos_ratio, ic_series = compute_ic_vectorized(predictions, returns)

    # Get benchmark returns as series
    bench_series = None
    if benchmark_returns is not None:
        bench_col = benchmark_returns.columns[0]
        bench_series = benchmark_returns[bench_col]

    # Build a date→return map for O(1) lookup
    ret_map: dict[str, dict[str, float]] = {}
    for d in common_dates:
        try:
            r = returns.loc[d]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[:, 0]
            ret_map[str(d)[:10]] = {str(k): float(v) for k, v in r.items() if not np.isnan(v)}
        except (KeyError, TypeError):
            ret_map[str(d)[:10]] = {}

    # Initialize engine economics accumulators (may be updated in non_overlapping)
    total_turnover = 0.0
    total_cost = 0.0
    bench_per_period: list[float] = []

    if non_overlapping:
        # ── Non-overlapping: independent 10-day windows ──
        rebalance_dates = common_dates[::rebalance_days]
        portfolio_values = [initial_capital]
        benchmark_values = [initial_capital]
        returns_list: list[float] = []
        current_holdings: dict[str, float] = {}

        for date in rebalance_dates:
            try:
                day_pred = predictions.loc[date]["score"]
            except KeyError:
                portfolio_values.append(portfolio_values[-1])
                benchmark_values.append(benchmark_values[-1])
                returns_list.append(0.0)
                bench_per_period.append(0.0)
                continue

            period_turnover = 0.0
            cost = 0.0
            if len(day_pred) >= topk:
                top_stocks = day_pred.nlargest(topk)
                new_holdings = {s: 1.0 / topk for s in top_stocks.index}
                all_symbols = set(current_holdings.keys()) | set(new_holdings.keys())
                period_turnover = (
                    sum(abs(new_holdings.get(s, 0) - current_holdings.get(s, 0)) for s in all_symbols)
                    / 2
                )
                cost = period_turnover * cost_bps / 10000
                current_holdings = new_holdings
            total_turnover += period_turnover
            total_cost += cost

            date_key = str(date)[:10]
            ret_lookup = ret_map.get(date_key, {})
            if current_holdings and ret_lookup:
                valid_weights = {s: w for s, w in current_holdings.items() if s in ret_lookup}
                if valid_weights:
                    total_w = sum(valid_weights.values())
                    port_ret = (
                        sum((valid_weights[s] / total_w) * ret_lookup[s] for s in valid_weights)
                        - cost
                    )
                else:
                    port_ret = 0.0
            else:
                port_ret = 0.0

            portfolio_values.append(portfolio_values[-1] * (1 + port_ret))
            returns_list.append(port_ret)

            if bench_series is not None and date in bench_series.index:
                b = float(bench_series.loc[date])
                benchmark_values.append(benchmark_values[-1] * (1 + (0.0 if np.isnan(b) else b)))
                bench_per_period.append(0.0 if np.isnan(b) else b)
            else:
                benchmark_values.append(benchmark_values[-1])
                bench_per_period.append(0.0)

    else:
        # ── Overlapping (layered): each day opens a 1/N position held N days ──
        # Each layer = 1/rebalance_days of capital, invested for exactly
        # rebalance_days days.  The portfolio holds up to rebalance_days
        # concurrent layers, producing smooth daily curves.
        layer_capital = initial_capital / rebalance_days
        # active_layers: list of [(entry_value, holdings_dict, maturity_idx), ...]
        active_layers: list[tuple[float, dict[str, float], int]] = []
        portfolio_values = [initial_capital]
        benchmark_values = [initial_capital]
        returns_list = []

        for day_idx, date in enumerate(common_dates):
            date_key = str(date)[:10]
            ret_lookup = ret_map.get(date_key, {})

            # 1. Collect matured layers → return to cash
            matured_cash = 0.0
            surviving: list[tuple[float, dict[str, float], int]] = []
            for layer_val, h, mat_idx in active_layers:
                if day_idx >= mat_idx:
                    matured_cash += layer_val
                else:
                    surviving.append((layer_val, h, mat_idx))
            active_layers = surviving

            # 2. Grow all surviving layers by today's return
            for i in range(len(active_layers)):
                lv, h, mi = active_layers[i]
                growth = 0.0
                valid_w = {s: w for s, w in h.items() if s in ret_lookup}
                if valid_w:
                    total_w = sum(valid_w.values())
                    growth = sum(
                        (valid_w[s] / total_w) * ret_lookup[s] for s in valid_w
                    )
                active_layers[i] = (lv * (1 + growth), h, mi)

            # 3. Open new layer (if we have predictions for today)
            try:
                day_pred = predictions.loc[date]["score"]
                if len(day_pred) >= topk:
                    top_stocks = day_pred.nlargest(topk)
                    new_h = {str(k): 1.0 / topk for k in top_stocks.index}
                    # Deduct transaction cost
                    cost_ratio = cost_bps / 10000
                    new_entry = layer_capital * (1 - cost_ratio)
                    active_layers.append((new_entry, new_h, day_idx + rebalance_days))
            except KeyError:
                pass

            # 4. Portfolio value = cash + sum of active layers
            total_active = sum(lv for lv, _, _ in active_layers)
            cash = initial_capital - layer_capital * len(active_layers)  # uninvested remainder
            total_value = matured_cash + cash + total_active
            portfolio_values.append(total_value)

            # Daily return
            prev = portfolio_values[-2] if len(portfolio_values) >= 2 else initial_capital
            daily_ret = (total_value / prev) - 1 if prev > 0 else 0.0
            returns_list.append(daily_ret)

            # Benchmark
            if bench_series is not None and date in bench_series.index:
                b = float(bench_series.loc[date])
                benchmark_values.append(
                    benchmark_values[-1] * (1 + (0.0 if np.isnan(b) else b))
                )
            else:
                benchmark_values.append(benchmark_values[-1])

    # Compute metrics
    total_return = portfolio_values[-1] / portfolio_values[0] - 1
    benchmark_return = benchmark_values[-1] / benchmark_values[0] - 1
    excess_return = total_return - benchmark_return

    # Max drawdown
    port_arr = np.array(portfolio_values)
    max_dd = float((port_arr / np.maximum.accumulate(port_arr) - 1).min())

    # Sharpe ratio (annualized)
    ret_arr = np.array(returns_list)
    ret_std = float(ret_arr.std())
    periods_per_year = 252 / rebalance_days if rebalance_days > 0 else 252
    sharpe = float(ret_arr.mean() / ret_std * np.sqrt(periods_per_year)) if ret_std > 1e-10 else 0.0

    # Annual return
    n_periods = len(returns_list)
    years = n_periods * rebalance_days / 252 if rebalance_days > 0 else n_periods / 252
    annual_ret = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0
    volatility = float(ret_arr.std() * np.sqrt(periods_per_year)) if n_periods > 0 else 0.0

    # Engine economics (costs already subtracted in port_ret → net_return == total_return)
    net_return_val = total_return

    # Information ratio (annualized)
    information_ratio_val = 0.0
    if non_overlapping and bench_per_period and len(bench_per_period) == len(returns_list):
        excess_arr = np.array(returns_list) - np.array(bench_per_period)
        tracking_error = float(excess_arr.std() * np.sqrt(periods_per_year))
        annual_excess = annual_ret - (float((1 + benchmark_return) ** (1 / years) - 1) if years > 0 else 0.0)
        if tracking_error > 1e-10:
            information_ratio_val = annual_excess / tracking_error

    return BacktestResult(
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        annual_return=annual_ret,
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
        turnover=total_turnover,
        costs=total_cost,
        net_return=net_return_val,
        information_ratio=information_ratio_val,
    )


def load_predictions(pred_path: str | Path) -> pd.DataFrame:
    """Load predictions from a pickle file."""
    with open(pred_path, "rb") as f:
        return pickle.load(f)


def load_returns(
    symbols: list[str],
    label_expr: str = "Ref($close, -10) / Ref($close, -1) - 1",
    start_time: str = "2025-01-01",
    end_time: str = "2026-06-18",
) -> pd.DataFrame:
    """Load returns using Qlib."""
    from qlib.data import D

    df = D.features(symbols, [label_expr], start_time=start_time, end_time=end_time)
    df = df.unstack(level="instrument")
    df.columns = [c[1] for c in df.columns]
    return df


def load_benchmark(
    symbol: str = "000300",
    label_expr: str = "Ref($close, -10) / Ref($close, -1) - 1",
    start_time: str = "2025-01-01",
    end_time: str = "2026-06-18",
) -> pd.DataFrame:
    """Load benchmark returns using Qlib.

    Returns DataFrame with datetime index and single column of returns.
    """
    from qlib.data import D

    df = D.features([symbol], [label_expr], start_time=start_time, end_time=end_time)
    # Flatten MultiIndex to just datetime
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="instrument")
    return df
