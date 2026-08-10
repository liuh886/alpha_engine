"""Fixed technical-indicator factors for 10D cross-sectional diagnosis.

The definitions in this module are deliberately small and predeclared.  They
use historical closes only and preserve their economic orientation:

* Bollinger reversion: lower 20-session z-score is better;
* MACD acceleration: higher 12/26/9 normalized histogram is better; and
* RSI strength: a larger share of 10-session absolute return magnitude came
  from positive sessions; and
* close-location pressure: the 10-session mean of the close's location inside
  each same-day high-low range.

These are research scores, not training labels or trading recommendations.
Economic evaluation must still use canonical raw forward 10D returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

MIN_SCALE: Final = 1e-12


@dataclass(frozen=True)
class TechnicalIndicatorSpec:
    """One immutable technical-indicator research contract."""

    name: str
    orientation: str
    parameters: dict[str, int]
    requires_high_low: bool = False


BOLLINGER_REVERSION = TechnicalIndicatorSpec(
    name="factor:technical:bollinger_reversion_z20",
    orientation="lower_price_zscore_is_better",
    parameters={"window": 20},
)
MACD_HISTOGRAM = TechnicalIndicatorSpec(
    name="factor:technical:macd_histogram_12_26_9",
    orientation="higher_normalized_macd_histogram_is_better",
    parameters={"fast_span": 12, "slow_span": 26, "signal_span": 9},
)
RSI_STRENGTH = TechnicalIndicatorSpec(
    name="factor:technical:rsi_strength_10",
    orientation="higher_positive_return_magnitude_share_is_better",
    parameters={"window": 10},
)
CLOSE_LOCATION_PRESSURE = TechnicalIndicatorSpec(
    name="factor:technical:close_location_pressure_10",
    orientation="higher_rolling_close_location_is_better",
    parameters={"window": 10},
    requires_high_low=True,
)
TECHNICAL_INDICATOR_SPECS: Final = (
    BOLLINGER_REVERSION,
    MACD_HISTOGRAM,
    RSI_STRENGTH,
    CLOSE_LOCATION_PRESSURE,
)


def _normalise_close_frame(close: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(close, pd.DataFrame):
        raise TypeError("close must be a DataFrame")
    if list(close.columns) != ["close"]:
        raise ValueError("close must contain exactly one 'close' column")
    if not isinstance(close.index, pd.MultiIndex):
        raise ValueError("close must use a MultiIndex")
    if set(close.index.names) != {"datetime", "instrument"}:
        raise ValueError("close index levels must be named datetime and instrument")
    if close.index.has_duplicates:
        raise ValueError("close index must not contain duplicates")
    if close.empty:
        raise ValueError("close must not be empty")

    frame = close.copy()
    frame.index = frame.index.set_levels(
        pd.to_datetime(frame.index.levels[frame.index.names.index("datetime")]),
        level="datetime",
    )
    frame = frame.reorder_levels(["datetime", "instrument"]).sort_index()
    values = frame["close"].astype(float)
    if np.isinf(values.to_numpy()).any():
        raise ValueError("close must not contain infinite values")
    finite = values.dropna()
    if finite.empty or (finite <= 0.0).any():
        raise ValueError("finite close values must be positive")
    frame["close"] = values
    return frame


def _score_frame(
    wide: pd.DataFrame,
    *,
    spec: TechnicalIndicatorSpec,
) -> pd.DataFrame:
    wide = wide.replace([np.inf, -np.inf], np.nan)
    scores = (
        wide.rename_axis(index="datetime", columns="instrument")
        .stack(future_stack=True)
        .rename("score")
        .to_frame()
        .sort_index()
    )
    scores.attrs.update(
        {
            "provenance": "historical_technical_indicator",
            "candidate": spec.name,
            "orientation": spec.orientation,
            "parameters": dict(spec.parameters),
            "uses_future_returns": False,
            "parameter_search_performed": False,
            "missing_value_policy": "fail_closed_no_fill",
        }
    )
    return scores


def compute_technical_indicator_scores(
    close: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Compute the three fixed historical score frames.

    Missing history remains missing.  No cross-sectional normalization,
    clipping, neutral fill, future return, or orientation search is applied.
    """

    frame = _normalise_close_frame(close)
    wide = frame["close"].unstack(level="instrument")

    boll_window = BOLLINGER_REVERSION.parameters["window"]
    boll_mean = wide.rolling(
        boll_window,
        min_periods=boll_window,
    ).mean()
    boll_std = wide.rolling(
        boll_window,
        min_periods=boll_window,
    ).std(ddof=0)
    # The candidate's declared orientation is mean reversion, hence the minus.
    bollinger = -(wide - boll_mean) / boll_std.where(boll_std > MIN_SCALE)

    fast_span = MACD_HISTOGRAM.parameters["fast_span"]
    slow_span = MACD_HISTOGRAM.parameters["slow_span"]
    signal_span = MACD_HISTOGRAM.parameters["signal_span"]
    fast = wide.ewm(
        span=fast_span,
        adjust=False,
        min_periods=fast_span,
    ).mean()
    slow = wide.ewm(
        span=slow_span,
        adjust=False,
        min_periods=slow_span,
    ).mean()
    macd = fast - slow
    signal = macd.ewm(
        span=signal_span,
        adjust=False,
        min_periods=signal_span,
    ).mean()
    macd_histogram = (macd - signal) / wide

    rsi_window = RSI_STRENGTH.parameters["window"]
    daily_return = wide.pct_change(fill_method=None)
    positive_magnitude = (
        daily_return.clip(lower=0.0)
        .rolling(
            rsi_window,
            min_periods=rsi_window,
        )
        .mean()
    )
    absolute_magnitude = (
        daily_return.abs()
        .rolling(
            rsi_window,
            min_periods=rsi_window,
        )
        .mean()
    )
    rsi_strength = positive_magnitude / absolute_magnitude.where(absolute_magnitude > MIN_SCALE)

    return {
        BOLLINGER_REVERSION.name: _score_frame(
            bollinger,
            spec=BOLLINGER_REVERSION,
        ),
        MACD_HISTOGRAM.name: _score_frame(
            macd_histogram,
            spec=MACD_HISTOGRAM,
        ),
        RSI_STRENGTH.name: _score_frame(
            rsi_strength,
            spec=RSI_STRENGTH,
        ),
    }


