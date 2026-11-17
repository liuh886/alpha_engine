"""Governed CBOE VIX history adapter.

The CBOE public historical CSV is the governed source for the real VIX index.
It is an index-level series: there is no traded volume or turnover, so this
adapter materializes an explicit zero volume and zero amount rather than
fabricating a traded quantity. Nothing is forward-filled, interpolated or
replaced by a volatility ETF.

The raw response is treated as untrusted until every used row passes strict
date, column, finite/positive and OHLC-envelope checks. Exact response bytes
are hash-bound and provenance is attached to the ``FetchResult`` for the
publication manifest.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

CBOE_VIX_PROVIDER = "cboe_public"
CBOE_VIX_SYMBOL = "VIX"
CBOE_VIX_URL = (
    "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
)
CBOE_VIX_COLUMNS = ("DATE", "OPEN", "HIGH", "LOW", "CLOSE")
CBOE_VIX_SOURCE_SCHEMA = "cboe_vix_history_csv_v1"
CBOE_VIX_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")
CBOE_VIX_VOLUME_BASIS = "not_applicable_index"
CBOE_VIX_AMOUNT_BASIS = "not_applicable_index"
CBOE_VIX_PRICE_BASIS = "index_level_unadjusted"
CBOE_VIX_TERMS_CAVEAT = (
    "CBOE states the historical data is compiled for the convenience of site "
    "visitors and does not guarantee accuracy; the page carries no explicit "
    "redistribution grant. Retain attribution, keep the data local and do not "
    "claim a licence."
)
OHLC_COMPARISON_TOLERANCE = 1e-8
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "alpha-engine-research/1.0 (research-only; CBOE VIX)",
            "Accept": "text/csv,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise DataFetchError(f"CBOE VIX history returned HTTP {status}")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except DataFetchError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DataFetchError(f"CBOE VIX history fetch failed: {exc}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise DataFetchError("CBOE VIX history response exceeds the size limit")
    if not payload:
        raise DataFetchError("CBOE VIX history response is empty")
    return payload


def _decode(payload: bytes | str) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataFetchError("CBOE VIX history is not valid UTF-8") from exc


def _parse_date(value: str) -> tuple[pd.Timestamp, str]:
    text = str(value or "").strip()
    for source_format in CBOE_VIX_DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, source_format)
        except ValueError:
            continue
        return pd.Timestamp(parsed.date()), source_format
    raise DataFetchError(f"CBOE VIX history has an invalid date: {value!r}")


def _parse_price(value: str, field: str, row_number: int) -> float:
    text = str(value or "").strip()
    try:
        number = float(text)
    except ValueError as exc:
        raise DataFetchError(
            f"CBOE VIX history row {row_number} has a non-numeric {field}"
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise DataFetchError(
            f"CBOE VIX history row {row_number} has a non-positive/non-finite {field}"
        )
    return number


def parse_cboe_vix_history(
    payload: bytes | str,
    *,
    start: str,
    end: str | None = None,
) -> pd.DataFrame:
    """Parse and validate the CBOE VIX CSV into canonical daily bars.

    Parsing is strict: exact header columns, one consistent exact date format,
    strictly ascending unique dates, finite positive OHLC and a valid OHLC
    envelope on every row inside the requested window. Rows outside the window
    are never used and are not silently substituted.
    """

    text = _decode(payload)
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise DataFetchError("CBOE VIX history is empty") from exc
    normalized_header = tuple(str(value).strip().upper() for value in header)
    if normalized_header != CBOE_VIX_COLUMNS:
        raise DataFetchError(
            "CBOE VIX history must have exactly DATE,OPEN,HIGH,LOW,CLOSE columns"
        )

    records: list[dict[str, object]] = []
    source_format: str | None = None
    previous_date: pd.Timestamp | None = None
    for row_number, row in enumerate(reader, start=2):
        if not row:
            raise DataFetchError(
                f"CBOE VIX history row {row_number} is blank"
            )
        if len(row) != len(CBOE_VIX_COLUMNS):
            raise DataFetchError(
                f"CBOE VIX history row {row_number} has {len(row)} columns"
            )
        date, row_format = _parse_date(row[0])
        if source_format is None:
            source_format = row_format
        elif row_format != source_format:
            raise DataFetchError(
                f"CBOE VIX history row {row_number} mixes date formats"
            )
        if previous_date is not None:
            if date == previous_date:
                raise DataFetchError(
                    f"CBOE VIX history has a duplicate date: {date.date().isoformat()}"
                )
            if date < previous_date:
                raise DataFetchError(
                    f"CBOE VIX history is not ascending at {date.date().isoformat()}"
                )
        previous_date = date
        open_value = _parse_price(row[1], "open", row_number)
        high = _parse_price(row[2], "high", row_number)
        low = _parse_price(row[3], "low", row_number)
        close = _parse_price(row[4], "close", row_number)
        records.append(
            {
                "date": date,
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
                "source_format": row_format,
            }
        )

    if not records:
        raise DataFetchError("CBOE VIX history has no data rows")

    frame = pd.DataFrame.from_records(records)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    start_at = pd.Timestamp(start).normalize()
    end_at = pd.Timestamp(end).normalize() if end else None
    if end_at is not None and end_at < start_at:
        raise DataFetchError("end must be on or after start")
    mask = frame["date"] >= start_at
    if end_at is not None:
        mask &= frame["date"] <= end_at
    frame = frame.loc[mask].copy()
    if frame.empty:
        raise DataFetchError("CBOE VIX history has no rows in the requested window")

    required_high = frame[["open", "close", "low"]].max(axis=1)
    required_low = frame[["open", "close", "high"]].min(axis=1)
    envelope_ok = (frame["high"] + OHLC_COMPARISON_TOLERANCE >= required_high) & (
        frame["low"] <= required_low + OHLC_COMPARISON_TOLERANCE
    ) & (frame["high"] + OHLC_COMPARISON_TOLERANCE >= frame["low"])
    if not bool(envelope_ok.all()):
        bad_dates = [
            pd.Timestamp(value).date().isoformat()
            for value in frame.loc[~envelope_ok, "date"]
        ]
        raise DataFetchError(
            "CBOE VIX history fails the OHLC envelope on: " + ", ".join(bad_dates[:6])
        )

    frame["volume"] = 0.0
    frame["amount"] = 0.0
    frame["factor"] = 1.0
    output = (
        frame[["date", "open", "high", "low", "close", "volume", "amount", "factor"]]
        .sort_values("date")
        .reset_index(drop=True)
    )
    output.attrs["volume_basis"] = CBOE_VIX_VOLUME_BASIS
    output.attrs["amount_basis"] = CBOE_VIX_AMOUNT_BASIS
    output.attrs["price_basis"] = CBOE_VIX_PRICE_BASIS
    output.attrs["source_date_format"] = source_format

    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(output, CBOE_VIX_SYMBOL)
    if not valid:
        raise DataFetchError(
            "CBOE VIX schema validation failed: " + "; ".join(errors)
        )
    return output


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CboeVixAdapter:
    """CBOE public VIX history adapter (US VIX only)."""

    _name: str = CBOE_VIX_PROVIDER
    fetcher: Callable[[str], bytes] | None = None
    clock: Callable[[], datetime] | None = None

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return CBOE_VIX_SYMBOL

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        market = str(req.market or "").strip().lower()
        symbol = str(req.symbol or "").strip().upper()
        if market != "us" or symbol != CBOE_VIX_SYMBOL:
            raise DataFetchError(
                "cboe_public only serves the real US VIX index; no CN or "
                "substitute instrument is supported"
            )
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")

        fetcher = self.fetcher or _fetch_bytes
        payload = fetcher(CBOE_VIX_URL)
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = payload
        if len(payload_bytes) > MAX_RESPONSE_BYTES:
            raise DataFetchError("CBOE VIX history response exceeds the size limit")
        if not payload_bytes:
            raise DataFetchError("CBOE VIX history response is empty")

        frame = parse_cboe_vix_history(payload_bytes, start=start, end=req.end)
        clock = self.clock or _utc_now
        fetched_at = clock()
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        fetched_at_utc = fetched_at.astimezone(timezone.utc).isoformat()
        provenance = {
            "provider": self.name,
            "provider_symbol": CBOE_VIX_SYMBOL,
            "source_url": CBOE_VIX_URL,
            "response_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "response_bytes": len(payload_bytes),
            "fetched_at_utc": fetched_at_utc,
            "source_schema": CBOE_VIX_SOURCE_SCHEMA,
            "source_date_format": str(frame.attrs.get("source_date_format")),
            "price_basis": CBOE_VIX_PRICE_BASIS,
            "volume_basis": CBOE_VIX_VOLUME_BASIS,
            "amount_basis": CBOE_VIX_AMOUNT_BASIS,
            "requested_start": start,
            "requested_end": req.end,
            "first_date": frame.iloc[0]["date"].date().isoformat(),
            "last_date": frame.iloc[-1]["date"].date().isoformat(),
            "rows": int(len(frame)),
            "terms_caveat": CBOE_VIX_TERMS_CAVEAT,
            "research_only": True,
            "trade_ready": False,
        }
        frame.attrs["provenance"] = provenance
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=frame,
            provider_symbol=CBOE_VIX_SYMBOL,
            provenance=provenance,
        )
