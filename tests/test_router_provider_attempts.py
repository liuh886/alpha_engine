from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

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
    }
