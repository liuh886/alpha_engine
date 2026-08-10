from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

TIINGO_API_ROOT = "https://api.tiingo.com"
_BAR_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "cash_distribution",
    "split_factor",
]


class TiingoClient(Protocol):
    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any: ...


class TiingoHttpError(DataFetchError):
    """Structured Tiingo HTTP failure safe to persist in provider evidence."""

    def __init__(
        self,
        *,
        status_code: int,
        path: str,
        attempts: int,
        retry_after_seconds: float | None = None,
        rate_limit_reset: str | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self.path = path
        self.attempts = int(attempts)
        self.retry_after_seconds = retry_after_seconds
        self.rate_limit_reset = rate_limit_reset
        if self.status_code == 429:
            self.error_class = "rate_limited"
        elif self.status_code in {401, 403}:
            self.error_class = "credential_or_entitlement"
        elif self.status_code == 404:
            self.error_class = "provider_symbol_not_found"
        elif self.status_code >= 500:
            self.error_class = "provider_upstream_error"
        else:
            self.error_class = "provider_http_error"
        details = [
            f"Tiingo HTTP {self.status_code} for {path}",
            f"attempts={self.attempts}",
        ]
        if retry_after_seconds is not None:
            details.append(f"retry_after_seconds={retry_after_seconds:g}")
        if rate_limit_reset:
            details.append(f"rate_limit_reset={rate_limit_reset}")
        super().__init__("; ".join(details))


class TiingoRateLimitError(TiingoHttpError):
    """HTTP 429 with reset evidence and bounded retry semantics."""


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
    return parsed if parsed >= 0 else None


def _header_text(headers: Any, *names: str) -> str | None:
    if headers is None:
        return None
    for name in names:
        value = headers.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


@dataclass
class TiingoHttpClient:
    token: str
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_retry_after_seconds: float = 30.0
    api_root: str = TIINGO_API_ROOT

    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        query = urllib.parse.urlencode(params or {})
        url = f"{self.api_root.rstrip('/')}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Token {self.token}",
                "User-Agent": "alpha-engine-research/1.0",
            },
        )
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                last_error = exc
                retry_after = _header_float(exc.headers, "Retry-After")
                rate_limit_reset = _header_text(
                    exc.headers,
                    "X-RateLimit-Reset",
                    "X-Rate-Limit-Reset",
                )
                retryable = exc.code == 429 or 500 <= exc.code < 600
                can_wait = retry_after is not None and retry_after <= self.max_retry_after_seconds
                if retryable and attempt < self.max_attempts:
                    if exc.code == 429 and retry_after is not None and not can_wait:
                        raise TiingoRateLimitError(
                            status_code=exc.code,
                            path=path,
                            attempts=attempt,
                            retry_after_seconds=retry_after,
                            rate_limit_reset=rate_limit_reset,
                        ) from exc
                    time.sleep(
                        retry_after
                        if can_wait and retry_after is not None
                        else min(2 ** (attempt - 1), 4)
                    )
                    continue
                error_type = TiingoRateLimitError if exc.code == 429 else TiingoHttpError
                raise error_type(
                    status_code=exc.code,
                    path=path,
                    attempts=attempt,
                    retry_after_seconds=retry_after,
                    rate_limit_reset=rate_limit_reset,
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                time.sleep(min(2 ** (attempt - 1), 4))
            except json.JSONDecodeError as exc:
                raise DataFetchError(f"Tiingo returned invalid JSON for {path}") from exc
        raise DataFetchError(f"Tiingo request failed for {path}: {last_error}")


def _normalise_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _date_param(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception as exc:
        raise DataFetchError(f"invalid date boundary: {value!r}") from exc


def _metadata_identity(payload: Any, requested_symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DataFetchError(f"Tiingo metadata is invalid for {requested_symbol}")
    ticker = _normalise_symbol(str(payload.get("ticker", "")))
    if ticker != requested_symbol:
        raise DataFetchError(
            "Tiingo identity mismatch: "
            f"requested={requested_symbol}, returned={ticker or 'missing'}"
        )
    return {
        "ticker": ticker,
        "name": str(payload.get("name", "")).strip() or None,
        "exchange_code": str(payload.get("exchangeCode", "")).strip() or None,
        "start_date": str(payload.get("startDate", "")).strip() or None,
        "end_date": str(payload.get("endDate", "")).strip() or None,
        "description": str(payload.get("description", "")).strip() or None,
    }


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _normalise_prices(payload: Any, *, symbol: str) -> pd.DataFrame:
    if not isinstance(payload, list) or not payload:
        raise DataFetchError(f"Tiingo returned no daily prices for {symbol}")
    frame = pd.DataFrame(payload)
    required = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjOpen",
        "adjHigh",
        "adjLow",
        "adjClose",
        "adjVolume",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataFetchError(f"Tiingo payload missing columns for {symbol}: {missing}")

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["date"], errors="coerce", utc=True)
            .dt.tz_convert(None)
            .dt.normalize(),
            "open": frame["adjOpen"],
            "high": frame["adjHigh"],
            "low": frame["adjLow"],
            "close": frame["adjClose"],
            "volume": frame["adjVolume"],
            "raw_open": frame["open"],
            "raw_high": frame["high"],
            "raw_low": frame["low"],
            "raw_close": frame["close"],
            "raw_volume": frame["volume"],
            "cash_distribution": frame.get("divCash", 0.0),
            "split_factor": frame.get("splitFactor", 1.0),
        }
    )
    out = _numeric(
        out,
        (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "raw_volume",
            "cash_distribution",
            "split_factor",
        ),
    )
    if out["split_factor"].isna().any() or (out["split_factor"] <= 0).any():
        raise DataFetchError(f"Tiingo split factors are invalid for {symbol}")
    if out["cash_distribution"].isna().any():
        out["cash_distribution"] = out["cash_distribution"].fillna(0.0)
    raw_close = out["raw_close"].where(out["raw_close"] > 0)
    out["factor"] = out["close"] / raw_close
    if out["factor"].isna().any() or (out["factor"] <= 0).any():
        raise DataFetchError(f"Tiingo adjustment factors are invalid for {symbol}")
    out["amount"] = out["close"] * out["volume"]
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close", "volume"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"Tiingo returned no usable daily prices for {symbol}")

    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(out, symbol)
    if not valid:
        raise DataFetchError(f"Tiingo schema validation failed for {symbol}: {'; '.join(errors)}")
    return out[_BAR_COLUMNS]