def compute_ohlc_technical_indicator_scores(
    bars: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Compute close-only factors plus fixed 10-session close location.

    Close location is ``(2 * close - high - low) / (high - low)``. Its
    10-session mean measures persistent buying or selling pressure without
    using a future bar or selecting a window after evaluation.
    """

    required = {"high", "low", "close"}
    if not isinstance(bars, pd.DataFrame):
        raise TypeError("bars must be a DataFrame")
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"bars are missing columns: {sorted(missing)}")

    close = _normalise_close_frame(bars[["close"]])
    aligned = bars.loc[close.index, ["high", "low"]].copy()
    for column in ("high", "low"):
        aligned[column] = pd.to_numeric(aligned[column], errors="coerce")
    finite = aligned.replace([np.inf, -np.inf], np.nan)
    if finite.isna().any().any():
        raise ValueError("high and low must be finite")
    scale = (
        pd.concat(
            [finite["high"].abs(), finite["low"].abs(), close["close"].abs()],
            axis=1,
        )
        .max(axis=1)
        .clip(lower=1.0)
    )
    tolerance = 1e-12 + scale * 1e-10
    invalid = (
        (finite["high"] + tolerance < finite["low"])
        | (finite["high"] + tolerance < close["close"])
        | (finite["low"] - tolerance > close["close"])
    )
    if invalid.any():
        raise ValueError("bars contain invalid high/low/close relationships")

    high = finite["high"].unstack(level="instrument")
    low = finite["low"].unstack(level="instrument")
    close_wide = close["close"].unstack(level="instrument")
    price_range = high - low
    daily_location = (2.0 * close_wide - high - low) / price_range.where(price_range > MIN_SCALE)
    window = CLOSE_LOCATION_PRESSURE.parameters["window"]
    pressure = daily_location.rolling(
        window,
        min_periods=window,
    ).mean()

    scores = compute_technical_indicator_scores(close)
    scores[CLOSE_LOCATION_PRESSURE.name] = _score_frame(
        pressure,
        spec=CLOSE_LOCATION_PRESSURE,
    )
    return scores
