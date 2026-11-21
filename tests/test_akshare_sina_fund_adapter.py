from __future__ import annotations

import datetime as dt
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.akshare_sina_fund_adapter import AkShareSinaFundAdapter
from src.data.adapters.base import DataFetchError, FetchRequest


def _sina_frame(
    *,
    dates: tuple[dt.date, ...] = (
        dt.date(2026, 11, 19),
        dt.date(2026, 11, 17),
        dt.date(2026, 11, 18),
        dt.date(2026, 11, 18),
        dt.date(2026, 11, 10),
        dt.date(2026, 11, 22),
    ),
    closes: tuple[float, ...] = (1.373, 1.352, 1.358, 1.358, 1.341, 1.390),
    volume_scale: float = 1.0,
) -> pd.DataFrame:
    opens = tuple(value - 0.01 for value in closes)
    volumes = tuple(218_500_662.0 - 1_000_000.0 * index for index in range(len(closes)))
    return pd.DataFrame(
        {
            "date": list(dates),
            "open": opens,
            "high": tuple(value + 0.02 for value in closes),
            "low": tuple(value - 0.02 for value in closes),
            "close": list(closes),
            "volume": volumes,
            "amount": tuple(
                volume * close * volume_scale
                for volume, close in zip(volumes, closes, strict=True)
            ),
            "postVol": [0.0] * len(closes),
            "postAmt": [0.0] * len(closes),
        }
    )


def _install(monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame, calls: list[str]) -> None:
    def fund_etf_hist_sina(*, symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return frame

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(fund_etf_hist_sina=fund_etf_hist_sina),
    )


def _request(symbol: str = "515180", start: str = "2026-11-17", end: str = "2026-11-21") -> FetchRequest:
    return FetchRequest(symbol=symbol, market="cn", start=start, end=end)


def test_sina_fund_parses_date_objects_and_clips_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame(), calls)

    result = AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())

    assert calls == ["sh515180"]
    assert result.provider == "akshare_sina_fund"
    assert result.provider_symbol == "sh515180"
    assert result.symbol == "515180"
    assert result.market == "cn"
    # datetime.date -> ISO session dates; exact window clip, ascending, unique.
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-11-17",
        "2026-11-18",
        "2026-11-19",
    ]
    assert result.df["date"].is_monotonic_increasing
    assert result.df["date"].is_unique
    # No fill: the 2026-11-20 gap is not invented.
    assert "2026-11-20" not in result.df["date"].dt.strftime("%Y-%m-%d").tolist()
    assert result.df["factor"].eq(1.0).all()
    assert result.df["amount"].isna().all()
    assert result.df["volume"].isna().all()
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


def test_sina_fund_records_provider_provenance_and_withheld_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame(), calls)

    result = AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())
    provenance = result.provenance

    assert provenance is not None
    assert provenance["provider"] == "akshare_sina_fund"
    assert provenance["provider_symbol"] == "sh515180"
    assert provenance["source_url"].startswith(
        "https://finance.sina.com.cn/realstock/company/sh515180/"
    )
    assert provenance["source_date_format"] == "date"
    assert "postVol" in provenance["source_schema"]
    assert provenance["price_basis"] == "provider_reported_raw"
    assert provenance["volume_basis"] == "withheld_sina_reported_shares"
    assert provenance["amount_basis"].startswith("withheld_")
    assert provenance["research_only"] is True
    assert provenance["trade_ready"] is False
    assert len(provenance["response_sha256"]) == 64
    assert provenance["rows"] == 3
    assert provenance["first_date"] == "2026-11-17"
    assert provenance["last_date"] == "2026-11-19"
    assert "median" in provenance["terms_caveat"]
    assert "withheld" in provenance["terms_caveat"]


def test_sina_fund_classifies_lot_basis_without_fabricating_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame(volume_scale=0.01), calls)

    result = AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())

    assert result.provenance is not None
    assert result.provenance["volume_basis"] == "withheld_sina_reported_lots_cny"
    assert result.df["volume"].isna().all()


def test_sina_fund_rejects_unreconcilable_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame(volume_scale=1000.0), calls)

    with pytest.raises(DataFetchError, match="unrecognized volume/amount unit basis"):
        AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())


def test_sina_fund_requires_volume_and_amount_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame().drop(columns=["amount"]), calls)

    with pytest.raises(DataFetchError, match="missing columns.*amount"):
        AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())


def test_sina_fund_rejects_non_positive_ohlc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _sina_frame()
    # index 3 is the retained duplicate for 2026-11-18 (keep="last").
    frame.loc[frame.index[3], "close"] = 0.0
    calls: list[str] = []
    _install(monkeypatch, frame, calls)

    with pytest.raises(DataFetchError, match="non-finite or non-positive OHLC"):
        AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())


def test_sina_fund_rejects_unparseable_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _sina_frame()
    frame.loc[frame.index[0], "date"] = "not-a-date"
    calls: list[str] = []
    _install(monkeypatch, frame, calls)

    with pytest.raises(DataFetchError, match="unparseable dates"):
        AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(_request())


def test_sina_fund_rejects_empty_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame(), calls)

    with pytest.raises(DataFetchError, match="has no bars"):
        AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(
            _request(start="2026-12-01", end="2026-12-02")
        )


def test_sina_fund_does_not_call_endpoint_for_non_etf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install(monkeypatch, _sina_frame(), calls)

    with pytest.raises(DataFetchError, match="supports CN ETFs/funds only"):
        AkShareSinaFundAdapter(min_interval_seconds=0.0).fetch_daily_bars(
            _request(symbol="600519")
        )
    assert calls == []
