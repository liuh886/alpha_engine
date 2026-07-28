"""Regression tests for consistent OHLC adjustment in _process_yfinance_df."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.adapters.yfinance_adapter import _process_yfinance_df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_yahoo_frame(
    *,
    adj_close: list[float] | None = None,
    amount: list[float] | None = None,
) -> pd.DataFrame:
    """Build a minimal pre-processed yfinance DataFrame with a Date index."""
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2026-07-27"), pd.Timestamp("2026-07-28")], name="Date"
    )
    data: dict = {
        "Open": [100.0, 102.0],
        "High": [105.0, 107.0],
        "Low": [99.0, 101.0],
        "Close": [103.0, 105.0],
        "Volume": [1_000_000, 1_200_000],
    }
    if adj_close is not None:
        data["Adj Close"] = adj_close
    if amount is not None:
        data["Amount"] = amount
    return pd.DataFrame(data, index=dates)


def _auto_adjust_frame() -> pd.DataFrame:
    """Simulate yfinance auto_adjust=True output — no Adj Close column."""
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2026-07-27"), pd.Timestamp("2026-07-28")], name="Date"
    )
    return pd.DataFrame(
        {
            "Open": [100.0, 102.0],
            "High": [105.0, 107.0],
            "Low": [99.0, 101.0],
            "Close": [103.0, 105.0],
            "Volume": [1_000_000, 1_200_000],
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# Consistent OHLC adjustment
# ---------------------------------------------------------------------------

def test_ohlc_consistently_adjusted_when_adj_close_present():
    """Open/High/Low/Close are all scaled by the same Adj Close / Close ratio."""
    # Adj Close is 3% above raw Close → ratio = 1.03
    result = _process_yfinance_df(
        _raw_yahoo_frame(adj_close=[103.0 * 1.03, 105.0 * 1.03])
    )

    assert result is not None
    assert not result.empty
    row = result.iloc[0]
    assert row["close"] == pytest.approx(103.0 * 1.03)
    assert row["open"] == pytest.approx(100.0 * 1.03)
    assert row["high"] == pytest.approx(105.0 * 1.03)
    assert row["low"] == pytest.approx(99.0 * 1.03)
    assert row["volume"] == 1_000_000
    # amount is recomputed from adjusted close * volume (no "amount" in input)
    assert row["amount"] == pytest.approx(103.0 * 1.03 * 1_000_000)


def test_existing_amount_scaled_by_ratio_when_adj_close_present():
    """When source already carries an amount column it is scaled by the ratio."""
    result = _process_yfinance_df(
        _raw_yahoo_frame(
            adj_close=[103.0 * 1.03, 105.0 * 1.03],
            amount=[103.0 * 1_000_000, 105.0 * 1_200_000],
        )
    )

    assert not result.empty
    assert result.iloc[0]["amount"] == pytest.approx(103.0 * 1.03 * 1_000_000)
    assert result.iloc[1]["amount"] == pytest.approx(105.0 * 1.03 * 1_200_000)


def test_varying_ratio_per_row():
    """Each row uses its own ratio; a 2:1 split on row 0 leaves row 1 alone."""
    result = _process_yfinance_df(
        _raw_yahoo_frame(adj_close=[103.0 * 0.5, 105.0 * 1.0])
    )

    assert not result.empty
    r0 = result.iloc[0]
    r1 = result.iloc[1]
    assert r0["close"] == pytest.approx(103.0 * 0.5)
    assert r0["open"] == pytest.approx(100.0 * 0.5)
    assert r1["close"] == pytest.approx(105.0)
    assert r1["open"] == pytest.approx(102.0)


# ---------------------------------------------------------------------------
# No double adjustment
# ---------------------------------------------------------------------------

def test_no_double_adjust_when_adj_close_absent():
    """auto_adjust=True shape (no Adj Close) passes through unchanged."""
    result = _process_yfinance_df(_auto_adjust_frame())

    assert not result.empty
    r0 = result.iloc[0]
    assert r0["close"] == 103.0
    assert r0["open"] == 100.0
    assert r0["high"] == 105.0
    assert r0["low"] == 99.0


# ---------------------------------------------------------------------------
# Invalid ratio → fail closed
# ---------------------------------------------------------------------------

def test_zero_close_yields_empty_result():
    """A zero raw Close produces inf ratio → empty DataFrame (fail closed)."""
    bad = _raw_yahoo_frame(adj_close=[103.0, 105.0])
    bad["Close"] = [0.0, 105.0]  # row 0 has zero close
    result = _process_yfinance_df(bad)
    assert result.empty


def test_negative_adj_close_yields_empty_result():
    """A negative Adj Close produces a negative ratio → empty DataFrame."""
    result = _process_yfinance_df(
        _raw_yahoo_frame(adj_close=[-1.0, 105.0])
    )
    assert result.empty


def test_nan_adj_close_yields_empty_result():
    """A NaN Adj Close produces a non-finite ratio → empty DataFrame."""
    result = _process_yfinance_df(
        _raw_yahoo_frame(adj_close=[np.nan, 105.0])
    )
    assert result.empty


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_input():
    assert _process_yfinance_df(pd.DataFrame()).empty
    assert _process_yfinance_df(None).empty


def test_single_row_correctly_adjusted():
    dates = pd.DatetimeIndex([pd.Timestamp("2026-07-27")], name="Date")
    single = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [105.0],
            "Low": [99.0],
            "Close": [103.0],
            "Volume": [1_000_000],
            "Adj Close": [103.0 * 1.05],
        },
        index=dates,
    )
    result = _process_yfinance_df(single)
    assert len(result) == 1
    r0 = result.iloc[0]
    assert r0["close"] == pytest.approx(103.0 * 1.05)
    assert r0["open"] == pytest.approx(100.0 * 1.05)
    assert r0["factor"] == 1.0


def test_nonnumeric_adj_close_yields_empty_result():
    """Non-numeric raw/adjusted prices fail closed rather than leak pandas TypeError."""
    bad = _raw_yahoo_frame(adj_close=[103.0, "invalid"])
    result = _process_yfinance_df(bad)
    assert result.empty
