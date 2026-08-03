"""Point-in-time relative-return targets for fixed-pool ranking research."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.daily_ranker import make_daily_rank_target


def _validate_single_column_frame(
    frame: pd.DataFrame,
    *,
    name: str,
    require_instrument: bool,
) -> pd.Series:
    if not isinstance(frame.index, pd.MultiIndex):
        raise ValueError(f"{name} must use a MultiIndex")
    required = {"datetime"}
    if require_instrument:
        required.add("instrument")
    missing = required - set(frame.index.names)
    if missing:
        raise ValueError(f"{name} index is missing levels: {sorted(missing)}")
    if frame.shape[1] != 1:
        raise ValueError(f"{name} must contain exactly one column")
    values = frame.iloc[:, 0].astype(float).sort_index()
    if values.index.has_duplicates:
        raise ValueError(f"{name} contains duplicate index rows")
    return values


def benchmark_series_by_date(
    benchmark_returns: pd.DataFrame,
    *,
    name: str,
) -> pd.Series:
    """Return one benchmark observation per date from a Qlib-style frame."""

    values = _validate_single_column_frame(
        benchmark_returns,
        name=name,
        require_instrument=False,
    )
    dates = pd.DatetimeIndex(values.index.get_level_values("datetime")).normalize()
    dated = pd.Series(values.to_numpy(dtype=float), index=dates, name=name)
    if dated.index.has_duplicates:
        duplicate_dates = dated.index[dated.index.duplicated()].unique()
        grouped = dated.groupby(level=0, sort=True)
        inconsistent = [
            date
            for date in duplicate_dates
            if grouped.get_group(date).nunique(dropna=False) != 1
        ]
        if inconsistent:
            raise ValueError(
                f"{name} has inconsistent duplicate dates: {inconsistent[:5]}"
            )
        dated = grouped.first()
    return dated.sort_index()


def broadcast_benchmark_to_stock_index(
    stock_frame: pd.DataFrame,
    benchmark_returns: pd.DataFrame,
    *,
    benchmark_name: str,
) -> pd.Series:
    """Broadcast dated benchmark returns to a stock date/instrument index."""

    stock_values = _validate_single_column_frame(
        stock_frame,
        name="stock_frame",
        require_instrument=True,
    )
    benchmark = benchmark_series_by_date(
        benchmark_returns,
        name=benchmark_name,
    )
    dates = pd.DatetimeIndex(
        stock_values.index.get_level_values("datetime")
    ).normalize()
    aligned = benchmark.reindex(dates)
    return pd.Series(
        aligned.to_numpy(dtype=float),
        index=stock_values.index,
        name=benchmark_name,
    )


def make_naive_benchmark_excess_returns(
    stock_forward_returns: pd.DataFrame,
    benchmark_forward_returns: pd.DataFrame,
) -> pd.DataFrame:
    """Subtract the same dated benchmark return from each stock observation."""

    stock = _validate_single_column_frame(
        stock_forward_returns,
        name="stock_forward_returns",
        require_instrument=True,
    )
    benchmark = broadcast_benchmark_to_stock_index(
        stock_forward_returns,
        benchmark_forward_returns,
        benchmark_name="benchmark_forward_return",
    )
    result = (stock - benchmark).to_frame("naive_excess_return")
    result.attrs.update(stock_forward_returns.attrs)
    result.attrs["provenance"] = "naive_benchmark_excess_forward_return"
    return result


def estimate_trailing_market_beta(
    stock_daily_returns: pd.DataFrame,
    benchmark_daily_returns: pd.DataFrame,
    *,
    lookback_sessions: int = 60,
    minimum_observations: int = 40,
) -> pd.DataFrame:
    """Estimate stock-specific trailing beta using only same-or-prior dates.

    Each beta at date ``t`` uses at most ``lookback_sessions`` paired daily
    observations ending at ``t``. Missing and non-finite pairs are excluded.
    """

    if lookback_sessions < 2:
        raise ValueError("lookback_sessions must be at least two")
    if minimum_observations < 2 or minimum_observations > lookback_sessions:
        raise ValueError(
            "minimum_observations must be between two and lookback_sessions"
        )
    stock = _validate_single_column_frame(
        stock_daily_returns,
        name="stock_daily_returns",
        require_instrument=True,
    )
    benchmark = broadcast_benchmark_to_stock_index(
        stock_daily_returns,
        benchmark_daily_returns,
        benchmark_name="benchmark_daily_return",
    )
    paired = pd.DataFrame(
        {
            "stock": stock.replace([np.inf, -np.inf], np.nan),
            "benchmark": benchmark.replace([np.inf, -np.inf], np.nan),
        }
    )
    paired = paired.sort_index()
    rows: list[pd.DataFrame] = []
    for instrument, group in paired.groupby(level="instrument", sort=True):
        dated = group.droplevel("instrument").sort_index()
        valid = dated["stock"].notna() & dated["benchmark"].notna()
        x = dated["benchmark"].where(valid)
        y = dated["stock"].where(valid)
        covariance = y.rolling(
            window=lookback_sessions,
            min_periods=minimum_observations,
        ).cov(x)
        variance = x.rolling(
            window=lookback_sessions,
            min_periods=minimum_observations,
        ).var()
        observations = valid.astype(int).rolling(
            window=lookback_sessions,
            min_periods=1,
        ).sum()
        beta = covariance / variance
        beta = beta.where(np.isfinite(beta) & variance.gt(0.0))
        output = pd.DataFrame(
            {
                "beta": beta,
                "paired_observations": observations.astype(int),
            },
            index=dated.index,
        )
        output["instrument"] = str(instrument)
        output = output.set_index("instrument", append=True)
        output.index = output.index.set_names(["datetime", "instrument"])
        rows.append(output)
    if not rows:
        raise ValueError("no beta rows could be estimated")
    result = pd.concat(rows).sort_index()
    result.attrs.update(
        {
            "provenance": "point_in_time_trailing_market_beta",
            "lookback_sessions": lookback_sessions,
            "minimum_observations": minimum_observations,
        }
    )
    return result


def make_beta_residual_forward_returns(
    stock_forward_returns: pd.DataFrame,
    benchmark_forward_returns: pd.DataFrame,
    beta_ledger: pd.DataFrame,
) -> pd.DataFrame:
    """Build stock forward returns residualized by point-in-time market beta."""

    stock = _validate_single_column_frame(
        stock_forward_returns,
        name="stock_forward_returns",
        require_instrument=True,
    )
    if not isinstance(beta_ledger.index, pd.MultiIndex):
        raise ValueError("beta_ledger must use a MultiIndex")
    if "beta" not in beta_ledger.columns:
        raise ValueError("beta_ledger must contain a beta column")
    beta = beta_ledger["beta"].astype(float).reindex(stock.index)
    benchmark = broadcast_benchmark_to_stock_index(
        stock_forward_returns,
        benchmark_forward_returns,
        benchmark_name="benchmark_forward_return",
    )
    residual = stock - beta * benchmark
    result = residual.to_frame("beta_residual_return")
    result.attrs.update(stock_forward_returns.attrs)
    result.attrs.update(
        {
            "provenance": "beta_residual_forward_return",
            "beta_provenance": beta_ledger.attrs.get("provenance", "unknown"),
            "beta_lookback_sessions": beta_ledger.attrs.get("lookback_sessions"),
            "beta_minimum_observations": beta_ledger.attrs.get(
                "minimum_observations"
            ),
        }
    )
    return result


def prove_naive_rank_invariance(
    stock_forward_returns: pd.DataFrame,
    benchmark_forward_returns: pd.DataFrame,
) -> dict[str, int | bool]:
    """Prove that same-date benchmark subtraction preserves daily ranks."""

    stock_sorted = stock_forward_returns.sort_index()
    naive = make_naive_benchmark_excess_returns(
        stock_sorted,
        benchmark_forward_returns,
    )
    raw_rank = make_daily_rank_target(stock_sorted).sort_index()
    naive_rank = make_daily_rank_target(naive).sort_index()
    valid = raw_rank.notna() & naive_rank.notna()
    if not raw_rank.loc[valid].equals(naive_rank.loc[valid]):
        raise ValueError("naive benchmark subtraction changed same-date ranks")
    return {
        "rank_identity": True,
        "compared_rows": int(valid.sum()),
        "raw_missing_rows": int(raw_rank.isna().sum()),
        "naive_missing_rows": int(naive_rank.isna().sum()),
    }
