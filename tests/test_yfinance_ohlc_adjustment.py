"""Regression tests for the governed Yahoo raw-bar adjustment contract.

The governed runtime requests ``auto_adjust=False`` with ``repair=True`` and
applies one explicit uniform ``Adj Close / Close`` ratio to every OHLC field
before the envelope gate runs. These tests pin that contract.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.adapters.yfinance_adapter import _process_yfinance_df


def _raw_frame(*, include_legacy_columns: bool = False) -> pd.DataFrame:
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2026-07-27"), pd.Timestamp("2026-07-28")],
        name="Date",
    )
    data: dict[str, list[float | str]] = {
        "Open": [100.0, 102.0],
        "High": [105.0, 107.0],
        "Low": [99.0, 101.0],
        "Close": [103.0, 105.0],
        "Adj Close": [102.5, 104.4],
        "Volume": [1_000_000, 1_200_000],
    }
    if include_legacy_columns:
        # A hand-built or cached frame may carry a stale synthetic amount
        # column; it must be recomputed from adjusted close and volume.
        data["Amount"] = [1.0, 1.0]
    return pd.DataFrame(data, index=dates)


def test_uniform_adj_close_ratio_scales_every_ohlc_field() -> None:
    result = _process_yfinance_df(_raw_frame())

    assert not result.empty
    ratio = 102.5 / 103.0
    row = result.iloc[0]
    assert row["open"] == pytest.approx(100.0 * ratio)
    assert row["high"] == pytest.approx(105.0 * ratio)
    assert row["low"] == pytest.approx(99.0 * ratio)
    assert row["close"] == pytest.approx(102.5)
    assert row["volume"] == 1_000_000
    assert row["factor"] == 1.0
    evidence = result.attrs["ohlc_rounding_reconciliation"]
    assert evidence["adjustment_method"] == "uniform_adj_close_ratio"


def test_legacy_amount_column_cannot_override_adjusted_close_amount() -> None:
    result = _process_yfinance_df(_raw_frame(include_legacy_columns=True))

    second_ratio = 104.4 / 105.0
    assert result["close"].tolist() == pytest.approx([102.5, 104.4])
    assert result["open"].tolist() == pytest.approx(
        [100.0 * (102.5 / 103.0), 102.0 * second_ratio]
    )
    assert result["amount"].tolist() == pytest.approx(
        [102.5 * 1_000_000, 104.4 * 1_200_000]
    )


def test_missing_adjustment_reference_fails_closed() -> None:
    # An already-adjusted frame without an ``Adj Close`` reference cannot be
    # normalized under the governed raw-bar contract and must not silently
    # pass through as if it were raw provider output.
    frame = _raw_frame().drop(columns=["Adj Close"])

    assert _process_yfinance_df(frame).empty


def test_invalid_required_price_row_is_dropped() -> None:
    frame = _raw_frame()
    frame["Close"] = frame["Close"].astype(object)
    frame.loc[pd.Timestamp("2026-07-27"), "Close"] = "invalid"

    result = _process_yfinance_df(frame)

    assert len(result) == 1
    assert result.iloc[0]["date"] == pd.Timestamp("2026-07-28")


def test_empty_input_returns_empty_frame() -> None:
    assert _process_yfinance_df(pd.DataFrame()).empty
    assert _process_yfinance_df(None).empty


def test_missing_required_column_returns_empty_frame() -> None:
    assert _process_yfinance_df(_raw_frame().drop(columns=["High"])).empty
