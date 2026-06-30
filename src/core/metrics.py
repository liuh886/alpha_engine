"""Performance metrics — pure functions.

All functions are stateless and return plain Python dicts or pd.Series so
they are easy to inspect in notebooks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


def compute_spread(
    long_returns: pd.Series,
    short_returns: pd.Series,
    bench_returns: Optional[pd.Series] = None,
    annualize: int = 252,
) -> dict:
    """Compute spread statistics for a long-short portfolio.

    Parameters
    ----------
    long_returns:   Daily returns of the long leg.
    short_returns:  Daily returns of the short leg.
    bench_returns:  Daily benchmark returns (optional).
    annualize:      Trading days per year for annualisation.

    Returns
    -------
    dict with keys:
      - ``spread_mean``     : mean daily spread
      - ``alpha_long``      : long leg excess return vs benchmark (mean daily)
      - ``alpha_short``     : benchmark excess return vs short leg (mean daily)
      - ``spread_sharpe``   : annualised Sharpe of the spread
      - ``spread_series``   : pd.Series of daily spread values
      - ``spread_equity``   : pd.Series cumulative equity (start=1.0)

    Examples
    --------
    >>> result = compute_spread(
    ...     long_returns=daily_ret[top10].mean(axis=1),
    ...     short_returns=daily_ret[bot10].mean(axis=1),
    ...     bench_returns=daily_ret["QQQ"],
    ... )
    >>> result["spread_series"].plot()
    >>> print(f"Spread Sharpe: {result['spread_sharpe']:.2f}")
    """
    spread = long_returns - short_returns
    
    if bench_returns is not None:
        bench = bench_returns.reindex(long_returns.index).fillna(0.0)
        alpha_long = (long_returns - bench).mean()
        alpha_short = (bench - short_returns).mean()
    else:
        alpha_long = float("nan")
        alpha_short = float("nan")

    spread_std = spread.std()
    spread_sharpe = (
        spread.mean() / spread_std * np.sqrt(annualize)
        if spread_std > 1e-10 else float("nan")
    )

    return {
        "spread_mean":   float(spread.mean()),
        "spread_std":    float(spread_std),
        "spread_sharpe": float(spread_sharpe),
        "alpha_long":    float(alpha_long),
        "alpha_short":   float(alpha_short),
        "spread_series": spread,
        "spread_equity": (1 + spread).cumprod(),
    }


def compute_ic_series(
    score_panel: pd.DataFrame,
    return_panel: pd.DataFrame,
    min_stocks: int = 5,
) -> dict:
    """Compute daily Information Coefficient (Spearman rank IC) series.

    Parameters
    ----------
    score_panel:
        DataFrame with column "score", MultiIndex (datetime, instrument).
    return_panel:
        DataFrame with column "return", same MultiIndex.
    min_stocks:
        Minimum number of valid stocks required to compute IC for a date.

    Returns
    -------
    dict with keys:
      - ``ic_series``   : pd.Series of daily IC values
      - ``ic_mean``     : float, mean IC
      - ``ic_std``      : float, std of IC
      - ``ic_ir``       : float, IC / std (IC Information Ratio)
      - ``ic_pos_pct``  : float, fraction of days with IC > 0
      - ``n_days``      : int, number of valid dates

    Examples
    --------
    >>> ic = compute_ic_series(score_panel, return_panel)
    >>> print(f"IC Mean: {ic['ic_mean']:.4f}  IR: {ic['ic_ir']:.4f}")
    >>> ic["ic_series"].plot(title="Daily IC")
    """
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        if df.index.names[0] != "datetime" and df.index.names[1] == "datetime":
            return df.swaplevel().sort_index()
        return df.sort_index()

    score_panel = _normalise(score_panel)
    return_panel = _normalise(return_panel)

    dates = sorted(score_panel.index.get_level_values(0).unique())
    ic_values: dict = {}

    for date in dates:
        try:
            s = score_panel.xs(date, level=0)["score"]
            r = return_panel.xs(date, level=0)["return"]
        except KeyError:
            continue

        common = s.index.intersection(r.index)
        if len(common) < min_stocks:
            continue

        ic = s.loc[common].corr(r.loc[common], method="spearman")
        if not np.isnan(ic):
            ic_values[date] = ic

    ic_series = pd.Series(ic_values, name="IC")
    ic_std = ic_series.std()

    return {
        "ic_series":  ic_series,
        "ic_mean":    float(ic_series.mean()) if len(ic_series) else float("nan"),
        "ic_std":     float(ic_std),
        "ic_ir":      float(ic_series.mean() / ic_std) if ic_std > 1e-10 else float("nan"),
        "ic_pos_pct": float((ic_series > 0).mean()) if len(ic_series) else float("nan"),
        "n_days":     len(ic_series),
    }
