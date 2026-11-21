from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.akshare_adapter import (
    AkShareAdapter,
    _translate_fund_transport_error,
)
from src.data.adapters.base import (
    DataFetchError,
    FetchRequest,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from src.data.provider_retry import RetryPolicy

NO_DELAY = RetryPolicy(
    max_attempts=3,
    base_delay_seconds=0.0,
    max_delay_seconds=0.0,
    max_honored_retry_after_seconds=30.0,
    jitter_ratio=0.0,
)


def _fund_etf_frame() -> pd.DataFrame:
    """Eastmoney fund fixture: out-of-order, duplicate, and outside the window."""

    return pd.DataFrame(
        {
            "日期": [
                "2026-11-19",
                "2026-11-17",
                "2026-11-18",
                "2026-11-18",
                "2026-11-10",
                "2026-11-20",
            ],
            "开盘": [1.360, 1.350, 1.355, 1.355, 1.340, 1.380],
            "收盘": [1.373, 1.352, 1.358, 1.358, 1.341, 1.390],
            "最高": [1.380, 1.360, 1.360, 1.360, 1.350, 1.400],
            "最低": [1.350, 1.340, 1.350, 1.350, 1.330, 1.370],
            "成交量": [1000.0, 900.0, 950.0, 950.0, 800.0, 1100.0],
            "成交额": [
                1373000.0,
                1216800.0,
                1288700.0,
                1288700.0,
                1072800.0,
                1529000.0,
            ],
        }
    )



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

    def fund_etf_hist_em(**kwargs: object) -> pd.DataFrame:
        raise AssertionError(f"regular stock unexpectedly used fund endpoint: {kwargs}")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=stock_zh_index_daily,
            stock_zh_a_hist=stock_zh_a_hist,
            fund_etf_hist_em=fund_etf_hist_em,
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
    # The A-share stock path still converts provider lots to canonical shares.
    assert result.df.loc[0, "volume"] == 100000.0


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


def test_cn_etf_515180_routes_to_fund_endpoint_with_qfq_and_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fund_etf_hist_em(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        return _fund_etf_frame()

    def stock_zh_a_hist(**kwargs: object) -> pd.DataFrame:
        raise AssertionError(f"ETF 515180 unexpectedly used stock endpoint: {kwargs}")

    def stock_zh_index_daily(*, symbol: str) -> pd.DataFrame:
        raise AssertionError(f"ETF 515180 unexpectedly used index endpoint: {symbol}")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=stock_zh_index_daily,
            stock_zh_a_hist=stock_zh_a_hist,
            fund_etf_hist_em=fund_etf_hist_em,
        ),
    )

    result = AkShareAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="515180",
            market="cn",
            start="2026-11-10",
            end="2026-11-19",
        )
    )

    assert calls == [
        {
            "symbol": "515180",
            "period": "daily",
            "start_date": "20261110",
            "end_date": "20261119",
            "adjust": "qfq",
        }
    ]
    # Provider identity matches the stock path, but the ETF/fund endpoint keeps
    # the governed provider lot basis instead of converting to shares.
    assert result.provider == "akshare"
    assert result.symbol == "515180"
    assert result.provider_symbol == "515180"
    assert result.market == "cn"
    # In-window, ascending, unique session dates only.
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-11-10",
        "2026-11-17",
        "2026-11-18",
        "2026-11-19",
    ]
    assert result.df["date"].is_monotonic_increasing
    assert result.df["date"].is_unique
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
    # Duplicate 2026-11-18 keeps the last row; names map, and the fund path
    # retains provider lots (no lot-to-share conversion).
    cutoff_row = result.df.loc[result.df["date"] == pd.Timestamp("2026-11-19")].iloc[0]
    assert cutoff_row["close"] == 1.373
    assert cutoff_row["open"] == 1.360
    assert cutoff_row["high"] == 1.380
    assert cutoff_row["low"] == 1.350
    assert cutoff_row["volume"] == 1000.0
    assert cutoff_row["amount"] == 1373000.0
    assert result.df["factor"].eq(1.0).all()


@pytest.mark.parametrize("symbol", ["515180", "159915", "161725", "510300", "560010", "588000"])
def test_cn_fund_prefixes_route_to_the_fund_endpoint(
    monkeypatch: pytest.MonkeyPatch, symbol: str
) -> None:
    endpoints: list[str] = []

    def fund_etf_hist_em(**_: object) -> pd.DataFrame:
        endpoints.append("fund")
        return _fund_etf_frame()

    def stock_zh_a_hist(**_: object) -> pd.DataFrame:
        endpoints.append("stock")
        return _fund_etf_frame()

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=lambda **_: pd.DataFrame(),
            stock_zh_a_hist=stock_zh_a_hist,
            fund_etf_hist_em=fund_etf_hist_em,
        ),
    )

    result = AkShareAdapter().fetch_daily_bars(
        FetchRequest(
            symbol=symbol,
            market="cn",
            start="2026-11-10",
            end="2026-11-19",
        )
    )

    assert endpoints == ["fund"]
    assert result.provider_symbol == symbol


def test_cn_etf_rejects_non_positive_ohlc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _fund_etf_frame()
    frame.loc[frame.index[0], "收盘"] = 0.0

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=lambda **_: pd.DataFrame(),
            stock_zh_a_hist=lambda **_: pd.DataFrame(),
            fund_etf_hist_em=lambda **_: frame,
        ),
    )

    with pytest.raises(DataFetchError, match="non-finite or non-positive OHLC"):
        AkShareAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="515180",
                market="cn",
                start="2026-11-10",
                end="2026-11-19",
            )
        )


