from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.base import FetchRequest
from src.data.adapters.efinance_adapter import EFinanceAdapter


def _eastmoney_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2026-06-17"],
            "开盘": [10.0],
            "最高": [11.0],
            "最低": [9.0],
            "收盘": [10.5],
            "成交量": [12.0],
            "成交额": [1260.0],
        }
    )


def test_akshare_converts_equity_lots_to_shares(monkeypatch):
    fake = SimpleNamespace(
        stock_zh_a_hist=lambda **kwargs: _eastmoney_frame(),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake)
    result = AkShareAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2026-06-17",
            end="2026-06-17",
        )
    )
    assert result.df.iloc[0]["volume"] == 1200.0
    assert result.df.iloc[0]["amount"] == 1260.0


def test_efinance_converts_equity_lots_to_shares(monkeypatch):
    fake = SimpleNamespace(
        stock=SimpleNamespace(
            get_quote_history=lambda *args, **kwargs: _eastmoney_frame()
        )
    )
    monkeypatch.setitem(sys.modules, "efinance", fake)
    result = EFinanceAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2026-06-17",
            end="2026-06-17",
        )
    )
    assert result.df.iloc[0]["volume"] == 1200.0
    assert result.df.iloc[0]["amount"] == 1260.0
