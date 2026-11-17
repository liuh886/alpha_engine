from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from scripts.data.refresh_selected_pool_prices_v2 import build_hardened_router
from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.cboe_vix_adapter import (
    CBOE_VIX_TERMS_CAVEAT,
    CBOE_VIX_URL,
    CboeVixAdapter,
    parse_cboe_vix_history,
)
from src.data.auxiliary_scope import (
    optional_reference_auxiliaries,
    optional_reference_symbols,
)
from src.data.provider_catalog import provider_capability

VALID_CSV = (
    b"DATE,OPEN,HIGH,LOW,CLOSE\n"
    b"11/12/2026,18.500000,19.800000,18.100000,19.200000\n"
    b"11/13/2026,19.200000,20.100000,18.900000,19.600000\n"
    b"11/16/2026,20.000000,24.520000,19.840000,22.910000\n"
)


def _parse(payload: bytes = VALID_CSV, *, start: str = "2026-11-01", end: str | None = "2026-11-16"):
    return parse_cboe_vix_history(payload, start=start, end=end)


def test_valid_history_is_strict_canonical_and_has_explicit_zero_volume() -> None:
    frame = _parse()

    assert list(frame.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "factor",
    ]
    assert [value.date().isoformat() for value in frame["date"]] == [
        "2026-11-12",
        "2026-11-13",
        "2026-11-16",
    ]
    assert frame["volume"].tolist() == [0.0, 0.0, 0.0]
    assert frame["amount"].tolist() == [0.0, 0.0, 0.0]
    assert frame["factor"].tolist() == [1.0, 1.0, 1.0]
    assert frame.attrs["volume_basis"] == "not_applicable_index"
    assert frame.attrs["amount_basis"] == "not_applicable_index"
    assert frame.attrs["price_basis"] == "index_level_unadjusted"
    assert frame.attrs["source_date_format"] == "%m/%d/%Y"


def test_iso_dates_are_accepted_without_fuzzy_parsing() -> None:
    payload = (
        b"DATE,OPEN,HIGH,LOW,CLOSE\n"
        b"2026-11-12,18.5,19.8,18.1,19.2\n"
        b"2026-11-13,19.2,20.1,18.9,19.6\n"
    )
    frame = parse_cboe_vix_history(payload, start="2026-11-01")
    assert len(frame) == 2
    assert frame.attrs["source_date_format"] == "%Y-%m-%d"


def test_no_forward_fill_or_interpolation() -> None:
    frame = _parse()
    # 2026-11-14 and 2026-11-15 are absent from the source and stay absent.
    assert "2026-11-14" not in {value.date().isoformat() for value in frame["date"]}
    assert "2026-11-15" not in {value.date().isoformat() for value in frame["date"]}


def test_header_must_be_exact() -> None:
    with pytest.raises(DataFetchError, match="exactly DATE,OPEN,HIGH,LOW,CLOSE"):
        _parse(b"DATE,OPEN,HIGH,LOW\n11/12/2026,18.5,19.8,18.1\n")
    with pytest.raises(DataFetchError, match="exactly DATE,OPEN,HIGH,LOW,CLOSE"):
        _parse(b"DATE,OPEN,HIGH,LOW,CLOSE,VOLUME\n11/12/2026,1,2,1,2,0\n")


def test_wrong_column_count_is_rejected() -> None:
    with pytest.raises(DataFetchError, match="has 4 columns"):
        _parse(b"DATE,OPEN,HIGH,LOW,CLOSE\n11/12/2026,18.5,19.8,18.1\n")


def test_invalid_or_mixed_dates_are_rejected() -> None:
    with pytest.raises(DataFetchError, match="invalid date"):
        _parse(b"DATE,OPEN,HIGH,LOW,CLOSE\n13/12/2026,18.5,19.8,18.1,19.2\n")
    with pytest.raises(DataFetchError, match="mixes date formats"):
        _parse(
            b"DATE,OPEN,HIGH,LOW,CLOSE\n"
            b"11/12/2026,18.5,19.8,18.1,19.2\n"
            b"2026-11-13,19.2,20.1,18.9,19.6\n"
        )


def test_duplicate_and_descending_dates_are_rejected() -> None:
    with pytest.raises(DataFetchError, match="duplicate date"):
        _parse(
            b"DATE,OPEN,HIGH,LOW,CLOSE\n"
            b"11/12/2026,18.5,19.8,18.1,19.2\n"
            b"11/12/2026,18.5,19.8,18.1,19.2\n"
        )
    with pytest.raises(DataFetchError, match="not ascending"):
        _parse(
            b"DATE,OPEN,HIGH,LOW,CLOSE\n"
            b"11/13/2026,19.2,20.1,18.9,19.6\n"
            b"11/12/2026,18.5,19.8,18.1,19.2\n"
        )


