"""Tencent qfq history: post-start listings clamp instead of failing over."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.adapters.base import FetchRequest
from src.data.adapters.tencent_fqkline_adapter import TencentQfqHistoryAdapter
from src.data.adapters.base import DataFetchError, HistoryStartUnreachable


def _frame(dates=("2021-06-15", "2021-06-16")) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": list(dates),
            "open": [10.0] * len(dates),
            "high": [11.0] * len(dates),
            "low": [9.0] * len(dates),
            "close": [10.5] * len(dates),
            "volume": [1200.0] * len(dates),
            "amount": [12600.0] * len(dates),
            "factor": [1.0] * len(dates),
        }
    )


def test_listing_boundary_refetches_from_available_start(monkeypatch) -> None:
    import src.data.adapters.tencent_fqkline_adapter as module

    calls: list[str] = []

    def fake_history(provider_symbol: str, start: str, end: str) -> pd.DataFrame:
        calls.append(start)
        if start == "2021-01-01":
            raise HistoryStartUnreachable(
                "no reach",
                provider_symbol=provider_symbol,
                requested_start=start,
                available_start="2021-06-15",
            )
        return _frame()

    monkeypatch.setattr(module, "_fetch_history_rows", fake_history)
    monkeypatch.setattr(module, "_completed_session_guard", lambda *args, **kwargs: None)

    result = TencentQfqHistoryAdapter().fetch_daily_bars(
        FetchRequest(symbol="688183", market="cn", start="2021-01-01", end="2021-06-16")
    )

    assert calls == ["2021-01-01", "2021-06-15"]
    assert result.provider == "tencent_qfq_history"
    assert result.start == "2021-06-15"
    assert len(result.df) == 2


def test_empty_history_stays_fatal(monkeypatch) -> None:
    import src.data.adapters.tencent_fqkline_adapter as module

    def fake_history(provider_symbol: str, start: str, end: str) -> pd.DataFrame:
        raise HistoryStartUnreachable(
            "empty",
            provider_symbol=provider_symbol,
            requested_start=start,
            available_start=None,
        )

    monkeypatch.setattr(module, "_fetch_history_rows", fake_history)
    monkeypatch.setattr(module, "_completed_session_guard", lambda *args, **kwargs: None)

    with pytest.raises(DataFetchError):
        TencentQfqHistoryAdapter().fetch_daily_bars(
            FetchRequest(symbol="XXXXXX", market="cn", start="2021-01-01", end="2021-06-16")
        )