@dataclass
class TiingoAdapter:
    token: str | None = None
    client: TiingoClient | None = None
    _name: str = "tiingo"

    def __post_init__(self) -> None:
        resolved = str(self.token or os.getenv("TIINGO_API_TOKEN", "")).strip()
        self.token = resolved or None
        if self.client is None and self.token:
            self.client = TiingoHttpClient(token=self.token)

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
            raise DataFetchError("Tiingo adapter currently supports market=us only")
        if start is None:
            raise DataFetchError("start is required")
        if end is not None and pd.Timestamp(end) < pd.Timestamp(start):
            raise DataFetchError("end must be on or after start")
        if self.client is None:
            raise DataFetchError("Tiingo is unavailable: TIINGO_API_TOKEN is not configured")

        started = time.perf_counter()
        metadata = _metadata_identity(self.client.get_json(f"tiingo/daily/{symbol}"), symbol)
        params = {"startDate": start, "resampleFreq": "daily"}
        if end is not None:
            params["endDate"] = end
        prices = self.client.get_json(f"tiingo/daily/{symbol}/prices", params=params)
        out = _normalise_prices(prices, symbol=symbol)
        if end is not None:
            out = out.loc[out["date"] <= pd.Timestamp(end)].reset_index(drop=True)
        out = out.loc[out["date"] >= pd.Timestamp(start)].reset_index(drop=True)
        if out.empty:
            raise DataFetchError(f"Tiingo has no rows in the request range for {symbol}")
        metadata["request_count"] = 2
        metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        out.attrs["provider_metadata"] = metadata
        out.attrs["price_mode"] = "adjusted_ohlcv_with_raw_audit_fields"
        out.attrs["amount_semantics"] = "synthetic_adjusted_close_times_volume"
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=end,
            df=out,
            provider_symbol=symbol,
        )
