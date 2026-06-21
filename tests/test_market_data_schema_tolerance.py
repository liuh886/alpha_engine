import pandas as pd

from src.data.validation.schema import validate_market_data


def _bar(*, low: float, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-06-18")],
            "open": [8.0],
            "high": [8.5],
            "low": [low],
            "close": [close],
            "volume": [100.0],
            "amount": [800.0],
        }
    )


def test_ohlc_validation_accepts_floating_point_noise():
    ok, _, errors = validate_market_data(_bar(low=7.846820000000001, close=7.84682), "HIMX")

    assert ok is True
    assert errors == []


def test_ohlc_validation_rejects_materially_invalid_bar():
    ok, _, errors = validate_market_data(_bar(low=8.1, close=7.8), "BAD")

    assert ok is False
    assert any("low_le_close" in error for error in errors)
