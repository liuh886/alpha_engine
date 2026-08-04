from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError
from src.data.adapters.polygon_intraday_adapter import (
    PolygonIntradayAdapter,
    PolygonIntradayRequest,
)


def _millis(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


def _bar(timestamp: str, price: float, volume: float = 1000.0) -> dict:
    return {
        "t": _millis(timestamp),
        "o": price,
        "h": price + 2.0,
        "l": price - 1.0,
        "c": price + 1.0,
        "v": volume,
        "vw": price + 0.5,
        "n": 250,
    }


@dataclass
class FakePolygonIntradayClient:
    returned_ticker: str = "QQQ"
    paginated: bool = False
    endless: bool = False
    calls: list[tuple[str, dict | None]] = field(default_factory=list)

    def get_json(self, path: str, *, params=None):
        self.calls.append((path, params))
        if path == "v2/aggs/next":
            payload = {
                "status": "OK",
                "ticker": self.returned_ticker,
                "results": [
                    _bar("2026-07-30 14:00:00+00:00", 502.0, 800.0)
                ],
            }
            if self.endless:
                payload["next_url"] = (
                    "https://api.polygon.io/v2/aggs/next?cursor=again&apiKey=secret"
                )
            return payload
        if path.startswith("v2/aggs/ticker/"):
            results = [
                _bar("2026-07-30 13:00:00+00:00", 499.0, 100.0),
                _bar("2026-07-30 13:30:00+00:00", 500.0, 1000.0),
            ]
            payload = {
                "status": "OK",
                "ticker": self.returned_ticker,
                "results": results,
            }
            if self.paginated or self.endless:
                payload["next_url"] = (
                    "https://api.polygon.io/v2/aggs/next?cursor=abc&apiKey=secret"
                )
            else:
                payload["results"].append(
                    _bar("2026-07-30 14:00:00+00:00", 502.0, 800.0)
                )
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
        "request_delay_seconds": 0.0,
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
    assert result.df.iloc[0]["vwap"] == pytest.approx(500.5)
    metadata = result.df.attrs["provider_metadata"]
    assert metadata["request_count"] == 1
    assert metadata["pages"] == 1
    assert metadata["pagination_completed"] is True
    assert metadata["multiplier"] == 30
    assert metadata["timezone"] == "America/New_York"


def test_polygon_intraday_completes_pagination_without_forwarding_api_key():
    client = FakePolygonIntradayClient(paginated=True)
    result = PolygonIntradayAdapter(client=client).fetch_aggregate_bars(
        _request()
    )
    assert result.df["timestamp_et"].dt.strftime("%H:%M").tolist() == [
        "09:30",
        "10:00",
    ]
    metadata = result.df.attrs["provider_metadata"]
    assert metadata["pages"] == 2
    assert metadata["pagination_used"] is True
    assert metadata["pagination_completed"] is True
    assert metadata["raw_results_count"] == 3
    assert client.calls[1][0] == "v2/aggs/next"
    assert client.calls[1][1] == {"cursor": "abc"}


def test_polygon_intraday_rejects_unbounded_pagination():
    with pytest.raises(DataFetchError, match="exceeded max_pages"):
        PolygonIntradayAdapter(
            client=FakePolygonIntradayClient(endless=True)
        ).fetch_aggregate_bars(_request(max_pages=2))


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
            self.calls.append((path, params))
            return {
                "status": "OK",
                "ticker": "QQQ",
                "results": [
                    _bar("2026-01-05 14:30:00+00:00", 500.0),
                    _bar("2026-07-06 13:30:00+00:00", 510.0),
                ],
            }

    result = PolygonIntradayAdapter(client=DstClient()).fetch_aggregate_bars(
        _request(start="2026-01-05", end="2026-07-06")
    )
    assert result.df["timestamp_et"].dt.strftime("%H:%M").tolist() == [
        "09:30",
        "09:30",
    ]