def test_cn_etf_missing_amount_column_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _fund_etf_frame().drop(columns=["成交额"])

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=lambda **_: pd.DataFrame(),
            stock_zh_a_hist=lambda **_: pd.DataFrame(),
            fund_etf_hist_em=lambda **_: frame,
        ),
    )

    with pytest.raises(DataFetchError, match="fund payload missing columns.*成交额"):
        AkShareAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="515180",
                market="cn",
                start="2026-11-10",
                end="2026-11-19",
            )
        )


def test_cn_etf_empty_payload_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=lambda **_: pd.DataFrame(),
            stock_zh_a_hist=lambda **_: pd.DataFrame(),
            fund_etf_hist_em=lambda **_: pd.DataFrame(),
        ),
    )

    with pytest.raises(DataFetchError, match="empty fund data for 515180"):
        AkShareAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="515180",
                market="cn",
                start="2026-11-10",
                end="2026-11-19",
            )
        )



def _fund_akshare(monkeypatch: pytest.MonkeyPatch, endpoint) -> None:
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_index_daily=lambda **_: pd.DataFrame(),
            stock_zh_a_hist=lambda **_: pd.DataFrame(),
            fund_etf_hist_em=endpoint,
        ),
    )


def _fund_request() -> FetchRequest:
    return FetchRequest(
        symbol="515180",
        market="cn",
        start="2026-11-10",
        end="2026-11-19",
    )


def test_cn_etf_fund_endpoint_retries_transient_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fund_etf_hist_em(**_: object) -> pd.DataFrame:
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise ConnectionResetError("Remote end closed connection without response")
        return _fund_etf_frame()

    _fund_akshare(monkeypatch, fund_etf_hist_em)

    result = AkShareAdapter(fund_retry_policy=NO_DELAY).fetch_daily_bars(_fund_request())

    assert len(calls) == 3
    assert result.provider == "akshare"
    assert result.provenance is not None
    assert result.provenance["retry_attempts"] == 3
    assert result.provenance["retry_outcome"] == "succeeded_after_retry"
    assert len(result.provenance["retry_history"]) == 2
    assert all(
        record["retryable"] is True for record in result.provenance["retry_history"]
    )
    assert result.provenance["retry_policy"]["max_honored_retry_after_seconds"] == 30.0
    assert result.provenance["volume_basis"] == "lots"
    assert result.provenance["amount_basis"] == "CNY"
    assert result.provenance["price_basis"] == "qfq_adjusted"


def test_cn_etf_fund_endpoint_exhausts_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fund_etf_hist_em(**_: object) -> pd.DataFrame:
        calls.append(len(calls) + 1)
        raise ConnectionResetError("Remote end closed connection without response")

    _fund_akshare(monkeypatch, fund_etf_hist_em)

    with pytest.raises(DataFetchError, match=r"after 3 attempt\(s\) \(exhausted\)"):
        AkShareAdapter(fund_retry_policy=NO_DELAY).fetch_daily_bars(_fund_request())
    assert len(calls) == 3


def test_cn_etf_fund_endpoint_does_not_retry_non_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fund_etf_hist_em(**_: object) -> pd.DataFrame:
        calls.append(len(calls) + 1)
        raise KeyError("unexpected provider schema")

    _fund_akshare(monkeypatch, fund_etf_hist_em)

    with pytest.raises(DataFetchError, match=r"after 1 attempt\(s\) \(not_retried\)"):
        AkShareAdapter(fund_retry_policy=NO_DELAY).fetch_daily_bars(_fund_request())
    assert len(calls) == 1


def test_cn_etf_fund_endpoint_honours_retry_after_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fund_etf_hist_em(**_: object) -> pd.DataFrame:
        calls.append(len(calls) + 1)
        raise ProviderRateLimitError("quota window", retry_after_seconds=3600.0)

    _fund_akshare(monkeypatch, fund_etf_hist_em)

    with pytest.raises(DataFetchError, match=r"after 1 attempt\(s\) \(not_retried\)"):
        AkShareAdapter(fund_retry_policy=NO_DELAY).fetch_daily_bars(_fund_request())
    assert len(calls) == 1


def _requests_http_error(status: int, retry_after: str | None) -> Exception:
    class Response:
        status_code = status
        headers = {} if retry_after is None else {"Retry-After": retry_after}

    class HTTPError(Exception):
        response = Response()

    HTTPError.__module__ = "requests.exceptions"
    return HTTPError("synthetic")


def test_fund_transport_error_translation_classifies_http_status() -> None:
    rate_limited = _translate_fund_transport_error(_requests_http_error(429, "12"))
    assert isinstance(rate_limited, ProviderRateLimitError)
    assert rate_limited.retry_after_seconds == 12.0

    unavailable = _translate_fund_transport_error(_requests_http_error(503, None))
    assert isinstance(unavailable, ProviderUnavailableError)

    not_found = _requests_http_error(404, None)
    assert _translate_fund_transport_error(not_found) is not_found

    class ConnectionError(Exception):
        pass

    ConnectionError.__module__ = "requests.exceptions"
    assert isinstance(
        _translate_fund_transport_error(ConnectionError("connection aborted")),
        ProviderUnavailableError,
    )

    class JSONDecodeError(ValueError):
        pass

    JSONDecodeError.__module__ = "requests.exceptions"
    decode_error = JSONDecodeError("not json")
    assert _translate_fund_transport_error(decode_error) is decode_error
