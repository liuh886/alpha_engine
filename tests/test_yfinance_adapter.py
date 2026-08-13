from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.yfinance_adapter import (
    CN_ETF_PRICE_TICK,
    OHLC_ROUNDING_REL_TOL,
    YFinanceAdapter,
    _get_yahoo_ticker,
    _reconcile_ohlc_rounding,
)


def _frame(dates: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.to_datetime(dates), name="Date")
    close = [10.5 + i for i in range(len(index))]
    return pd.DataFrame(
        {
            "Open": [10.0 + i for i in range(len(index))],
            "High": [11.0 + i for i in range(len(index))],
            "Low": [9.0 + i for i in range(len(index))],
            "Close": close,
            "Adj Close": close,
            "Volume": [1000 + i for i in range(len(index))],
        },
        index=index,
    )


def test_yfinance_translates_inclusive_end_and_clips_provider_rows(monkeypatch):
    captured: dict[str, object] = {}

    def download(
        ticker,
        *,
        start,
        end,
        progress,
        auto_adjust,
        repair,
        threads,
    ):
        captured.update(
            {
                "ticker": ticker,
                "start": start,
                "end": end,
                "progress": progress,
                "auto_adjust": auto_adjust,
                "repair": repair,
                "threads": threads,
            }
        )
        return _frame(["2026-06-17", "2026-06-18", "2026-06-19"])

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
    result = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2026-06-17",
            end="2026-06-18",
        )
    )
    assert captured == {
        "ticker": "000001.SZ",
        "start": "2026-06-17",
        "end": "2026-06-19",
        "progress": False,
        "auto_adjust": False,
        "repair": True,
        "threads": False,
    }
    assert result.end == "2026-06-18"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-06-17",
        "2026-06-18",
    ]
    assert result.df.iloc[0]["open"] == pytest.approx(10.0)
    assert result.df.iloc[0]["high"] == pytest.approx(11.0)
    assert result.df.iloc[0]["low"] == pytest.approx(9.0)
    assert result.df.iloc[0]["close"] == pytest.approx(10.5)
    assert result.df.iloc[0]["amount"] == pytest.approx(10500.0)


def test_uniform_adj_close_ratio_preserves_ohlc_envelope(monkeypatch):
    index = pd.DatetimeIndex(pd.to_datetime(["2026-08-12"]), name="Date")
    frame = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [110.0],
            "Low": [90.0],
            "Close": [105.0],
            "Adj Close": [99.75],
            "Volume": [1000.0],
        },
        index=index,
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda *args, **kwargs: frame),
    )
    result = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="ETN",
            market="us",
            start="2026-08-12",
            end="2026-08-12",
        )
    )
    ratio = 99.75 / 105.0
    assert result.df.loc[0, "open"] == pytest.approx(100.0 * ratio)
    assert result.df.loc[0, "high"] == pytest.approx(110.0 * ratio)
    assert result.df.loc[0, "low"] == pytest.approx(90.0 * ratio)
    assert result.df.loc[0, "close"] == pytest.approx(99.75)
    evidence = result.df.attrs["ohlc_rounding_reconciliation"]
    assert evidence["adjustment_method"] == "uniform_adj_close_ratio"
    assert evidence["max_relative_violation"] == pytest.approx(0.0)


def test_cn_yahoo_exchange_mapping_covers_main_boards_and_growth_boards():
    assert _get_yahoo_ticker("000001", "cn") == "000001.SZ"
    assert _get_yahoo_ticker("301291", "cn") == "301291.SZ"
    assert _get_yahoo_ticker("600009", "cn") == "600009.SS"
    assert _get_yahoo_ticker("688521", "cn") == "688521.SS"
    assert _get_yahoo_ticker("000300", "cn") == "000300.SS"
    assert _get_yahoo_ticker("515180", "cn") == "515180.SS"


def test_yfinance_current_snapshot_keeps_open_ended_provider_request(monkeypatch):
    captured: dict[str, object] = {}

    def download(ticker, **kwargs):
        captured["end"] = kwargs["end"]
        return _frame(["2026-06-17", "2026-06-18"])

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
    result = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(symbol="AAPL", market="us", start="2026-06-17")
    )
    assert captured["end"] is None
    assert result.end is None


