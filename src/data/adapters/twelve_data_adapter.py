"""Twelve Data adjusted daily-bar adapter (internal research use only).

Twelve Data's free tier is personal, non-commercial and prohibits
redistribution. This adapter is therefore wired only where Alpha Engine keeps
its outputs internal (formal refresh strategy job and the QQQ signal job); it is
not part of the public provider rebuild/reseed or the professional price
validation path.

The adapter requests ``adjust=all`` so open/high/low/close are on one
corporate-action-adjusted basis. Twelve Data does not return raw prices
alongside adjusted ones, so ``factor`` is the adjusted identity (1.0) and the
native adjustment method is recorded in provenance instead of being
reconstructed. Nothing is forward-filled, interpolated or partially accepted.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import pandas as pd

from src.data.adapters.base import (
    DataFetchError,
    FetchRequest,
    FetchResult,
    ProviderContractError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

TWELVE_DATA_API_ROOT = "https://api.twelvedata.com"
TWELVE_DATA_PROVIDER = "twelve_data"
TWELVE_DATA_MAX_OUTPUTSIZE = 5000
TWELVE_DATA_SOURCE_SCHEMA = "twelve_data_time_series_v1"
TWELVE_DATA_PRICE_MODE = "adjusted_ohlcv"
TWELVE_DATA_ADJUSTMENT_METHOD = "provider_adjust_all_native"
TWELVE_DATA_VOLUME_BASIS = "provider_adjusted_volume"
TWELVE_DATA_AMOUNT_SEMANTICS = "synthetic_adjusted_close_times_volume"
TWELVE_DATA_USAGE_NOTE = (
    "Free tier is personal, non-commercial and prohibits redistribution. "
    "Internal research use only; it never sets professional_source_ready."
)
OHLC_COMPARISON_TOLERANCE = 1e-8
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]


class TwelveDataClient(Protocol):
    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _header_float(headers: Any, name: str) -> float | None:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except ValueError:
        return None
    return parsed if parsed >= 0.0 else None


@dataclass
class TwelveDataHttpClient:
    """Single-attempt HTTP client; retry/backoff lives in the caller."""

    token: str
    timeout_seconds: float = 30.0
    api_root: str = TWELVE_DATA_API_ROOT

    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        token = str(self.token or "").strip()
        if not token:
            raise DataFetchError(
                "Twelve Data is unavailable: TWELVE_DATA_API_TOKEN is not configured"
            )
        query = dict(params or {})
        query["apikey"] = token
        url = f"{self.api_root.rstrip('/')}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "alpha-engine-research/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            retry_after = _header_float(exc.headers, "Retry-After")
            if exc.code == 429:
                raise ProviderRateLimitError(
                    f"Twelve Data HTTP 429 for {path}",
                    retry_after_seconds=retry_after,
                ) from exc
            if 500 <= int(exc.code) < 600:
                raise ProviderUnavailableError(
                    f"Twelve Data HTTP {exc.code} for {path}",
                    retry_after_seconds=retry_after,
                ) from exc
            raise DataFetchError(f"Twelve Data HTTP {exc.code} for {path}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise ProviderTimeoutError(f"Twelve Data timed out for {path}") from exc
            raise ProviderUnavailableError(f"Twelve Data network failure for {path}: {reason}") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"Twelve Data timed out for {path}") from exc
        except OSError as exc:
            raise ProviderUnavailableError(
                f"Twelve Data transport failure for {path}: {exc}"
            ) from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise DataFetchError("Twelve Data response exceeds the size limit")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderContractError("Twelve Data returned invalid JSON") from exc


def _normalise_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _date_param(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception as exc:
        raise ProviderContractError(f"invalid date boundary: {value!r}") from exc


def _required_outputsize(start: str, end: str | None) -> int:
    end_at = pd.Timestamp(end) if end else pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    start_at = pd.Timestamp(start)
    if end_at < start_at:
        raise ProviderContractError("end must be on or after start")
    sessions = int(len(pd.bdate_range(start_at, end_at)))
    needed = sessions + 10
    if needed > TWELVE_DATA_MAX_OUTPUTSIZE:
        raise DataFetchError(
            "Twelve Data request window exceeds the provider maximum of "
            f"{TWELVE_DATA_MAX_OUTPUTSIZE} daily bars"
        )
    return max(1, needed)


def _api_error(payload: Any, symbol: str) -> None:
    """Translate Twelve Data's 200-with-error payloads into typed failures."""

    if not isinstance(payload, dict):
        raise ProviderContractError(f"Twelve Data payload is invalid for {symbol}")
    code = payload.get("code")
    message = str(payload.get("message", "")).strip()
    status = str(payload.get("status", "")).strip().lower()
    if status != "error" and code is None:
        return
    lowered = message.lower()
    if str(code) == "429" or "rate limit" in lowered or "api credits" in lowered:
        raise ProviderRateLimitError(
            f"Twelve Data rate limited {symbol}: {message or 'rate limit'}"
        )
    if "401" in str(code) or "403" in str(code) or "apikey" in lowered:
        raise DataFetchError(
            f"Twelve Data credential/entitlement failure for {symbol}: {message}"
        )
    if "404" in str(code) or ("symbol" in lowered and ("not found" in lowered or "invalid" in lowered)):
        raise DataFetchError(
            f"Twelve Data symbol is unknown for {symbol}: {message}"
        )
    if str(code).startswith("5"):
        raise ProviderUnavailableError(
            f"Twelve Data upstream error for {symbol}: {message}"
        )
    raise ProviderContractError(
        f"Twelve Data rejected the request for {symbol}: {message or payload}"
    )


