from __future__ import annotations

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.tushare_adapter import TushareAdapter, _to_ts_code


class FakeTushareClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def query(self, api_name: str, *, params: dict, fields: str) -> pd.DataFrame:
        self.calls.append((api_name, params, fields))
        if api_name == "daily":
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000001.SZ"],
                    "trade_date": ["20210105", "20210104"],
                    "open": [20.0, 10.0],
                    "high": [22.0, 11.0],
                    "low": [18.0, 9.0],
                    "close": [21.0, 10.5],
                    "pre_close": [10.5, 10.0],
                    "vol": [12.0, 10.0],
                    "amount": [24.0, 10.0],
                }
            )
        if api_name == "adj_factor":
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000001.SZ"],
                    "trade_date": ["20210105", "20210104"],
                    "adj_factor": [2.0, 1.0],
                }
            )
        if api_name == "index_daily":
            return pd.DataFrame(
                {
                    "ts_code": ["000300.SH"],
                    "trade_date": ["20210104"],
                    "open": [5000.0],
                    "high": [5100.0],
                    "low": [4900.0],
                    "close": [5050.0],
                    "vol": [100.0],
                    "amount": [200.0],
                }
            )
        raise AssertionError(api_name)


def test_tushare_equity_freezes_qfq_anchor_and_normalizes_units():
    client = FakeTushareClient()
    result = TushareAdapter(client=client).fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2021-01-01",
            end="2021-01-05",
        )
    )

    assert result.provider_symbol == "000001.SZ"
    assert [call[0] for call in client.calls] == ["daily", "adj_factor"]
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2021-01-04",
        "2021-01-05",
    ]
    assert result.df["factor"].tolist() == pytest.approx([0.5, 1.0])
    assert result.df["open"].tolist() == pytest.approx([5.0, 20.0])
    assert result.df["close"].tolist() == pytest.approx([5.25, 21.0])
    assert result.df["volume"].tolist() == pytest.approx([1000.0, 1200.0])
    assert result.df["amount"].tolist() == pytest.approx([10000.0, 24000.0])


def test_tushare_index_uses_index_endpoint():
    client = FakeTushareClient()
    result = TushareAdapter(client=client).fetch_daily_bars(
        FetchRequest(
            symbol="000300",
            market="cn",
            start="2021-01-01",
            end="2021-01-05",
        )
    )
    assert result.provider_symbol == "000300.SH"
    assert [call[0] for call in client.calls] == ["index_daily"]
    assert result.df.iloc[0]["factor"] == pytest.approx(1.0)
    assert result.df.iloc[0]["volume"] == pytest.approx(10000.0)
    assert result.df.iloc[0]["amount"] == pytest.approx(200000.0)


def test_tushare_requires_token_or_injected_client(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(DataFetchError, match="TUSHARE_TOKEN"):
        TushareAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="000001",
                market="cn",
                start="2021-01-01",
                end="2021-01-05",
            )
        )


def test_tushare_symbol_mapping_covers_cn_boards():
    assert _to_ts_code("000001") == "000001.SZ"
    assert _to_ts_code("301291") == "301291.SZ"
    assert _to_ts_code("600009") == "600009.SH"
    assert _to_ts_code("688521") == "688521.SH"
    assert _to_ts_code("000300") == "000300.SH"
