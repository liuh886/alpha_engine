from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_open_close_research_adapter import (
    YFinanceOpenCloseResearchAdapter,
)


def test_open_close_adapter_preserves_adjusted_open_close_and_synthesizes_envelope(
    monkeypatch,
):
    index = pd.DatetimeIndex(["2026-07-30", "2026-07-31"], name="Date")
    raw = pd.DataFrame(
        {
            "Open": [100.0, 102.0],
            "High": [99.9, 102.5],
            "Low": [99.0, 103.0],
            "Close": [101.0, 101.5],
            "Volume": [1000.0, 1200.0],
        },
        index=index,
    )
    fake = SimpleNamespace(download=lambda *args, **kwargs: raw)
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    result = YFinanceOpenCloseResearchAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="QQQ",
            market="us",
            start="2026-07-30",
            end="2026-07-31",
        )
    )
    assert result.provider == "yfinance_open_close_research"
    assert result.df["open"].tolist() == pytest.approx([100.0, 102.0])
    assert result.df["close"].tolist() == pytest.approx([101.0, 101.5])
    assert result.df["high"].tolist() == pytest.approx([101.0, 102.0])
    assert result.df["low"].tolist() == pytest.approx([100.0, 101.5])
    assert (result.df["high"] >= result.df[["open", "close"]].max(axis=1)).all()
    assert (result.df["low"] <= result.df[["open", "close"]].min(axis=1)).all()