def _parse_value(raw: Any, field: str, *, symbol: str, row: int) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ProviderContractError(
            f"Twelve Data row {row} has a non-numeric {field} for {symbol}"
        ) from exc
    if not math.isfinite(value):
        raise ProviderContractError(
            f"Twelve Data row {row} has a non-finite {field} for {symbol}"
        )
    return value


def parse_twelve_data_payload(
    payload: Any,
    *,
    symbol: str,
    start: str,
    end: str | None = None,
) -> pd.DataFrame:
    """Parse strict adjusted daily bars from one Twelve Data response."""

    _api_error(payload, symbol)
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        raise ProviderContractError(f"Twelve Data metadata is missing for {symbol}")
    returned_symbol = _normalise_symbol(str(meta.get("symbol", "")))
    if returned_symbol != symbol:
        raise ProviderContractError(
            "Twelve Data identity mismatch: "
            f"requested={symbol}, returned={returned_symbol or 'missing'}"
        )
    interval = str(meta.get("interval", "")).strip().lower()
    if interval and interval != "1day":
        raise ProviderContractError(
            f"Twelve Data interval mismatch for {symbol}: {interval}"
        )

    values = payload.get("values")
    if not isinstance(values, list) or not values:
        raise DataFetchError(f"Twelve Data returned no daily prices for {symbol}")

    records: list[dict[str, Any]] = []
    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            raise ProviderContractError(
                f"Twelve Data row {index} is not an object for {symbol}"
            )
        required = {"datetime", "open", "high", "low", "close", "volume"}
        missing = sorted(required.difference(item))
        if missing:
            raise ProviderContractError(
                f"Twelve Data row {index} is missing {missing} for {symbol}"
            )
        open_value = _parse_value(item["open"], "open", symbol=symbol, row=index)
        high = _parse_value(item["high"], "high", symbol=symbol, row=index)
        low = _parse_value(item["low"], "low", symbol=symbol, row=index)
        close = _parse_value(item["close"], "close", symbol=symbol, row=index)
        volume = _parse_value(item["volume"], "volume", symbol=symbol, row=index)
        if min(open_value, high, low, close) <= 0.0:
            raise ProviderContractError(
                f"Twelve Data row {index} has a non-positive OHLC for {symbol}"
            )
        if volume < 0.0:
            raise ProviderContractError(
                f"Twelve Data row {index} has negative volume for {symbol}"
            )
        try:
            date = pd.Timestamp(str(item["datetime"]).strip()).normalize()
        except Exception as exc:
            raise ProviderContractError(
                f"Twelve Data row {index} has an invalid date for {symbol}"
            ) from exc
        required_high = max(open_value, close, low)
        required_low = min(open_value, close, high)
        if (
            high + OHLC_COMPARISON_TOLERANCE < required_high
            or low > required_low + OHLC_COMPARISON_TOLERANCE
            or high + OHLC_COMPARISON_TOLERANCE < low
        ):
            raise ProviderContractError(
                "Twelve Data OHLC envelope violation on "
                f"{date.date().isoformat()} for {symbol}"
            )
        records.append(
            {
                "date": date,
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    frame = pd.DataFrame.from_records(records)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].duplicated().any():
        duplicates = sorted(
            {
                pd.Timestamp(value).date().isoformat()
                for value in frame.loc[frame["date"].duplicated(), "date"]
            }
        )
        raise ProviderContractError(
            "Twelve Data returned duplicate dates for "
            f"{symbol}: {', '.join(duplicates[:6])}"
        )
    frame = frame.sort_values("date").reset_index(drop=True)

    start_at = pd.Timestamp(start).normalize()
    end_at = pd.Timestamp(end).normalize() if end else None
    if end_at is not None and end_at < start_at:
        raise ProviderContractError("end must be on or after start")
    mask = frame["date"] >= start_at
    if end_at is not None:
        mask &= frame["date"] <= end_at
    frame = frame.loc[mask].copy().reset_index(drop=True)
    if frame.empty:
        raise DataFetchError(f"Twelve Data has no rows in the request range for {symbol}")

    frame["amount"] = frame["close"] * frame["volume"]
    frame["factor"] = 1.0
    output = frame[_BAR_COLUMNS]

    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(output, symbol)
    if not valid:
        raise ProviderContractError(
            f"Twelve Data schema validation failed for {symbol}: {'; '.join(errors)}"
        )
    return output


@dataclass
class TwelveDataAdapter:
    token: str | None = None
    client: TwelveDataClient | None = None
    clock: Callable[[], datetime] | None = None
    _name: str = TWELVE_DATA_PROVIDER

    def __post_init__(self) -> None:
        resolved = str(self.token or os.getenv("TWELVE_DATA_API_TOKEN", "")).strip()
        self.token = resolved or None
        if self.client is None and self.token:
            self.client = TwelveDataHttpClient(token=self.token)

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _normalise_symbol(req.symbol)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = self.provider_symbol(req)
        market = str(req.market or "").strip().lower()
        start = _date_param(req.start)
        end = _date_param(req.end)
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "us":
            raise DataFetchError("Twelve Data adapter currently supports market=us only")
        if start is None:
            raise DataFetchError("start is required")
        if end is not None and pd.Timestamp(end) < pd.Timestamp(start):
            raise DataFetchError("end must be on or after start")
        if self.client is None:
            raise DataFetchError(
                "Twelve Data is unavailable: TWELVE_DATA_API_TOKEN is not configured"
            )

        params = {
            "symbol": symbol,
            "interval": "1day",
            "outputsize": str(_required_outputsize(start, end)),
            "start_date": start,
            "adjust": "all",
            "format": "JSON",
            "order": "ASC",
        }
        if end is not None:
            params["end_date"] = end
        started = time.perf_counter()
        payload = self.client.get_json("time_series", params=params)
        out = parse_twelve_data_payload(payload, symbol=symbol, start=start, end=end)
        fetched_at = (self.clock or _utc_now)()
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        fetched_at_utc = fetched_at.astimezone(timezone.utc).isoformat()
        response_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        provenance = {
            "provider": self.name,
            "provider_symbol": symbol,
            "source_url": f"{TWELVE_DATA_API_ROOT}/time_series",
            "request": {key: value for key, value in params.items() if key != "apikey"},
            "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "response_bytes": len(response_bytes),
            "fetched_at_utc": fetched_at_utc,
            "source_schema": TWELVE_DATA_SOURCE_SCHEMA,
            "price_mode": TWELVE_DATA_PRICE_MODE,
            "adjustment_method": TWELVE_DATA_ADJUSTMENT_METHOD,
            "volume_basis": TWELVE_DATA_VOLUME_BASIS,
            "amount_semantics": TWELVE_DATA_AMOUNT_SEMANTICS,
            "requested_start": start,
            "requested_end": end,
            "first_date": out.iloc[0]["date"].date().isoformat(),
            "last_date": out.iloc[-1]["date"].date().isoformat(),
            "rows": int(len(out)),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "usage_note": TWELVE_DATA_USAGE_NOTE,
            "research_only": True,
            "trade_ready": False,
        }
        out.attrs["provider_metadata"] = {
            "provider": self.name,
            "provider_symbol": symbol,
            "rows": int(len(out)),
            "elapsed_seconds": provenance["elapsed_seconds"],
            "response_sha256": provenance["response_sha256"],
        }
        out.attrs["price_mode"] = TWELVE_DATA_PRICE_MODE
        out.attrs["adjustment_method"] = TWELVE_DATA_ADJUSTMENT_METHOD
        out.attrs["volume_basis"] = TWELVE_DATA_VOLUME_BASIS
        out.attrs["amount_semantics"] = TWELVE_DATA_AMOUNT_SEMANTICS
        out.attrs["provenance"] = provenance
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=end,
            df=out,
            provider_symbol=symbol,
            provenance=provenance,
        )


__all__ = [
    "TwelveDataAdapter",
    "TwelveDataHttpClient",
    "parse_twelve_data_payload",
]