def test_yfinance_rejects_invalid_or_reversed_boundaries(monkeypatch):
    called = False

    def download(*args, **kwargs):
        nonlocal called
        called = True
        return _frame(["2026-06-18"])

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
    adapter = YFinanceAdapter()
    with pytest.raises(DataFetchError, match="invalid end"):
        adapter.fetch_daily_bars(
            FetchRequest(
                symbol="AAPL",
                market="us",
                start="2026-06-17",
                end="not-a-date",
            )
        )
    assert called is False
    with pytest.raises(DataFetchError, match="end must be on or after start"):
        adapter.fetch_daily_bars(
            FetchRequest(
                symbol="AAPL",
                market="us",
                start="2026-06-19",
                end="2026-06-18",
            )
        )
    assert called is False


def test_tiny_ohlc_rounding_violation_is_reconciled_with_evidence():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-17"]),
            "open": [10.0],
            "high": [11.0 - 1e-10],
            "low": [9.0],
            "close": [11.0],
            "volume": [100.0],
            "amount": [1100.0],
            "factor": [1.0],
        }
    )
    reconciled, evidence = _reconcile_ohlc_rounding(frame)
    assert reconciled.loc[0, "high"] == pytest.approx(11.0)
    assert evidence["corrected_rows"] == 1
    assert evidence["corrected_high_rows"] == 1
    assert evidence["corrected_low_rows"] == 0
    assert evidence["max_relative_violation"] < OHLC_ROUNDING_REL_TOL
    assert reconciled.attrs["ohlc_rounding_reconciliation"] == evidence


def test_provider_scale_adjusted_ohlc_drift_is_reconciled():
    close = 100.0
    relative_gap = 2.2e-4
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-07"]),
            "open": [99.0],
            "high": [close * (1.0 - relative_gap)],
            "low": [98.0],
            "close": [close],
            "volume": [100.0],
            "amount": [10000.0],
            "factor": [1.0],
        }
    )
    reconciled, evidence = _reconcile_ohlc_rounding(frame)
    assert evidence["max_relative_violation"] == pytest.approx(relative_gap)
    assert evidence["max_relative_violation"] < OHLC_ROUNDING_REL_TOL
    assert reconciled.loc[0, "high"] == pytest.approx(close)


def test_cn_etf_one_tick_ohlc_rounding_is_reconciled(monkeypatch):
    index = pd.DatetimeIndex(pd.to_datetime(["2026-08-07"]), name="Date")
    frame = pd.DataFrame(
        {
            "Open": [1.323],
            "High": [1.323],
            "Low": [1.320],
            "Close": [1.324],
            "Adj Close": [1.324],
            "Volume": [1000.0],
        },
        index=index,
    )
    relative_gap = CN_ETF_PRICE_TICK / 1.324
    assert relative_gap > OHLC_ROUNDING_REL_TOL
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda *args, **kwargs: frame),
    )
    result = YFinanceAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="515180",
            market="cn",
            start="2026-08-07",
            end="2026-08-07",
        )
    )
    evidence = result.df.attrs["ohlc_rounding_reconciliation"]
    assert result.df.loc[0, "high"] == pytest.approx(1.324)
    assert evidence["absolute_tolerance"] == CN_ETF_PRICE_TICK
    assert evidence["raw_reconciliation"]["max_relative_violation"] > OHLC_ROUNDING_REL_TOL
    assert evidence["raw_reconciliation"]["max_absolute_violation"] == pytest.approx(
        CN_ETF_PRICE_TICK
    )


def test_same_one_tick_relative_gap_remains_material_for_cn_stock(monkeypatch):
    index = pd.DatetimeIndex(pd.to_datetime(["2026-08-07"]), name="Date")
    frame = pd.DataFrame(
        {
            "Open": [1.323],
            "High": [1.323],
            "Low": [1.320],
            "Close": [1.324],
            "Adj Close": [1.324],
            "Volume": [1000.0],
        },
        index=index,
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda *args, **kwargs: frame),
    )
    with pytest.raises(DataFetchError, match="material Yahoo OHLC"):
        YFinanceAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="600009",
                market="cn",
                start="2026-08-07",
                end="2026-08-07",
            )
        )


def test_material_ohlc_inconsistency_remains_rejected(monkeypatch):
    frame = _frame(["2026-06-17"])
    frame.loc[:, "High"] = 10.0
    frame.loc[:, "Close"] = 12.0
    frame.loc[:, "Adj Close"] = 12.0
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(download=lambda *args, **kwargs: frame),
    )
    with pytest.raises(DataFetchError, match="material Yahoo OHLC"):
        YFinanceAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="000063",
                market="cn",
                start="2026-06-17",
                end="2026-06-17",
            )
        )
