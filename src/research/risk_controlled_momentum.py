"""Risk-controlled momentum helpers for fixed-ten-day research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_volatility_adjusted_momentum(
    momentum: pd.DataFrame,
    volatility: pd.DataFrame,
    *,
    max_volatility_quantile: float = 0.80,
) -> pd.DataFrame:
    """Return a momentum score penalized by same-date volatility.

    Inputs must be indexed by (datetime, instrument). The output has one
    `score` column and can be passed directly to run_10d_experiment.
    """

    if not 0 < max_volatility_quantile <= 1:
        raise ValueError("max_volatility_quantile must be in (0, 1]")

    mom = momentum.iloc[:, 0].astype(float).rename("momentum")
    vol = volatility.iloc[:, 0].astype(float).replace(0.0, np.nan).rename("volatility")
    common = mom.index.intersection(vol.index)
    frame = pd.DataFrame({"momentum": mom.loc[common], "volatility": vol.loc[common]}).dropna()
    if frame.empty:
        result = pd.DataFrame(columns=["score"], index=common)
        result.attrs["provenance"] = "risk_controlled_momentum_score"
        return result

    def _score_day(day: pd.DataFrame) -> pd.Series:
        cutoff = day["volatility"].quantile(max_volatility_quantile)
        kept = day["volatility"] <= cutoff
        score = day["momentum"] / day["volatility"]
        return score.where(kept)

    scores = frame.groupby(level="datetime", group_keys=False).apply(_score_day)
    result = scores.to_frame("score")
    result.attrs["provenance"] = "risk_controlled_momentum_score"
    result.attrs["max_volatility_quantile"] = max_volatility_quantile
    return result
