from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.akshare_sina_adapter import (
    AkShareSinaAdapter,
    _provider_symbol,
)
from src.data.adapters.base import FetchRequest


def test_sina_equity_uses_qfq_and_preserves_share_units(monkeypatch):
    captured: dict[str, object] = {}

    def daily(*, symbol, start_date, end_date, adjust):
        captured.update(
            {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
            }
        )
        return pd.DataFrame(
            {
                "date": ["2026-06-17"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [1200.0],
                "amount": [12600.0],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_a_daily=daily),
    )
    result = AkShareSinaAdapter(min_interval_seconds=0).fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2026-06-17",
            end="2026-06-17",
        )
    )
    assert captured == {
        "symbol": "sz000001",
        "start_date": "20260617",
        "end_date": "20260617",
        "adjust": "qfq",
    }
    assert result.provider_symbol == "sz000001"
    assert result.df.iloc[0]["volume"] == pytest.approx(1200.0)
    assert result.df.iloc[0]["amount"] == pytest.approx(12600.0)
    assert result.df.iloc[0]["factor"] == pytest.approx(1.0)


def test_sina_index_filters_requested_dates(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": ["2026-06-16", "2026-06-17", "2026-06-18"],
            "open": [5000.0, 5010.0, 5020.0],
            "high": [5100.0, 5110.0, 5120.0],
            "low": [4900.0, 4910.0, 4920.0],
            "close": [5050.0, 5060.0, 5070.0],
            "volume": [100.0, 110.0, 120.0],
        }
    )
    captured: dict[str, object] = {}

    def index_daily(*, symbol):
        captured["symbol"] = symbol
        return frame

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_index_daily=index_daily),
    )
    result = AkShareSinaAdapter(min_interval_seconds=0).fetch_daily_bars(
        FetchRequest(
            symbol="000300",
            market="cn",
            start="2026-06-17",
            end="2026-06-18",
        )
    )
    assert captured["symbol"] == "sh000300"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-06-17",
        "2026-06-18",
    ]
    assert result.df["amount"].isna().all()
    assert result.df["factor"].tolist() == pytest.approx([1.0, 1.0])


def test_sina_symbol_mapping_covers_cn_exchanges():
    assert _provider_symbol("000001") == "sz000001"
    assert _provider_symbol("301291") == "sz301291"
    assert _provider_symbol("600009") == "sh600009"
    assert _provider_symbol("688521") == "sh688521"
    assert _provider_symbol("430047") == "bj430047"
    assert _provider_symbol("000300") == "sh000300"
