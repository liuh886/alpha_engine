from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from src.data.adapters.base import (
    DataFetchError,
    FetchRequest,
    ProviderContractError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from src.data.adapters.twelve_data_adapter import (
    TwelveDataAdapter,
    TwelveDataHttpClient,
)


def _payload(*, symbol: str = "QQQ", values: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "meta": {
            "symbol": symbol,
            "interval": "1day",
            "currency": "USD",
            "exchange": "NASDAQ",
            "type": "ETF",
        },
        "values": values
        if values is not None
        else [
            {
                "datetime": "2024-01-30",
                "open": "400.0",
                "high": "402.0",
                "low": "399.0",
                "close": "401.0",
                "volume": "1000",
            },
            {
                "datetime": "2024-01-31",
                "open": "401.0",
                "high": "403.0",
                "low": "400.0",
                "close": "402.0",
                "volume": "1200",
            },
        ],
        "status": "ok",
    }


class FakeTwelveDataClient:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        self.calls.append((path, params))
        return self.payload


def test_twelve_data_normalises_adjusted_ohlcv_and_records_provenance() -> None:
    client = FakeTwelveDataClient(_payload())
    result = TwelveDataAdapter(client=client).fetch_daily_bars(
        FetchRequest(symbol="qqq", market="us", start="2024-01-30", end="2024-01-31")
    )

    assert result.provider == "twelve_data"
    assert result.provider_symbol == "QQQ"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-01-30",
        "2024-01-31",
    ]
    assert result.df["open"].tolist() == pytest.approx([400.0, 401.0])
    assert result.df["close"].tolist() == pytest.approx([401.0, 402.0])
    assert result.df["factor"].tolist() == pytest.approx([1.0, 1.0])
    assert result.df["amount"].tolist() == pytest.approx([401000.0, 482400.0])
    assert result.df.attrs["price_mode"] == "adjusted_ohlcv"

    provenance = result.provenance
    assert provenance is not None
    assert provenance["provider"] == "twelve_data"
    assert provenance["provider_symbol"] == "QQQ"
    assert provenance["response_sha256"] and len(provenance["response_sha256"]) == 64
    assert provenance["fetched_at_utc"].endswith("+00:00")
    assert provenance["price_mode"] == "adjusted_ohlcv"
    assert provenance["adjustment_method"] == "provider_adjust_all_native"
    assert provenance["volume_basis"] == "provider_adjusted_volume"
    assert "apikey" not in provenance["request"]
    assert provenance["request"]["adjust"] == "all"
    assert provenance["request"]["interval"] == "1day"
    assert provenance["request"]["order"] == "ASC"
    assert provenance["request"]["start_date"] == "2024-01-30"
    assert provenance["request"]["end_date"] == "2024-01-31"

    path, params = client.calls[0]
    assert path == "time_series"
    assert params is not None
    assert params["symbol"] == "QQQ"
    assert params["interval"] == "1day"
    assert params["adjust"] == "all"
    assert int(params["outputsize"]) >= 2


def test_twelve_data_rejects_non_positive_ohlc() -> None:
    payload = _payload(
        values=[
            {
                "datetime": "2024-01-30",
                "open": "0",
                "high": "402.0",
                "low": "399.0",
                "close": "401.0",
                "volume": "1000",
            }
        ]
    )
    with pytest.raises(ProviderContractError, match="non-positive OHLC"):
        TwelveDataAdapter(client=FakeTwelveDataClient(payload)).fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="us", start="2024-01-30", end="2024-01-30")
        )


def test_twelve_data_rejects_non_finite_values() -> None:
    payload = _payload(
        values=[
            {
                "datetime": "2024-01-30",
                "open": "NaN",
                "high": "402.0",
                "low": "399.0",
                "close": "401.0",
                "volume": "1000",
            }
        ]
    )
    with pytest.raises(ProviderContractError, match="non-finite"):
        TwelveDataAdapter(client=FakeTwelveDataClient(payload)).fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="us", start="2024-01-30", end="2024-01-30")
        )


def test_twelve_data_rejects_duplicate_dates_without_filling() -> None:
    values = [
        {
            "datetime": "2024-01-30",
            "open": "400.0",
            "high": "402.0",
            "low": "399.0",
            "close": "401.0",
            "volume": "1000",
        }
    ]
    payload = _payload(values=values + values)
    with pytest.raises(ProviderContractError, match="duplicate dates"):
        TwelveDataAdapter(client=FakeTwelveDataClient(payload)).fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="us", start="2024-01-30", end="2024-01-31")
        )


def test_twelve_data_rejects_symbol_identity_mismatch() -> None:
    with pytest.raises(ProviderContractError, match="identity mismatch"):
        TwelveDataAdapter(client=FakeTwelveDataClient(_payload(symbol="SPY"))).fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="us", start="2024-01-30", end="2024-01-31")
        )


def test_twelve_data_classifies_api_rate_limit_as_transient() -> None:
    payload = {
        "code": 429,
        "message": "You have run out of API credits for the current minute.",
        "status": "error",
    }
    with pytest.raises(ProviderRateLimitError):
        TwelveDataAdapter(client=FakeTwelveDataClient(payload)).fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="us", start="2024-01-30", end="2024-01-31")
        )


def test_twelve_data_requires_token_or_client(monkeypatch) -> None:
    monkeypatch.delenv("TWELVE_DATA_API_TOKEN", raising=False)
    with pytest.raises(DataFetchError, match="TWELVE_DATA_API_TOKEN"):
        TwelveDataAdapter().fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="us", start="2024-01-01", end="2024-01-31")
        )


def test_twelve_data_rejects_non_us_market() -> None:
    with pytest.raises(DataFetchError, match="market=us"):
        TwelveDataAdapter(client=FakeTwelveDataClient(_payload())).fetch_daily_bars(
            FetchRequest(symbol="QQQ", market="cn", start="2024-01-30", end="2024-01-31")
        )


def test_twelve_data_http_timeout_is_typed_transient(monkeypatch) -> None:
    def raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", raise_timeout)
    client = TwelveDataHttpClient(token="fixture-token")
    with pytest.raises(ProviderTimeoutError):
        client.get_json("time_series", params={"symbol": "QQQ"})


def test_twelve_data_http_429_is_rate_limit(monkeypatch) -> None:
    def raise_rate_limit(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://api.twelvedata.com/time_series",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "12"},
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_rate_limit)
    client = TwelveDataHttpClient(token="fixture-token")
    with pytest.raises(ProviderRateLimitError) as captured:
        client.get_json("time_series", params={"symbol": "QQQ"})
    assert captured.value.retry_after_seconds == 12.0
