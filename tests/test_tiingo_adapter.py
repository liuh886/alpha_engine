from __future__ import annotations

import urllib.error
from typing import Any

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.tiingo_adapter import (
    TiingoAdapter,
    TiingoHttpClient,
    TiingoRateLimitError,
)


class FakeTiingoClient:
    def __init__(self, *, metadata_ticker: str = "QQQI") -> None:
        self.metadata_ticker = metadata_ticker
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get_json(
        self, path: str, *, params: dict[str, str] | None = None
    ) -> Any:
        self.calls.append((path, params))
        if path == "tiingo/daily/QQQI":
            return {
                "ticker": self.metadata_ticker,
                "name": "NEOS Nasdaq-100 High Income ETF",
                "exchangeCode": "NASDAQ",
                "startDate": "2024-01-30",
                "endDate": "2026-08-01",
                "description": "income ETF",
            }
        if path == "tiingo/daily/QQQI/prices":
            return [
                {
                    "date": "2024-01-30T00:00:00.000Z",
                    "open": 50.0,
                    "high": 51.0,
                    "low": 49.0,
                    "close": 50.5,
                    "volume": 1000,
                    "adjOpen": 48.0,
                    "adjHigh": 48.96,
                    "adjLow": 47.04,
                    "adjClose": 48.48,
                    "adjVolume": 1000,
                    "divCash": 0.0,
                    "splitFactor": 1.0,
                },
                {
                    "date": "2024-01-31T00:00:00.000Z",
                    "open": 50.5,
                    "high": 52.0,
                    "low": 50.0,
                    "close": 51.0,
                    "volume": 1200,
                    "adjOpen": 48.48,
                    "adjHigh": 49.92,
                    "adjLow": 48.0,
                    "adjClose": 48.96,
                    "adjVolume": 1200,
                    "divCash": 0.61,
                    "splitFactor": 1.0,
                },
            ]
        raise AssertionError(path)


def test_tiingo_uses_adjusted_ohlcv_and_retains_raw_actions() -> None:
    client = FakeTiingoClient()
    result = TiingoAdapter(client=client).fetch_daily_bars(
        FetchRequest(
            symbol="qqqi",
            market="us",
            start="2024-01-30",
            end="2024-01-31",
        )
    )

    assert result.provider == "tiingo"
    assert result.provider_symbol == "QQQI"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2024-01-30",
        "2024-01-31",
    ]
    assert result.df["open"].tolist() == pytest.approx([48.0, 48.48])
    assert result.df["close"].tolist() == pytest.approx([48.48, 48.96])
    assert result.df["raw_close"].tolist() == pytest.approx([50.5, 51.0])
    assert result.df["factor"].tolist() == pytest.approx(
        [48.48 / 50.5, 48.96 / 51.0]
    )
    assert result.df["cash_distribution"].tolist() == pytest.approx([0.0, 0.61])
    assert result.df["split_factor"].tolist() == pytest.approx([1.0, 1.0])
    assert result.df["amount"].tolist() == pytest.approx([48480.0, 58752.0])
    assert result.df.attrs["provider_metadata"]["ticker"] == "QQQI"
    assert result.df.attrs["provider_metadata"]["request_count"] == 2
    assert result.df.attrs["provider_metadata"]["elapsed_seconds"] >= 0.0
    assert client.calls[1] == (
        "tiingo/daily/QQQI/prices",
        {
            "startDate": "2024-01-30",
            "resampleFreq": "daily",
            "endDate": "2024-01-31",
        },
    )


def test_tiingo_rejects_metadata_identity_mismatch() -> None:
    with pytest.raises(DataFetchError, match="identity mismatch"):
        TiingoAdapter(client=FakeTiingoClient(metadata_ticker="QQQ")).fetch_daily_bars(
            FetchRequest(
                symbol="QQQI",
                market="us",
                start="2024-01-30",
                end="2024-01-31",
            )
        )


def test_tiingo_requires_explicit_token_or_client(monkeypatch) -> None:
    monkeypatch.delenv("TIINGO_API_TOKEN", raising=False)
    with pytest.raises(DataFetchError, match="TIINGO_API_TOKEN"):
        TiingoAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="QQQ",
                market="us",
                start="2024-01-01",
                end="2024-01-31",
            )
        )


def test_tiingo_rejects_non_us_market() -> None:
    with pytest.raises(DataFetchError, match="market=us"):
        TiingoAdapter(client=FakeTiingoClient()).fetch_daily_bars(
            FetchRequest(
                symbol="QQQI",
                market="cn",
                start="2024-01-30",
                end="2024-01-31",
            )
        )


def test_tiingo_frame_dates_are_timezone_naive() -> None:
    result = TiingoAdapter(client=FakeTiingoClient()).fetch_daily_bars(
        FetchRequest(
            symbol="QQQI",
            market="us",
            start="2024-01-30",
            end="2024-01-31",
        )
    )
    assert isinstance(result.df.loc[0, "date"], pd.Timestamp)
    assert result.df.loc[0, "date"].tzinfo is None


def test_tiingo_429_without_retry_after_uses_bounded_backoff(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"ok": true}'

    def rate_limit_then_succeed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise urllib.error.HTTPError(
                url="https://api.tiingo.com/tiingo/daily/QQQ",
                code=429,
                msg="Too Many Requests",
                hdrs={},
                fp=None,
            )
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", rate_limit_then_succeed)
    monkeypatch.setattr("time.sleep", sleeps.append)
    client = TiingoHttpClient(token="fixture-token", max_attempts=3)

    assert client.get_json("tiingo/daily/QQQ") == {"ok": True}
    assert calls == 3
    assert sleeps == [1, 2]


def test_tiingo_429_exposes_rate_limit_reset_without_long_sleep(
    monkeypatch,
) -> None:
    def raise_rate_limit(*args, **kwargs):
        raise urllib.error.HTTPError(
            url="https://api.tiingo.com/tiingo/daily/QQQ",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "3600", "X-RateLimit-Reset": "next-hour"},
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_rate_limit)
    client = TiingoHttpClient(
        token="fixture-token",
        max_attempts=3,
        max_retry_after_seconds=30.0,
    )

    with pytest.raises(TiingoRateLimitError) as captured:
        client.get_json("tiingo/daily/QQQ")

    error = captured.value
    assert error.status_code == 429
    assert error.error_class == "rate_limited"
    assert error.attempts == 1
    assert error.retry_after_seconds == 3600.0
    assert error.rate_limit_reset == "next-hour"
