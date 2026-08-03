from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.sina_close_snapshot_adapter import SinaCloseSnapshotAdapter


class _Response:
    def __init__(self, payload: str) -> None:
        self.content = payload.encode("gbk")

    def raise_for_status(self) -> None:
        return None


def _raw_overlap() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-07-31",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 10000.0,
                "factor": 1.0,
            }
        ]
    )


def _quote(*, quote_date: str = "2026-08-03", quote_time: str = "15:00:03") -> str:
    fields = [""] * 33
    fields[0] = "Fixture"
    fields[1] = "10.60"
    fields[2] = "10.50"
    fields[3] = "10.80"
    fields[4] = "11.10"
    fields[5] = "10.40"
    fields[8] = "1200"
    fields[9] = "12800"
    fields[30] = quote_date
    fields[31] = quote_time
    return f'var hq_str_sz000001="{",".join(fields)}";'


def test_adapter_returns_overlap_and_completed_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.data.adapters.sina_close_snapshot_adapter._raw_overlap",
        lambda *_args, **_kwargs: _raw_overlap(),
    )
    monkeypatch.setattr(
        "src.data.adapters.sina_close_snapshot_adapter.requests.get",
        lambda *_args, **_kwargs: _Response(_quote()),
    )
    result = SinaCloseSnapshotAdapter().fetch_daily_bars(
        FetchRequest(
            symbol="000001",
            market="cn",
            start="2026-07-31",
            end="2026-08-03",
        )
    )
    assert result.provider == "sina_close_snapshot"
    assert result.provider_symbol == "sz000001"
    assert result.df["date"].astype(str).tolist() == ["2026-07-31", "2026-08-03"]
    assert result.df.iloc[-1]["close"] == pytest.approx(10.8)


@pytest.mark.parametrize(
    ("date", "time", "expected"),
    [
        ("2026-08-03", "14:59:59", "not a completed"),
        ("2026-07-31", "15:00:03", "not a completed"),
    ],
)
def test_adapter_rejects_intraday_or_stale_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    date: str,
    time: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        "src.data.adapters.sina_close_snapshot_adapter._raw_overlap",
        lambda *_args, **_kwargs: _raw_overlap(),
    )
    monkeypatch.setattr(
        "src.data.adapters.sina_close_snapshot_adapter.requests.get",
        lambda *_args, **_kwargs: _Response(_quote(quote_date=date, quote_time=time)),
    )
    with pytest.raises(DataFetchError, match=expected):
        SinaCloseSnapshotAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="000001",
                market="cn",
                start="2026-07-31",
                end="2026-08-03",
            )
        )


def test_adapter_rejects_invalid_ohlc(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = _quote().replace(",11.10,10.40,", ",10.70,10.90,")
    monkeypatch.setattr(
        "src.data.adapters.sina_close_snapshot_adapter._raw_overlap",
        lambda *_args, **_kwargs: _raw_overlap(),
    )
    monkeypatch.setattr(
        "src.data.adapters.sina_close_snapshot_adapter.requests.get",
        lambda *_args, **_kwargs: _Response(invalid),
    )
    with pytest.raises(DataFetchError, match="OHLC envelope"):
        SinaCloseSnapshotAdapter().fetch_daily_bars(
            FetchRequest(
                symbol="000001",
                market="cn",
                start="2026-07-31",
                end="2026-08-03",
            )
        )
