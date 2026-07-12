from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.base import DataFetchError, FetchRequest


def test_csi300_uses_index_endpoint_and_preserves_missing_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def stock_zh_index_daily(*, symbol: str) -> pd.DataFrame:
        calls.append(("index", symbol))
        return pd.DataFrame(
            {
                "date": ["2020-12-31", "2021-01-04", "2021-01-05", "2021-01-06"],
                "open": [5200.0, 5210.0, 5220.0, 5230.0],
                "high": [5210.0, 5220.0, 5230.0, 5240.0],
                "low": [5190.0, 5200.0, 5210.0, 5220.0],
                "close": [5205.0, 5215.0, 5225.0, 5235.0],
                "volume": [100.0, 110.0, 120.0, 130.0],
            }
        )

    def stock_zh_a_hist(**_: object) -> pd.DataFrame:
        raise AssertionError("CSI 300 must not use the A-share stock endpoint")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=stock_zh_index_daily,
            stock_zh_a_hist=stock_zh_a_hist,
        ),
    )

    result = AkShareAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="000300",
            market="cn",
            start="2021-01-01",
            end="2021-01-05",
        )
    )

    assert calls == [("index", "sh000300")]
    assert result.provider_symbol == "sh000300"
    assert result.symbol == "000300"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2021-01-04",
        "2021-01-05",
    ]
    assert result.df["amount"].isna().all()
    assert result.df["factor"].eq(1.0).all()
    assert result.df.columns.tolist() == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "factor",
    ]


def test_regular_cn_stock_keeps_adjusted_stock_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def stock_zh_a_hist(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "日期": ["2021-01-04"],
                "开盘": [100.0],
                "最高": [101.0],
                "最低": [99.0],
                "收盘": [100.5],
                "成交量": [1000.0],
                "成交额": [100500.0],
            }
        )

    def stock_zh_index_daily(*, symbol: str) -> pd.DataFrame:
        raise AssertionError(f"regular stock unexpectedly used index endpoint: {symbol}")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=stock_zh_index_daily,
            stock_zh_a_hist=stock_zh_a_hist,
        ),
    )

    result = AkShareAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="600519",
            market="cn",
            start="2021-01-01",
            end="2021-01-05",
        )
    )

    assert calls == [
        {
            "symbol": "600519",
            "period": "daily",
            "start_date": "20210101",
            "end_date": "20210105",
            "adjust": "qfq",
        }
    ]
    assert result.provider_symbol == "600519"
    assert result.df.loc[0, "amount"] == 100500.0


def test_csi300_index_payload_requires_real_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=lambda **_: pd.DataFrame(
                {
                    "date": ["2021-01-04"],
                    "open": [5200.0],
                    "high": [5210.0],
                    "low": [5190.0],
                    "close": [5205.0],
                }
            ),
            stock_zh_a_hist=lambda **_: pd.DataFrame(),
        ),
    )

    with pytest.raises(DataFetchError, match="missing columns.*volume"):
        AkShareAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="000300",
                market="cn",
                start="2021-01-01",
            )
        )
