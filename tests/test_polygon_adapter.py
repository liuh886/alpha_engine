from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.polygon_adapter import PolygonAdapter


@dataclass
class FakePolygonClient:
    returned_ticker: str = "AAPL"

    def get_json(self, path: str, *, params=None):
        if path.startswith("v3/reference/tickers/"):
            return {
                "status": "OK",
                "results": {
                    "ticker": self.returned_ticker,
                    "name": "Apple Inc.",
                    "market": "stocks",
                    "primary_exchange": "XNAS",
                    "type": "CS",
                    "active": True,
                    "list_date": "1980-12-12",
                    "composite_figi": "BBG000B9XRY4",
                },
            }
        if path.startswith("v2/aggs/ticker/"):
            return {
                "status": "OK",
                "results": [
                    {
                        "t": int(pd.Timestamp("2026-07-30", tz="UTC").timestamp() * 1000),
                        "o": 210.0,
                        "h": 213.0,
                        "l": 209.0,
                        "c": 212.0,
                        "v": 1000.0,
                    },
                    {
                        "t": int(pd.Timestamp("2026-07-31", tz="UTC").timestamp() * 1000),
                        "o": 212.0,
                        "h": 214.0,
                        "l": 211.0,
                        "c": 213.0,
                        "v": 1200.0,
                    },
                ],
            }
        raise AssertionError(path)


def test_polygon_adapter_validates_identity_and_normalizes_bars():
    result = PolygonAdapter(client=FakePolygonClient()).fetch_daily_bars(
        FetchRequest(
            symbol="AAPL",
            market="us",
            start="2026-07-30",
            end="2026-07-31",
        )
    )
    assert result.provider == "polygon"
    assert result.provider_symbol == "AAPL"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-30",
        "2026-07-31",
    ]
    assert result.df["factor"].tolist() == pytest.approx([1.0, 1.0])
    assert result.df.iloc[0]["amount"] == pytest.approx(212000.0)
    assert result.df.attrs["provider_metadata"]["primary_exchange"] == "XNAS"
    assert result.df.attrs["provider_metadata"]["request_count"] == 2


def test_polygon_adapter_rejects_identity_substitution():
    with pytest.raises(DataFetchError, match="identity mismatch"):
        PolygonAdapter(client=FakePolygonClient(returned_ticker="MSFT")).fetch_daily_bars(
            FetchRequest(
                symbol="AAPL",
                market="us",
                start="2026-07-30",
                end="2026-07-31",
            )
        )


def test_polygon_adapter_requires_explicit_credential(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(DataFetchError, match="POLYGON_API_KEY"):
        PolygonAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="AAPL",
                market="us",
                start="2026-07-30",
                end="2026-07-31",
            )
        )
