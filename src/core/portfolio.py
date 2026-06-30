"""Portfolio construction — pure functions.

Builds rolling long (and optionally long-short) portfolios from a panel
of scores.  All functions return plain DataFrames and Series; no I/O.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from .selection import select_topk, select_bottomk


@dataclass
class RollingPortfolioResult:
    """Result container returned by ``build_rolling_portfolio``."""

    # Daily portfolio returns (equal-weight within each leg)
    long_returns: pd.Series
    short_returns: pd.Series        # empty Series if long-only
    spread_returns: pd.Series       # long_returns - short_returns
    bench_returns: pd.Series        # empty Series if benchmark not provided

    # Holdings per rebalance date: {date: [ticker, ...]}
    long_holdings: dict = field(default_factory=dict)
    short_holdings: dict = field(default_factory=dict)

    # Equity curves (cumulative product, starting at 1.0)
    @property
    def long_equity(self) -> pd.Series:
        return (1 + self.long_returns).cumprod()

    @property
    def spread_equity(self) -> pd.Series:
        return (1 + self.spread_returns).cumprod()


def build_rolling_portfolio(
    score_panel: pd.DataFrame,
    return_panel: pd.DataFrame,
    k: int = 10,
    holding_days: int = 10,
    long_only: bool = False,
    guardrail: bool = True,
    prices: Optional[pd.DataFrame] = None,
    ma: Optional[pd.DataFrame] = None,
    benchmark_returns: Optional[pd.Series] = None,
) -> RollingPortfolioResult:
    """Build a rolling rebalanced portfolio from a score panel.

    Rebalances every ``holding_days`` trading days using a new set of top-K
    (and bottom-K for the short leg) tickers.

    Parameters
    ----------
    score_panel:
        DataFrame with columns ["score"] and MultiIndex (datetime, instrument)
        OR (instrument, datetime).  Will be auto-detected.
    return_panel:
        DataFrame with columns ["return"] and same MultiIndex structure as
        ``score_panel``.
    k:
        Number of stocks per leg.
    holding_days:
        Number of trading days between rebalances.
    long_only:
        If True, only construct the long leg.
    guardrail:
        Pass through to ``select_topk``.
    prices:
        Panel of prices, indexed like ``score_panel``.  Used for guardrail.
    ma:
        Panel of moving-average prices.  Used for guardrail.
    benchmark_returns:
        Daily benchmark returns as a Series indexed by date.

    Returns
    -------
    RollingPortfolioResult

    Examples
    --------
    >>> result = build_rolling_portfolio(score_panel, return_panel, k=10, holding_days=10)
    >>> result.spread_equity.plot(title="Long-Short Spread Equity Curve")
    """
    # ── Normalise MultiIndex orientation to (datetime, instrument) ─────────
    def _to_dt_instr(df: pd.DataFrame) -> pd.DataFrame:
        if df.index.names[0] != "datetime" and df.index.names[1] == "datetime":
            return df.swaplevel().sort_index()
        return df.sort_index()

    score_panel = _to_dt_instr(score_panel)
    return_panel = _to_dt_instr(return_panel)

    dates = sorted(score_panel.index.get_level_values(0).unique())
    rebalance_dates = dates[::holding_days]

    long_holdings: dict = {}
    short_holdings: dict = {}
    current_long: list = []
    current_short: list = []

    daily_long_rets: dict = {}
    daily_short_rets: dict = {}

    for date in dates:
        # Rebalance if this is a rebalance date
        if date in rebalance_dates:
            try:
                scores_today = score_panel.xs(date, level=0)["score"]
            except KeyError:
                pass
            else:
                prices_today = (
                    prices.xs(date, level=0).iloc[:, 0]
                    if prices is not None else None
                )
                ma_today = (
                    ma.xs(date, level=0).iloc[:, 0]
                    if ma is not None else None
                )
                current_long = select_topk(
                    scores_today, k,
                    guardrail=guardrail,
                    prices=prices_today,
                    ma=ma_today,
                )
                current_short = [] if long_only else select_bottomk(scores_today, k)
                long_holdings[date] = list(current_long)
                short_holdings[date] = list(current_short)

        # Compute equal-weight returns for the holding day
        try:
            rets_today = return_panel.xs(date, level=0)["return"]
        except KeyError:
            continue

        if current_long:
            valid_long = [t for t in current_long if t in rets_today.index]
            daily_long_rets[date] = rets_today[valid_long].mean() if valid_long else 0.0
        else:
            daily_long_rets[date] = 0.0

        if current_short:
            valid_short = [t for t in current_short if t in rets_today.index]
            daily_short_rets[date] = rets_today[valid_short].mean() if valid_short else 0.0
        else:
            daily_short_rets[date] = 0.0

    long_ret_series = pd.Series(daily_long_rets, name="long")
    short_ret_series = pd.Series(daily_short_rets, name="short")
    spread_series = (long_ret_series - short_ret_series).rename("spread")

    bench_series = (
        benchmark_returns.reindex(long_ret_series.index).fillna(0.0)
        if benchmark_returns is not None
        else pd.Series(dtype=float)
    )

    return RollingPortfolioResult(
        long_returns=long_ret_series,
        short_returns=short_ret_series,
        spread_returns=spread_series,
        bench_returns=bench_series,
        long_holdings=long_holdings,
        short_holdings=short_holdings,
    )
