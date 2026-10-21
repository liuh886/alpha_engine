from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from src.data.adapters.baostock_adapter import _to_baostock_code
from src.data.adapters.base import FetchRequest, FetchResult
from src.data.adapters.yfinance_adapter import _get_yahoo_ticker
from src.data.router import MarketDataRouter


def _bars(*, valid: bool) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-01-04", "2021-01-05"]),
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [1_000.0, 1_100.0],
            "amount": [100_500.0, 111_650.0],
            "factor": [1.0, 1.0],
        }
    )
    if not valid:
        frame.loc[0, "high"] = 98.0
    return frame


@dataclass
class FakeAdapter:
    _name: str
    resolved_symbol: str
    valid: bool

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return self.resolved_symbol

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=_bars(valid=self.valid),
            provider_symbol=self.resolved_symbol,
        )


def test_csi300_provider_ticker_mappings_are_explicit() -> None:
    assert _get_yahoo_ticker("000300", "cn") == "000300.SS"
    assert _to_baostock_code("000300") == "sh.000300"


def test_router_records_failed_schema_and_selected_benchmark_source() -> None:
    router = MarketDataRouter(
        adapters=[
            FakeAdapter("stock_api", "stock_api:000300", valid=False),
            FakeAdapter("yfinance", "000300.SS", valid=True),
        ],
        policy={"cn": ["stock_api", "yfinance"]},
    )

    response = router.fetch_daily_bars(
        symbol="000300",
        market="cn",
        start="2021-01-01",
        validate=True,
    )

    assert response.ok is True
    assert response.result is not None
    assert response.result.provider == "yfinance"
    assert response.result.provider_symbol == "000300.SS"
    assert len(response.attempts) == 2

    rejected = response.attempts[0].to_dict()
    assert rejected["provider"] == "stock_api"
    assert rejected["provider_symbol"] == "stock_api:000300"
    assert rejected["ok"] is False
    assert rejected["rows"] == 2
    assert rejected["first_date"] == "2021-01-04"
    assert rejected["last_date"] == "2021-01-05"
    assert rejected["error"] == "schema validation failed"
    assert rejected["schema_errors"]
    assert rejected["source_family"] == "stock_api"
    assert rejected["independent_group"] == "stock_api"
    assert rejected["circuit_breaker_open"] is False

    selected = response.attempts[1].to_dict()
    assert selected == {
        "provider": "yfinance",
        "ok": True,
        "provider_symbol": "000300.SS",
        "rows": 2,
        "first_date": "2021-01-04",
        "last_date": "2021-01-05",
        "error": None,
        "schema_errors": [],
        "source_family": "yahoo_finance",
        "independent_group": "yahoo_finance",
        "circuit_breaker_open": False,
    }


def test_symbol_policy_overrides_market_default_without_affecting_other_symbols() -> None:
    router = MarketDataRouter(
        adapters=[
            FakeAdapter("yfinance", "000300.SS", valid=True),
            FakeAdapter("akshare", "sh000300", valid=True),
        ],
        policy={
            "cn": ["yfinance", "akshare"],
            "cn:000300": ["akshare", "yfinance"],
        },
    )

    benchmark = router.fetch_daily_bars(
        symbol="000300",
        market="CN",
        start="2021-01-01",
        validate=True,
    )
    stock = router.fetch_daily_bars(
        symbol="600519",
        market="cn",
        start="2021-01-01",
        validate=True,
    )

    assert router.providers_for_request("CN", "000300") == ["akshare", "yfinance"]
    assert benchmark.result is not None
    assert benchmark.result.provider == "akshare"
    assert benchmark.attempts[0].provider == "akshare"

    assert router.providers_for_request("cn", "600519") == ["yfinance", "akshare"]
    assert stock.result is not None
    assert stock.result.provider == "yfinance"
    assert stock.attempts[0].provider == "yfinance"


def test_multi_source_consistency_uses_symbol_override_order() -> None:
    router = MarketDataRouter(
        adapters=[
            FakeAdapter("yfinance", "000300.SS", valid=True),
            FakeAdapter("akshare", "sh000300", valid=True),
        ],
        policy={
            "cn": ["yfinance", "akshare"],
            "cn:000300": ["akshare", "yfinance"],
        },
    )

    results = router.fetch_multi_source_bars(
        symbol="000300",
        market="cn",
        start="2021-01-01",
        limit=2,
    )

    assert list(results) == ["akshare", "yfinance"]


@dataclass
class DatedAdapter:
    name: str
    dates: tuple[str, ...]
    calls: int = 0

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        self.calls += 1
        frame = _bars(valid=True).iloc[:len(self.dates)].copy()
        frame["date"] = pd.to_datetime(self.dates)
        return FetchResult(self.name, req.symbol, req.market, req.start, req.end, frame, req.symbol)


