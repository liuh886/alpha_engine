from __future__ import annotations

from dataclasses import dataclass, field
import urllib.error

import pytest

from src.data.adapters.alpaca_adapter import AlpacaAdapter, AlpacaHttpClient
from src.data.adapters.base import DataFetchError, FetchRequest


def _row(date: str, *, vwap: float = 101.5) -> dict[str, object]:
    return {
        "t": f"{date}T04:00:00Z",
        "o": 100.0,
        "h": 103.0,
        "l": 99.0,
        "c": 102.0,
        "v": 1000.0,
        "vw": vwap,
        "n": 50,
    }


@dataclass
class FakeAlpacaClient:
    returned_symbol: str = "AAPL"
    include_vwap: bool = True
    first_vwap: float = 101.5
    repeated_token: bool = False
    calls: list[dict[str, str]] = field(default_factory=list)

    def get_json(self, path: str, *, params=None):
        values = dict(params or {})
        self.calls.append(values)
        token = values.get("page_token")
        if token is None:
            rows = [_row("2026-07-30", vwap=self.first_vwap)]
            next_token = "page-2"
        else:
            rows = [_row("2026-07-31")]
            next_token = "page-2" if self.repeated_token else None
        if not self.include_vwap:
            for row in rows:
                row.pop("vw")
        return {
            "symbol": self.returned_symbol,
            "bars": rows,
            "next_page_token": next_token,
        }


def _request() -> FetchRequest:
    return FetchRequest(symbol="AAPL", market="us", start="2026-07-30", end="2026-07-31")


def test_alpaca_adapter_paginates_and_normalizes_adjusted_sip_bars() -> None:
    client = FakeAlpacaClient()
    result = AlpacaAdapter(client=client).fetch_daily_bars(_request())

    assert result.provider == "alpaca_sip"
    assert result.provider_symbol == "AAPL"
    assert result.df["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-30",
        "2026-07-31",
    ]
    assert result.df["vwap"].tolist() == pytest.approx([101.5, 101.5])
    assert result.df["amount"].tolist() == pytest.approx([101500.0, 101500.0])
    assert result.df.attrs["provider_metadata"] == {
        "symbol": "AAPL",
        "feed": "sip",
        "timeframe": "1Day",
        "adjustment": "all",
        "request_count": 2,
        "elapsed_seconds": result.df.attrs["provider_metadata"]["elapsed_seconds"],
    }
    assert client.calls[0]["feed"] == "sip"
    assert client.calls[0]["adjustment"] == "all"
    assert client.calls[1]["page_token"] == "page-2"


def test_alpaca_adapter_supports_explicit_otc_feed() -> None:
    client = FakeAlpacaClient(returned_symbol="ABBNY")
    request = FetchRequest(
        symbol="ABBNY", market="us", start="2026-07-30", end="2026-07-31"
    )

    result = AlpacaAdapter(client=client, feed="otc").fetch_daily_bars(request)

    assert result.provider == "alpaca_otc"
    assert client.calls[0]["feed"] == "otc"
    assert result.df.attrs["provider_metadata"]["feed"] == "otc"


def test_alpaca_adapter_rejects_identity_substitution() -> None:
    with pytest.raises(DataFetchError, match="identity mismatch"):
        AlpacaAdapter(client=FakeAlpacaClient(returned_symbol="MSFT")).fetch_daily_bars(
            _request()
        )


def test_alpaca_adapter_rejects_missing_reported_vwap() -> None:
    with pytest.raises(DataFetchError, match="missing columns"):
        AlpacaAdapter(client=FakeAlpacaClient(include_vwap=False)).fetch_daily_bars(_request())


def test_alpaca_adapter_allows_half_tick_rounding_only() -> None:
    accepted = AlpacaAdapter(client=FakeAlpacaClient(first_vwap=98.997)).fetch_daily_bars(
        _request()
    )
    assert accepted.df.attrs["rounded_envelope_tolerance_sessions"] == 1

    with pytest.raises(DataFetchError, match="first_date=2026-07-30"):
        AlpacaAdapter(client=FakeAlpacaClient(first_vwap=98.99)).fetch_daily_bars(_request())


def test_alpaca_adapter_requires_both_credentials(monkeypatch) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(DataFetchError, match="APCA_API_KEY_ID"):
        AlpacaAdapter().fetch_daily_bars(_request())


def test_alpaca_http_errors_do_not_expose_credentials(monkeypatch) -> None:
    key_id = "alpaca-key-id"
    secret = "alpaca-secret-value"

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(DataFetchError) as captured:
        AlpacaHttpClient(key_id=key_id, secret_key=secret, max_attempts=1).get_json(
            "v2/stocks/AAPL/bars"
        )

    assert key_id not in str(captured.value)
    assert secret not in str(captured.value)
    assert captured.value.__suppress_context__ is True


def test_alpaca_adapter_rejects_repeated_page_token() -> None:
    with pytest.raises(DataFetchError, match="repeated a pagination token"):
        AlpacaAdapter(client=FakeAlpacaClient(repeated_token=True)).fetch_daily_bars(_request())


def test_alpaca_adapter_rejects_undeclared_feed() -> None:
    with pytest.raises(DataFetchError, match="must be sip or otc"):
        AlpacaAdapter(client=FakeAlpacaClient(), feed="iex")