@pytest.mark.parametrize("value", ("0", "-1", "nan", "inf", ""))
def test_non_positive_or_non_finite_prices_are_rejected(value: str) -> None:
    payload = (
        b"DATE,OPEN,HIGH,LOW,CLOSE\n"
        + f"11/12/2026,{value},19.8,18.1,19.2\n".encode()
    )
    with pytest.raises(DataFetchError, match="non-positive/non-finite|non-numeric"):
        _parse(payload)


def test_ohlc_envelope_is_enforced_on_the_requested_window() -> None:
    payload = (
        b"DATE,OPEN,HIGH,LOW,CLOSE\n"
        b"11/12/2026,18.5,17.8,18.1,19.2\n"
    )
    with pytest.raises(DataFetchError, match="OHLC envelope"):
        _parse(payload, start="2026-11-01", end="2026-11-16")


def test_rows_outside_the_requested_window_are_not_used() -> None:
    payload = (
        b"DATE,OPEN,HIGH,LOW,CLOSE\n"
        b"02/11/1992,19.24,18.57,17.61,17.70\n"
        b"11/12/2026,18.5,19.8,18.1,19.2\n"
    )
    frame = _parse(payload, start="2026-11-01")
    assert [value.date().isoformat() for value in frame["date"]] == ["2026-11-12"]


def test_blank_and_empty_payloads_are_rejected() -> None:
    with pytest.raises(DataFetchError, match="is empty"):
        _parse(b"")
    with pytest.raises(DataFetchError, match="no data rows"):
        _parse(b"DATE,OPEN,HIGH,LOW,CLOSE\n")
    with pytest.raises(DataFetchError, match="no rows in the requested window"):
        _parse(VALID_CSV, start="2027-01-01", end=None)


def test_invalid_utf8_is_rejected() -> None:
    with pytest.raises(DataFetchError, match="not valid UTF-8"):
        _parse(b"DATE,OPEN,HIGH,LOW,CLOSE\n\xff\xfe\n")


def test_adapter_records_exact_provenance_and_response_hash() -> None:
    fetched_at = datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc)
    adapter = CboeVixAdapter(fetcher=lambda url: VALID_CSV, clock=lambda: fetched_at)
    result = adapter.fetch_daily_bars(
        FetchRequest(symbol="VIX", market="us", start="2026-11-01", end="2026-11-16")
    )

    provenance = result.provenance
    assert provenance is not None
    assert provenance["provider"] == "cboe_public"
    assert provenance["provider_symbol"] == "VIX"
    assert provenance["source_url"] == CBOE_VIX_URL
    assert provenance["response_sha256"] == hashlib.sha256(VALID_CSV).hexdigest()
    assert provenance["response_bytes"] == len(VALID_CSV)
    assert provenance["fetched_at_utc"] == fetched_at.isoformat()
    assert provenance["source_schema"] == "cboe_vix_history_csv_v1"
    assert provenance["volume_basis"] == "not_applicable_index"
    assert provenance["terms_caveat"] == CBOE_VIX_TERMS_CAVEAT
    assert provenance["research_only"] is True
    assert provenance["trade_ready"] is False
    assert result.df.attrs["provenance"] == provenance
    assert result.provider_symbol == "VIX"
    assert result.provider == "cboe_public"


def test_adapter_refuses_other_symbols_and_cn_market() -> None:
    adapter = CboeVixAdapter(fetcher=lambda url: VALID_CSV)
    with pytest.raises(DataFetchError, match="only serves the real US VIX index"):
        adapter.fetch_daily_bars(
            FetchRequest(symbol="VXN", market="us", start="2026-11-01")
        )
    with pytest.raises(DataFetchError, match="only serves the real US VIX index"):
        adapter.fetch_daily_bars(
            FetchRequest(symbol="VIX", market="cn", start="2026-11-01")
        )


def test_provider_selection_pins_vix_to_cboe_only() -> None:
    us = build_hardened_router("us")
    assert us.providers_for_request("us", "VIX") == ["cboe_public"]
    assert us.providers_for_request("us", "SPX") == ["yfinance"]
    assert us.providers_for_request("us", "QQQ") == ["yfinance"]
    assert "cboe_public" not in us.providers_for_market("us")

    cn = build_hardened_router("cn")
    assert "cboe_public" not in cn.providers_for_market("cn")
    assert "cboe_public" not in cn.providers_for_request("cn", "VIX")
    assert optional_reference_auxiliaries("cn") == ()
    assert "VIX" not in optional_reference_symbols("cn")


def test_provider_catalog_declares_index_only_semantics_and_terms_caveat() -> None:
    capability = provider_capability("cboe_public")
    assert capability.markets == ("us",)
    assert capability.price_mode == "index_level_unadjusted"
    assert capability.volume_unit == "not_applicable_index"
    assert capability.amount_unit == "not_applicable_index"
    assert capability.corporate_actions is False
    assert "explicit redistribution grant" in capability.usage_note
