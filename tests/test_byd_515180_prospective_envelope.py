from __future__ import annotations

import pandas as pd
import pytest

from scripts.run_byd_515180_prospective import (
    MAX_ENVELOPE_REPAIR_PCT,
    PROVIDER_ANCHOR_LOOKBACK_DAYS,
    _audit_and_repair_envelope,
    _provider_request_start,
)
from src.research.byd_515180_prospective import ETF_CUTOFF


def test_provider_request_starts_before_frozen_anchor() -> None:
    requested = pd.Timestamp(_provider_request_start())
    anchor = pd.Timestamp(ETF_CUTOFF)
    assert requested == anchor - pd.Timedelta(
        days=PROVIDER_ANCHOR_LOOKBACK_DAYS
    )
    assert requested < anchor


def test_small_envelope_violation_repairs_only_high_low() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-08-03"),
                "open": 10.0,
                "high": 9.995,
                "low": 9.90,
                "close": 9.95,
                "volume": 1000.0,
                "adj_close": 9.95,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
    )
    repaired, audit = _audit_and_repair_envelope(frame)
    assert len(audit) == 1
    assert audit[0]["within_repair_tolerance"] is True
    assert repaired.iloc[0]["high"] == 10.0
    assert repaired.iloc[0]["low"] == frame.iloc[0]["low"]
    assert repaired.iloc[0]["open"] == frame.iloc[0]["open"]
    assert repaired.iloc[0]["close"] == frame.iloc[0]["close"]
    assert repaired.iloc[0]["volume"] == frame.iloc[0]["volume"]


def test_material_envelope_violation_blocks_run() -> None:
    close = 10.0
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-08-04"),
                "open": close * (1.0 + MAX_ENVELOPE_REPAIR_PCT + 0.001),
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
                "adj_close": close,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
    )
    with pytest.raises(RuntimeError, match="exceed tolerance"):
        _audit_and_repair_envelope(frame)
