from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError
from src.data.adapters.polygon_intraday_adapter import (
    PolygonIntradayAdapter,
    PolygonIntradayRequest,
)


def _millis(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


@dataclass
class FakePolygonIntradayClient:
    returned_ticker: str = "QQQ"
    paginated: bool = False

    def get_json(self, path: str, *, params=None):
        if path.startswith("v3/reference/tickers/"):
            return {
                "status": "OK",
                "results": {
                    "ticker": self.returned_ticker,
                    "name": "Invesco QQQ Trust",
                    "market": "stocks",
                    "primary_exchange": "XNAS",
                    "type": "ETF",
                    "active": True,
                    "list_date": "1999-03-10",
                    "composite_figi": "BBG000BSWKH7",
                },
            }
        if path.startswith("v2/aggs/ticker/"):
            payload = {
                "status": "OK",
                "results": [
                    {
                        "t": _millis("2026-07-30 13:00:00+00:00"),
                        "o": 499.0,
                        "h": 500.0,
                        "l": 498.0,
                        "c": 499.5,
                        "v": 100.0,
                    },
                    {
                        "t": _millis("2026-07-30 13:30:00+00:00"),
                        "o": 500.0,
                        "h": 503.0,
                        "l": 499.0,
                        "c": 502.0,
                        "v": 1000.0,
                        "vw": 501.2,
                        "n": 250,
                    },
                    {
                        "t": _millis("2026-07-30 14:00:00+00:00"),
                        "o": 502.0,
                        "h": 504.0,
                        "l": 501.0,
                        "c": 503.0,
                        "v": 800.0,
                    },
                ],
            }
            if self.paginated:
                payload["next_url"] = "https://api.polygon.io/v2/aggs/next"
            return payload
        raise AssertionError(path)


def _request(**overrides):
    values = {
        "symbol": "QQQ",
        "market": "us",
        "start": "2026-07-30",
        "end": "2026-07-30",
        "multiplier": 30,
        "timespan": "minute",
        "regular_session_only": True,
    }
    values.update(overrides)
    return PolygonIntradayRequest(**values)


def test_polygon_intraday_filters_regular_session_and_preserves_timezone():
    result = PolygonIntradayAdapter(
        client=FakePolygonIntradayClient()
    ).fetch_aggregate_bars(_request())
    assert result.provider == "polygon_intraday"
    assert result.provider_symbol == "QQQ"
    assert result.df["timestamp_et"].dt.strftime("%H:%M").tolist() == [
        "09:30",
        "10:00",
    ]
    assert result.df["session_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-30",
        "2026-07-30",
    ]
    assert result.df.iloc[0]["vwap"] == pytest.approx(501.2)
    metadata = result.df.attrs["provider_metadata"]
    assert metadata["request_count"] == 2
    assert metadata["multiplier"] == 30
    assert metadata["timezone"] == "America/New_York"


def test_polygon_intraday_rejects_pagination_or_truncation():
    with pytest.raises(DataFetchError, match="requires pagination"):
        PolygonIntradayAdapter(
            client=FakePolygonIntradayClient(paginated=True)
        ).fetch_aggregate_bars(_request())


def test_polygon_intraday_rejects_identity_substitution():
    with pytest.raises(DataFetchError, match="identity mismatch"):
        PolygonIntradayAdapter(
            client=FakePolygonIntradayClient(returned_ticker="SPY")
        ).fetch_aggregate_bars(_request())


def test_polygon_intraday_requires_explicit_credential(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(DataFetchError, match="POLYGON_API_KEY"):
        PolygonIntradayAdapter().fetch_aggregate_bars(_request())


def test_polygon_intraday_dst_open_alignment():
    class DstClient(FakePolygonIntradayClient):
        def get_json(self, path: str, *, params=None):
            if path.startswith("v3/reference/tickers/"):
                return super().get_json(path, params=params)
            return {
                "status": "OK",
                "results": [
                    {
                        "t": _millis("2026-01-05 14:30:00+00:00"),
                        "o": 500.0,
                        "h": 501.0,
                        "l": 499.0,
                        "c": 500.5,
                        "v": 1000.0,
                    },
                    {
                        "t": _millis("2026-07-06 13:30:00+00:00"),
                        "o": 510.0,
                        "h": 511.0,
                        "l": 509.0,
                        "c": 510.5,
                        "v": 1000.0,
                    },
                ],
            }

    result = PolygonIntradayAdapter(client=DstClient()).fetch_aggregate_bars(
        _request(start="2026-01-05", end="2026-07-06")
    )
    assert result.df["timestamp_et"].dt.strftime("%H:%M").tolist() == [
        "09:30",
        "09:30",
    ]
