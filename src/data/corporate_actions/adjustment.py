"""Deterministic adjusted-price reconstruction from raw OHLCV and daily factors."""

from __future__ import annotations

import numpy as np
import pandas as pd

_PRICE_COLUMNS = ("open", "high", "low", "close")


def rebuild_adjusted_ohlcv(
    raw_bars: pd.DataFrame,
    daily_factors: pd.DataFrame,
    *,
    cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    """Rebuild adjusted OHLCV using a factor anchor frozen at ``cutoff``.

    ``daily_factors`` must contain one positive factor for every raw-bar date.
    Prices are multiplied by ``factor / cutoff_factor`` and volume is multiplied
    by the inverse ratio. The input frames are never modified.
    """

    required_bars = {"date", *_PRICE_COLUMNS, "volume"}
    missing_bars = sorted(required_bars - set(raw_bars.columns))
    if missing_bars:
        raise ValueError(f"raw bars missing columns: {missing_bars}")
    if not {"date", "factor"} <= set(daily_factors.columns):
        raise ValueError("daily factors require date and factor columns")

    bars = raw_bars.copy(deep=True)
    factors = daily_factors.loc[:, ["date", "factor"]].copy(deep=True)
    bars["date"] = pd.to_datetime(bars["date"], errors="raise").dt.normalize()
    factors["date"] = pd.to_datetime(
        factors["date"],
        errors="raise",
    ).dt.normalize()
    if bars["date"].duplicated().any():
        raise ValueError("raw bars contain duplicate dates")
    if factors["date"].duplicated().any():
        raise ValueError("daily factors contain duplicate dates")

    factors["factor"] = pd.to_numeric(factors["factor"], errors="raise")
    finite_positive = np.isfinite(factors["factor"]) & (factors["factor"] > 0)
    if not finite_positive.all():
        raise ValueError("adjustment factors must be finite and positive")

    cutoff_date = pd.Timestamp(cutoff).normalize()
    cutoff_rows = factors.loc[factors["date"] == cutoff_date, "factor"]
    if len(cutoff_rows) != 1:
        raise ValueError("declared cutoff must have exactly one adjustment factor")
    cutoff_factor = float(cutoff_rows.iloc[0])

    merged = bars.merge(
        factors,
        on="date",
        how="left",
        validate="one_to_one",
    )
    if merged["factor"].isna().any():
        missing = merged.loc[merged["factor"].isna(), "date"].dt.strftime("%Y-%m-%d")
        raise ValueError(
            "missing adjustment factor for raw-bar dates: " + ", ".join(missing.tolist()[:10])
        )

    ratio = merged["factor"].astype(float) / cutoff_factor
    for column in _PRICE_COLUMNS:
        values = pd.to_numeric(merged[column], errors="raise")
        merged[column] = values * ratio
    volume = pd.to_numeric(merged["volume"], errors="raise")
    merged["volume"] = volume / ratio
    merged["adjustment_anchor_date"] = cutoff_date
    merged["adjustment_anchor_factor"] = cutoff_factor
    merged["price_role"] = "adjusted_feature_and_label"

    if not (
        (merged["low"] <= merged["open"])
        & (merged["low"] <= merged["close"])
        & (merged["high"] >= merged["open"])
        & (merged["high"] >= merged["close"])
    ).all():
        raise ValueError("rebuilt adjusted OHLC relationships are invalid")
    return merged.sort_values("date").reset_index(drop=True)