def test_end_preference_falls_back_to_one_current_source_without_merging() -> None:
    stale = DatedAdapter("tencent_qfq_history", ("2026-10-20",))
    current = DatedAdapter("akshare_sina", ("2026-10-21",))
    unused = DatedAdapter("akshare", ("2026-10-21",))
    router = MarketDataRouter(adapters=[stale, current, unused], policy={"cn": [stale.name, current.name, unused.name]})

    legacy = router.fetch_daily_bars(symbol="300017", market="cn", start="2026-10-20", end="2026-10-21", validate=True)
    assert legacy.result is not None and legacy.result.provider == stale.name
    assert current.calls == 0
    response = router.fetch_daily_bars(symbol="300017", market="cn", start="2026-10-20", end="2026-10-21", validate=True, prefer_complete_end=True)

    assert response.result is not None and response.result.provider == current.name
    assert response.result.df["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-10-21"]
    assert response.attempts[0].ok is False
    assert response.attempts[0].last_date == "2026-10-20"
    assert "no bar for requested end" in str(response.attempts[0].error)
    assert response.attempts[1].ok is True
    assert unused.calls == 0


def test_all_sources_lag_retain_the_latest_single_source_and_original_priority() -> None:
    adapters = [DatedAdapter("akshare_sina", ("2026-10-19",)),
                DatedAdapter("akshare", ("2026-10-20",)), DatedAdapter("baostock", ("2026-10-20",))]
    response = MarketDataRouter(adapters=adapters, policy={"cn": [a.name for a in adapters]}).fetch_daily_bars(
        symbol="300017", market="cn", start="2026-10-19", end="2026-10-21", validate=True, prefer_complete_end=True,
    )
    assert response.result is not None and response.result.provider == "akshare"
    assert all(attempt.ok is False for attempt in response.attempts)
    assert response.result.df["date"].max() == pd.Timestamp("2026-10-20")


def test_a_future_row_does_not_satisfy_the_requested_cutoff() -> None:
    ahead = DatedAdapter("tencent_qfq_history", ("2026-10-20", "2026-10-22"))
    current = DatedAdapter("akshare_sina", ("2026-10-21",))
    router = MarketDataRouter(adapters=[ahead, current], policy={"cn": [ahead.name, current.name]})
    response = router.fetch_daily_bars(symbol="300017", market="cn", start="2026-10-20", end="2026-10-21", prefer_complete_end=True)
    assert response.result is not None and response.result.provider == current.name
    assert response.attempts[0].last_date == "2026-10-22"
    assert response.attempts[0].ok is False

    future_only = DatedAdapter("akshare", ("2026-10-22",))
    response = MarketDataRouter(adapters=[future_only]).fetch_daily_bars(
        symbol="300017", market="cn", start="2026-10-20", end="2026-10-21", prefer_complete_end=True,
    )
    assert not response.ok


def test_a_valid_lag_does_not_open_the_source_family_circuit() -> None:
    stale = DatedAdapter("tencent_qfq_history", ("2026-10-20",))
    router = MarketDataRouter(adapters=[stale], failure_threshold=1)
    for symbol in ("300017", "300133"):
        response = router.fetch_daily_bars(symbol=symbol, market="cn", start="2026-10-20", end="2026-10-21", prefer_complete_end=True)
        assert response.result is not None
        assert not response.attempts[0].circuit_breaker_open
    assert stale.calls == 2
    assert router.provider_health_snapshot()["open_source_families"] == []


def test_end_preference_requires_an_explicit_cutoff() -> None:
    with pytest.raises(ValueError, match="requires end"):
        MarketDataRouter(adapters=[]).fetch_daily_bars(symbol="300017", market="cn", start="2026-10-20", prefer_complete_end=True)


def test_cutoff_resolver_uses_current_fallback_and_keeps_real_lag_when_all_lag(monkeypatch) -> None:
    from scripts.data import resolve_formal_provider_cutoff as resolver

    monkeypatch.setattr(resolver, "PROBE_DELAY_SECONDS", 0)
    stale = DatedAdapter("tencent_qfq_history", ("2026-10-20",))
    current = DatedAdapter("akshare_sina", ("2026-10-20", "2026-10-21"))
    router = MarketDataRouter(adapters=[stale, current], policy={"cn": [stale.name, current.name]})
    payload = resolver.resolve_formal_provider_cutoff(market="cn", requested_cutoff="2026-10-21", seed_cutoff="2026-10-20", router=router)
    assert payload["status"] == "current" and payload["effective_cutoff"] == "2026-10-21"
    assert payload["member_watermarks"]["300017"] == "2026-10-21"

    current.dates = ("2026-10-20", "2026-10-22")
    payload = resolver.resolve_formal_provider_cutoff(market="cn", requested_cutoff="2026-10-21", seed_cutoff="2026-10-20", router=router)
    assert payload["status"] == "delayed" and payload["effective_cutoff"] == "2026-10-20"


def test_selected_refresh_uses_current_fallback_in_the_first_retry_round() -> None:
    from scripts.data.refresh_selected_pool_prices import _fetch_with_retries

    stale = DatedAdapter("tencent_qfq_history", ("2026-10-20",))
    current = DatedAdapter("akshare_sina", ("2026-10-20", "2026-10-21"))
    router = MarketDataRouter(adapters=[stale, current], policy={"cn": [stale.name, current.name]})
    response, attempts = _fetch_with_retries(router, symbol="300017", market="cn", start="2026-10-20", cutoff="2026-10-21", max_rounds=3)
    assert response.result is not None and response.result.provider == current.name
    assert stale.calls == current.calls == 1
    assert [row["round"] for row in attempts] == [1, 1]
    assert attempts[-1]["cutoff_complete"] is True
