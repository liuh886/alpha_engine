from __future__ import annotations

import pandas as pd
import pytest

import src.data.adapters.tencent_fqkline_adapter as tencent
from src.data.adapters.base import DataFetchError


def _page(first: str, periods: int) -> pd.DataFrame:
    dates = pd.bdate_range(first, periods=periods)
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 100.0,
            "amount": float("nan"),
            "factor": 1.0,
        }
    )


def test_history_fetch_paginates_and_deduplicates(monkeypatch) -> None:
    newer = _page("2023-06-01", 640)
    older = _page("2021-01-01", 500)
    calls: list[str] = []

    def fake_fetch(provider_symbol: str, start: str, end: str, *, count: int = 10):
        assert provider_symbol == "sh515180"
        assert start == "2021-01-01"
        assert count == 640
        calls.append(end)
        return newer if len(calls) == 1 else older

    monkeypatch.setattr(tencent, "_fetch_rows", fake_fetch)
    result = tencent._fetch_history_rows("sh515180", "2021-01-01", "2026-08-14")

    assert len(calls) == 2
    assert result.iloc[0]["date"] == pd.Timestamp("2021-01-01")
    assert result.iloc[-1]["date"] <= pd.Timestamp("2026-08-14")
    assert result["date"].is_unique
    assert result["amount"].notna().all()


def test_history_fetch_rejects_unverified_partial_history(monkeypatch) -> None:
    partial_history = _page("2024-01-02", 100)

    def fake_fetch(provider_symbol: str, start: str, end: str, *, count: int = 10):
        assert provider_symbol == "sz301001"
        assert start == "2021-01-01"
        assert count == 640
        return partial_history

    monkeypatch.setattr(tencent, "_fetch_rows", fake_fetch)
    with pytest.raises(DataFetchError, match="independently governed start"):
        tencent._fetch_history_rows("sz301001", "2021-01-01", "2026-08-14")
