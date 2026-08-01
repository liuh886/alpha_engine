from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult
from src.data.router import MarketDataRouter


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-18"]),
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
            "amount": [1050.0],
            "factor": [1.0],
        }
    )


@dataclass
class FakeAdapter:
    _name: str
    fail: bool = False
    calls: int = 0

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        self.calls += 1
        if self.fail:
            raise DataFetchError(f"{self.name} unavailable")
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=_frame(),
            provider_symbol=req.symbol,
        )


def test_same_source_family_opens_one_shared_circuit():
    akshare = FakeAdapter("akshare", fail=True)
    efinance = FakeAdapter("efinance", fail=True)
    yahoo = FakeAdapter("yfinance")
    router = MarketDataRouter(
        adapters=[akshare, efinance, yahoo],
        policy={"cn": ["akshare", "efinance", "yfinance"]},
        failure_threshold=2,
    )

    first = router.fetch_daily_bars(
        symbol="000001",
        market="cn",
        start="2026-06-18",
        end="2026-06-18",
    )
    assert first.ok is True
    assert akshare.calls == 1
    assert efinance.calls == 1
    assert router.provider_health_snapshot()["open_source_families"] == ["eastmoney"]

    second = router.fetch_daily_bars(
        symbol="000002",
        market="cn",
        start="2026-06-18",
        end="2026-06-18",
    )
    assert second.ok is True
    assert akshare.calls == 1
    assert efinance.calls == 1
    assert second.attempts[0].circuit_breaker_open is True
    assert second.attempts[1].circuit_breaker_open is True
    assert second.attempts[0].source_family == "eastmoney"


def test_multi_source_independent_mode_deduplicates_upstream_family():
    akshare = FakeAdapter("akshare")
    efinance = FakeAdapter("efinance")
    yahoo = FakeAdapter("yfinance")
    router = MarketDataRouter(
        adapters=[akshare, efinance, yahoo],
        policy={"cn": ["akshare", "efinance", "yfinance"]},
    )
    results = router.fetch_multi_source_bars(
        symbol="000001",
        market="cn",
        start="2026-06-18",
        end="2026-06-18",
        limit=2,
        independent_only=True,
    )
    assert list(results) == ["akshare", "yfinance"]
    assert efinance.calls == 0
