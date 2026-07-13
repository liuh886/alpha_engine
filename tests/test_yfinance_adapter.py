from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter


def _frame(dates: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    return pd.DataFrame(
        {
            "Open": [10.0 + i for i in range(len(index))],
            "High": [11.0 + i for i in range(len(index))],
            "Low": [9.0 + i for i in range(len(index))],
            "Close": [10.5 + i for i in range(len(index))],
            "Volume": [1000 + i for i in range(len(index))],
        },
        index=index,
    )


def test_yfinance_translates_inclusive_end_and_clips_provider_rows(monkeypatch):
    captured: dict[str, object] = {}

    def download(ticker, *, start, end, progress, auto_adjust):
        captured.update(
            {
                "ticker": ticker,
                "start": start,
                "end": end,
                "progress": progress,
                "auto_adjust": auto_adjust,
            }
        )
        # Include one defensive row after the declared boundary. The adapter must
        # never expose it to the router even if a provider over-returns.
        return _frame(["2026-06-17", "2026-06-18", "2026-06-19"])

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))

    result = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2026-06-17",
            end="2026-06-18",
        )
    )

    assert captured == {
        "ticker": "000001.SZ",
        "start": "2026-06-17",
        "end": "2026-06-19",
        "progress": False,
        "auto_adjust": True,
    }
    assert result.end == "2026-06-18"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-06-17",
        "2026-06-18",
    ]


def test_yfinance_current_snapshot_keeps_open_ended_provider_request(monkeypatch):
    captured: dict[str, object] = {}

    def download(ticker, *, start, end, progress, auto_adjust):
        captured["end"] = end
        return _frame(["2026-06-17", "2026-06-18"])

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))

    result = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(symbol="AAPL", market="us", start="2026-06-17")
    )

    assert captured["end"] is None
    assert result.end is None
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-06-17",
        "2026-06-18",
    ]


def test_yfinance_rejects_invalid_or_reversed_boundaries(monkeypatch):
    called = False

    def download(*args, **kwargs):
        nonlocal called
        called = True
        return _frame(["2026-06-18"])

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
    adapter = YFinanceAdapter()

    with pytest.raises(DataFetchError, match="invalid end"):
        adapter.fetch_daily_bars(
            FetchRequest(
                symbol="AAPL",
                market="us",
                start="2026-06-17",
                end="not-a-date",
            )
        )
    assert called is False

    with pytest.raises(DataFetchError, match="end must be on or after start"):
        adapter.fetch_daily_bars(
            FetchRequest(
                symbol="AAPL",
                market="us",
                start="2026-06-19",
                end="2026-06-18",
            )
        )
    assert called is True
