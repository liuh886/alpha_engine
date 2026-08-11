"""Regression tests for the governed Yahoo auto-adjusted OHLC contract."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.adapters.yfinance_adapter import _process_yfinance_df


def _auto_adjusted_frame(*, include_legacy_columns: bool = False) -> pd.DataFrame:
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2026-07-27"), pd.Timestamp("2026-07-28")],
        name="Date",
    )
    data: dict[str, list[float | str]] = {
        "Open": [100.0, 102.0],
        "High": [105.0, 107.0],
        "Low": [99.0, 101.0],
        "Close": [103.0, 105.0],
        "Volume": [1_000_000, 1_200_000],
    }
    if include_legacy_columns:
        # These columns can be present in hand-built or older cached frames.
        # The governed runtime requests auto_adjust=True and must not use them
        # to rescale an already adjusted OHLC set.
        data["Adj Close"] = [51.5, "not-used"]
        data["Amount"] = [1.0, 1.0]
    return pd.DataFrame(data, index=dates)


def test_auto_adjusted_ohlc_passes_through_without_double_adjustment() -> None:
    result = _process_yfinance_df(_auto_adjusted_frame())

    assert not result.empty
    row = result.iloc[0]
    assert row["open"] == 100.0
    assert row["high"] == 105.0
    assert row["low"] == 99.0
    assert row["close"] == 103.0
    assert row["volume"] == 1_000_000
    assert row["factor"] == 1.0


def test_legacy_adj_close_and_amount_cannot_rescale_auto_adjusted_bars() -> None:
    result = _process_yfinance_df(_auto_adjusted_frame(include_legacy_columns=True))

    assert result["close"].tolist() == [103.0, 105.0]
    assert result["open"].tolist() == [100.0, 102.0]
    assert result["amount"].tolist() == pytest.approx(
        [103.0 * 1_000_000, 105.0 * 1_200_000]
    )


def test_invalid_required_price_row_is_dropped() -> None:
    frame = _auto_adjusted_frame()
    frame["Close"] = frame["Close"].astype(object)
    frame.loc[pd.Timestamp("2026-07-27"), "Close"] = "invalid"

    result = _process_yfinance_df(frame)

    assert len(result) == 1
    assert result.iloc[0]["date"] == pd.Timestamp("2026-07-28")


def test_empty_input_returns_empty_frame() -> None:
    assert _process_yfinance_df(pd.DataFrame()).empty
    assert _process_yfinance_df(None).empty


def test_missing_required_column_returns_empty_frame() -> None:
    assert _process_yfinance_df(_auto_adjusted_frame().drop(columns=["High"])).empty
