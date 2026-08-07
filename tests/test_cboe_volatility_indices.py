from __future__ import annotations

import pandas as pd
import pytest

from src.data.adapters.cboe_volatility_indices import parse_cboe_volatility_history


def test_parse_ohlc_history_uses_close() -> None:
    text = "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2026,14,16,13,15.5\n01/05/2026,15,17,14,16.0\n"
    frame = parse_cboe_volatility_history("VIX9D", text)
    assert list(frame.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")]
    assert frame.loc[pd.Timestamp("2026-01-02"), "close"] == pytest.approx(15.5)


def test_parse_single_value_history() -> None:
    text = "DATE,VVIX\n01/02/2026,92.5\n01/05/2026,95.0\n"
    frame = parse_cboe_volatility_history("VVIX", text)
    assert frame.loc[pd.Timestamp("2026-01-05"), "close"] == pytest.approx(95.0)


def test_parse_skew_single_value_history() -> None:
    text = "DATE,SKEW\n01/02/2026,142.5\n01/05/2026,145.0\n"
    frame = parse_cboe_volatility_history("SKEW", text)
    assert frame.loc[pd.Timestamp("2026-01-05"), "close"] == pytest.approx(145.0)


def test_parser_rejects_unsupported_index() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        parse_cboe_volatility_history("VIX6M", "DATE,CLOSE\n01/02/2026,20\n")


def test_parser_rejects_duplicate_dates() -> None:
    text = "DATE,CLOSE\n01/02/2026,15\n01/02/2026,16\n"
    with pytest.raises(ValueError, match="duplicate"):
        parse_cboe_volatility_history("VIX3M", text)
