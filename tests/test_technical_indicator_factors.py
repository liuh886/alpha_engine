"""Contracts for fixed historical technical-indicator factors."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.technical_indicator_factors import (
    BOLLINGER_REVERSION,
    CLOSE_LOCATION_PRESSURE,
    MACD_HISTOGRAM,
    RSI_STRENGTH,
    compute_ohlc_technical_indicator_scores,
    compute_technical_indicator_scores,
)


def _close_frame(*, periods: int = 80) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=periods)
    symbols = ("A", "B", "C")
    index = pd.MultiIndex.from_product(
        [dates, symbols],
        names=["datetime", "instrument"],
    )
    paths = {
        "A": np.linspace(10.0, 20.0, periods),
        "B": np.linspace(20.0, 10.0, periods),
        "C": 15.0 + np.sin(np.arange(periods) / 3.0),
    }
    values = np.concatenate(
        [[paths[symbol][offset] for symbol in symbols] for offset in range(periods)]
    )
    return pd.DataFrame({"close": values}, index=index)


def _ohlc_frame(*, periods: int = 80) -> pd.DataFrame:
    frame = _close_frame(periods=periods)
    symbols = frame.index.get_level_values("instrument")
    high_gap = np.where(symbols == "A", 0.1, 1.0)
    low_gap = np.where(symbols == "B", 0.1, 1.0)
    frame["high"] = frame["close"] + high_gap
    frame["low"] = frame["close"] - low_gap
    return frame[["high", "low", "close"]]


def test_fixed_indicator_contracts_and_orientations() -> None:
    scores = compute_technical_indicator_scores(_close_frame())

    assert set(scores) == {
        BOLLINGER_REVERSION.name,
        MACD_HISTOGRAM.name,
        RSI_STRENGTH.name,
    }
    for name, frame in scores.items():
        assert list(frame.columns) == ["score"]
        assert frame.attrs["candidate"] == name
        assert frame.attrs["provenance"] == "historical_technical_indicator"
        assert frame.attrs["uses_future_returns"] is False
        assert frame.attrs["parameter_search_performed"] is False
        assert frame.attrs["missing_value_policy"] == "fail_closed_no_fill"

    latest = scores[RSI_STRENGTH.name].xs(
        pd.bdate_range("2025-01-02", periods=80)[-1],
        level="datetime",
    )["score"]
    assert latest["A"] == pytest.approx(1.0)
    assert latest["B"] == pytest.approx(0.0)

    macd_latest = scores[MACD_HISTOGRAM.name].xs(
        pd.bdate_range("2025-01-02", periods=80)[-1],
        level="datetime",
    )["score"]
    assert macd_latest["A"] > 0.0
    assert macd_latest["B"] < 0.0


@pytest.mark.parametrize(
    "candidate",
    (BOLLINGER_REVERSION.name, MACD_HISTOGRAM.name, RSI_STRENGTH.name),
)
def test_indicator_scores_do_not_use_future_closes(candidate: str) -> None:
    original = _close_frame()
    cutoff = pd.Timestamp("2025-03-03")
    changed = original.copy()
    future = changed.index.get_level_values("datetime") > cutoff
    changed.loc[future, "close"] *= 100.0

    expected = compute_technical_indicator_scores(original)[candidate]
    actual = compute_technical_indicator_scores(changed)[candidate]
    expected = expected.loc[
        expected.index.get_level_values("datetime") <= cutoff
    ]
    actual = actual.loc[actual.index.get_level_values("datetime") <= cutoff]

    pd.testing.assert_frame_equal(actual, expected)
    assert actual.attrs == expected.attrs


def test_indicator_inputs_fail_closed() -> None:
    close = _close_frame()
    with pytest.raises(ValueError, match="exactly one"):
        compute_technical_indicator_scores(close.rename(columns={"close": "price"}))

    invalid = close.copy()
    invalid.iloc[0, 0] = 0.0
    with pytest.raises(ValueError, match="positive"):
        compute_technical_indicator_scores(invalid)


def test_close_location_pressure_has_fixed_direction_and_no_future_use() -> None:
    original = _ohlc_frame()
    scores = compute_ohlc_technical_indicator_scores(original)
    pressure = scores[CLOSE_LOCATION_PRESSURE.name]
    latest_date = original.index.get_level_values("datetime").max()
    latest = pressure.xs(latest_date, level="datetime")["score"]

    assert latest["A"] > latest["B"]
    assert pressure.attrs["orientation"] == (
        "higher_rolling_close_location_is_better"
    )
    assert pressure.attrs["parameters"] == {"window": 10}
    assert pressure.attrs["uses_future_returns"] is False
    assert pressure.attrs["parameter_search_performed"] is False

    cutoff = pd.Timestamp("2025-03-03")
    changed = original.copy()
    future = changed.index.get_level_values("datetime") > cutoff
    changed.loc[future, "high"] *= 2.0
    changed.loc[future, "low"] *= 0.5
    expected = pressure.loc[
        pressure.index.get_level_values("datetime") <= cutoff
    ]
    actual = compute_ohlc_technical_indicator_scores(changed)[
        CLOSE_LOCATION_PRESSURE.name
    ]
    actual = actual.loc[
        actual.index.get_level_values("datetime") <= cutoff
    ]
    pd.testing.assert_frame_equal(actual, expected)


def test_close_location_pressure_rejects_invalid_ohlc() -> None:
    invalid = _ohlc_frame()
    invalid.iloc[0, invalid.columns.get_loc("high")] = (
        invalid.iloc[0]["close"] - 1.0
    )

    with pytest.raises(ValueError, match="invalid high/low/close"):
        compute_ohlc_technical_indicator_scores(invalid)
