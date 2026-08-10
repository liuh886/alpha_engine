"""Benchmark-residual trend-quality research signal.

The signal is deliberately simple and predeclared:

* use 126 historical market sessions;
* skip the most recent 10 sessions;
* estimate each instrument's beta to the benchmark;
* measure residual mean return divided by residual volatility; and
* keep the economically declared orientation (higher is better).

It is a historical feature only.  It never consumes forward returns and it
does not replace canonical raw 10D returns for economic evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

DEFAULT_LOOKBACK_SESSIONS: Final = 126
DEFAULT_SKIP_RECENT_SESSIONS: Final = 10
MIN_VARIANCE: Final = 1e-12


@dataclass(frozen=True)
class BenchmarkResidualTrendResult:
    """Aligned residual-trend components at each signal date."""

    score: pd.DataFrame
    beta: pd.DataFrame
    residual_mean: pd.DataFrame
    residual_volatility: pd.DataFrame


def _normalise_stock_returns(stock_returns: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(stock_returns, pd.DataFrame):
        raise TypeError("stock_returns must be a DataFrame")
    if not isinstance(stock_returns.index, pd.MultiIndex):
        raise ValueError("stock_returns must use a MultiIndex")
    if set(stock_returns.index.names) != {"datetime", "instrument"}:
        raise ValueError("stock_returns index levels must be named datetime and instrument")
    if stock_returns.shape[1] != 1:
        raise ValueError("stock_returns must contain exactly one return column")
    if stock_returns.index.has_duplicates:
        raise ValueError("stock_returns index must not contain duplicates")

    frame = stock_returns.copy()
    frame.index = frame.index.set_levels(
        pd.to_datetime(frame.index.levels[frame.index.names.index("datetime")]),
        level="datetime",
    )
    frame = frame.reorder_levels(["datetime", "instrument"]).sort_index()
    values = frame.iloc[:, 0].astype(float)
    if np.isinf(values.to_numpy()).any():
        raise ValueError("stock_returns must not contain infinite values")
    frame.iloc[:, 0] = values
    return frame


def _normalise_benchmark_returns(
    benchmark_returns: pd.Series | pd.DataFrame,
) -> pd.Series:
    if isinstance(benchmark_returns, pd.DataFrame):
        if benchmark_returns.shape[1] != 1:
            raise ValueError("benchmark_returns must contain exactly one return column")
        series = benchmark_returns.iloc[:, 0].copy()
    elif isinstance(benchmark_returns, pd.Series):
        series = benchmark_returns.copy()
    else:
        raise TypeError("benchmark_returns must be a Series or DataFrame")

    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("benchmark_returns must use a DatetimeIndex")
    if series.index.has_duplicates:
        raise ValueError("benchmark_returns index must not contain duplicates")
    series.index = pd.to_datetime(series.index)
    series = series.sort_index().astype(float)
    if np.isinf(series.to_numpy()).any():
        raise ValueError("benchmark_returns must not contain infinite values")
    finite = series.dropna()
    if len(finite) < 2 or float(finite.var(ddof=1)) <= MIN_VARIANCE:
        raise ValueError("benchmark_returns must have positive finite variance")
    return series


def _component_frame(
    pieces: list[pd.Series],
    *,
    column: str,
    source_index: pd.MultiIndex,
    attrs: dict[str, object],
) -> pd.DataFrame:
    combined = pd.concat(pieces).rename(column).to_frame()
    combined.index = combined.index.set_names(["datetime", "instrument"])
    combined = combined.reindex(source_index)
    combined.attrs.update(attrs)
    return combined


def compute_benchmark_residual_trend(
    stock_returns: pd.DataFrame,
    benchmark_returns: pd.Series | pd.DataFrame,
    *,
    benchmark: str = "QQQ",
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    skip_recent_sessions: int = DEFAULT_SKIP_RECENT_SESSIONS,
) -> BenchmarkResidualTrendResult:
    """Compute a no-lookahead benchmark-residual trend-quality score.

    Missing observations are never filled.  A score exists only when all
    ``lookback_sessions`` paired stock/benchmark returns are finite after
    shifting by ``skip_recent_sessions`` market sessions.  Flat benchmark or
    residual windows stay missing instead of receiving a neutral score.
    """

    if lookback_sessions < 3:
        raise ValueError("lookback_sessions must be at least three")
    if skip_recent_sessions < 1:
        raise ValueError("skip_recent_sessions must be positive")
    if not benchmark.strip():
        raise ValueError("benchmark must be non-empty")

    stocks = _normalise_stock_returns(stock_returns)
    benchmark_series = _normalise_benchmark_returns(benchmark_returns)
    source_index = stocks.index
    stock_column = stocks.columns[0]

    score_pieces: list[pd.Series] = []
    beta_pieces: list[pd.Series] = []
    mean_pieces: list[pd.Series] = []
    volatility_pieces: list[pd.Series] = []

    for instrument, group in stocks.groupby(level="instrument", sort=True):
        instrument_returns = (
            group.droplevel("instrument")[stock_column]
            .reindex(benchmark_series.index)
            .astype(float)
        )
        lagged_stock = instrument_returns.shift(skip_recent_sessions)
        lagged_benchmark = benchmark_series.shift(skip_recent_sessions)
        rolling_stock = lagged_stock.rolling(
            lookback_sessions,
            min_periods=lookback_sessions,
        )
        rolling_benchmark = lagged_benchmark.rolling(
            lookback_sessions,
            min_periods=lookback_sessions,
        )

        mean_stock = rolling_stock.mean()
        mean_benchmark = rolling_benchmark.mean()
        variance_stock = rolling_stock.var(ddof=1)
        variance_benchmark = rolling_benchmark.var(ddof=1)
        covariance = rolling_stock.cov(lagged_benchmark)

        valid_benchmark_variance = variance_benchmark.where(variance_benchmark > MIN_VARIANCE)
        beta = covariance / valid_benchmark_variance
        residual_mean = mean_stock - beta * mean_benchmark
        residual_variance = (
            variance_stock + beta.pow(2) * variance_benchmark - 2.0 * beta * covariance
        )
        residual_variance = residual_variance.where(residual_variance > MIN_VARIANCE)
        residual_volatility = np.sqrt(residual_variance)
        score = residual_mean / residual_volatility

        original_dates = group.index.get_level_values("datetime")
        instrument_index = pd.MultiIndex.from_arrays(
            [
                original_dates,
                np.repeat(str(instrument), len(original_dates)),
            ],
            names=["datetime", "instrument"],
        )
        for series, pieces in (
            (score, score_pieces),
            (beta, beta_pieces),
            (residual_mean, mean_pieces),
            (residual_volatility, volatility_pieces),
        ):
            selected = series.reindex(original_dates)
            selected.index = instrument_index
            pieces.append(selected)

    attrs: dict[str, object] = {
        "provenance": "historical_benchmark_residual_trend_quality",
        "benchmark": benchmark,
        "lookback_sessions": lookback_sessions,
        "skip_recent_sessions": skip_recent_sessions,
        "orientation": "higher_residual_trend_quality_is_better",
        "uses_future_returns": False,
        "parameter_search_performed": False,
        "missing_value_policy": "fail_closed_no_fill",
    }
    return BenchmarkResidualTrendResult(
        score=_component_frame(
            score_pieces,
            column="score",
            source_index=source_index,
            attrs=attrs,
        ),
        beta=_component_frame(
            beta_pieces,
            column="beta",
            source_index=source_index,
            attrs=attrs,
        ),
        residual_mean=_component_frame(
            mean_pieces,
            column="residual_mean",
            source_index=source_index,
            attrs=attrs,
        ),
        residual_volatility=_component_frame(
            volatility_pieces,
            column="residual_volatility",
            source_index=source_index,
            attrs=attrs,
        ),
    )
