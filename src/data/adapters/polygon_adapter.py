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

POLYGON_API_ROOT = "https://api.polygon.io"


class PolygonClient(Protocol):
    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any: ...


class PolygonHttpError(DataFetchError):
    def __init__(
        self,
        *,
        status_code: int,
        path: str,
        attempts: int,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self.path = path
        self.attempts = int(attempts)
        self.retry_after_seconds = retry_after_seconds
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
        message = f"Polygon HTTP {self.status_code} for {path}; attempts={attempts}"
        if retry_after_seconds is not None:
            message += f"; retry_after_seconds={retry_after_seconds:g}"
        super().__init__(message)


@dataclass
class PolygonHttpClient:
    api_key: str
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_retry_after_seconds: float = 30.0
    api_root: str = POLYGON_API_ROOT

    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        query_params = dict(params or {})
        query_params["apiKey"] = self.api_key
        query = urllib.parse.urlencode(query_params)
        url = f"{self.api_root.rstrip('/')}/{path.lstrip('/')}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "alpha-engine-research/1.0",
            },
        )
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = exc
                retry_after: float | None = None
                value = exc.headers.get("Retry-After") if exc.headers else None
                if value is not None:
                    try:
                        retry_after = max(0.0, float(str(value).strip()))
                    except ValueError:
                        retry_after = None
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.max_attempts:
                    if (
                        exc.code == 429
                        and retry_after is not None
                        and retry_after > self.max_retry_after_seconds
                    ):
                        raise PolygonHttpError(
                            status_code=exc.code,
                            path=path,
                            attempts=attempt,
                            retry_after_seconds=retry_after,
                        ) from None
                    time.sleep(
                        retry_after if retry_after is not None else min(2 ** (attempt - 1), 4)
                    )
                    continue
                raise PolygonHttpError(
                    status_code=exc.code,
                    path=path,
                    attempts=attempt,
                    retry_after_seconds=retry_after,
                ) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                time.sleep(min(2 ** (attempt - 1), 4))
            except json.JSONDecodeError as exc:
                raise DataFetchError(f"Polygon returned invalid JSON for {path}") from exc
        error_name = type(last_error).__name__ if last_error is not None else "unknown"
        raise DataFetchError(f"Polygon request failed for {path}: {error_name}")


def _normalise_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _date(value: str | None, *, field: str) -> str:
    if value is None or not str(value).strip():
        raise DataFetchError(f"{field} is required")
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception as exc:
        raise DataFetchError(f"invalid {field}: {value!r}") from exc


def _metadata(payload: Any, requested_symbol: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DataFetchError(f"Polygon metadata is invalid for {requested_symbol}")
    results = payload.get("results")
    if not isinstance(results, dict):
        raise DataFetchError(f"Polygon metadata has no results for {requested_symbol}")
    ticker = _normalise_symbol(results.get("ticker", ""))
    if ticker != requested_symbol:
        raise DataFetchError(
            "Polygon identity mismatch: "
            f"requested={requested_symbol}, returned={ticker or 'missing'}"
        )
    return {
        "ticker": ticker,
        "name": str(results.get("name", "")).strip() or None,
        "market": str(results.get("market", "")).strip() or None,
        "primary_exchange": str(results.get("primary_exchange", "")).strip() or None,
        "type": str(results.get("type", "")).strip() or None,
        "active": results.get("active"),
        "list_date": str(results.get("list_date", "")).strip() or None,
        "composite_figi": str(results.get("composite_figi", "")).strip() or None,
    }


def _bars(payload: Any, *, symbol: str) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise DataFetchError(f"Polygon aggregates are invalid for {symbol}")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise DataFetchError(f"Polygon returned no daily aggregates for {symbol}")
    frame = pd.DataFrame(results)
    required = {"t", "o", "h", "l", "c", "v", "vw"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataFetchError(f"Polygon aggregates missing columns for {symbol}: {missing}")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["t"], unit="ms", errors="coerce", utc=True)
            .dt.tz_convert(None)
            .dt.normalize(),
            "open": pd.to_numeric(frame["o"], errors="coerce"),
            "high": pd.to_numeric(frame["h"], errors="coerce"),
            "low": pd.to_numeric(frame["l"], errors="coerce"),
            "close": pd.to_numeric(frame["c"], errors="coerce"),
            "vwap": pd.to_numeric(frame["vw"], errors="coerce"),
            "volume": pd.to_numeric(frame["v"], errors="coerce"),
        }
    )
    out["amount"] = out["vwap"] * out["volume"]
    out["factor"] = 1.0
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close", "vwap", "volume"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"Polygon returned no usable aggregates for {symbol}")
    if (out[["vwap", "volume"]] <= 0).any().any():
        raise DataFetchError(f"Polygon VWAP and volume must be positive for {symbol}")
    relative_tolerance = out["close"].abs().clip(lower=1.0) * 1e-8
    envelope_distance = pd.concat(
        [(out["low"] - out["vwap"]).clip(lower=0.0), (out["vwap"] - out["high"]).clip(lower=0.0)],
        axis=1,
    ).max(axis=1)
    strict_violations = envelope_distance > relative_tolerance
    # Polygon publishes OHLC at cent precision while reported VWAP may carry
    # finer precision. Half a cent is the maximum nearest-tick discrepancy.
    tolerance = relative_tolerance.clip(lower=0.005)
    outside_envelope = envelope_distance > tolerance
    if outside_envelope.any():
        raise DataFetchError(
            f"Polygon VWAP violates the OHLC envelope for {symbol}: "
            f"sessions={int(outside_envelope.sum())}, "
            f"max_distance={float(envelope_distance[outside_envelope].max()):.8f}"
        )
    out.attrs["rounded_envelope_tolerance_sessions"] = int(strict_violations.sum())
    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(out, symbol)
    if not valid:
        raise DataFetchError(f"Polygon schema validation failed for {symbol}: {'; '.join(errors)}")
    return out[["date", "open", "high", "low", "close", "vwap", "volume", "amount", "factor"]]


@dataclass
class PolygonAdapter:
    api_key: str | None = None
    client: PolygonClient | None = None
    _name: str = "polygon"

    def __post_init__(self) -> None:
        resolved = str(self.api_key or os.getenv("POLYGON_API_KEY", "")).strip()
        self.api_key = resolved or None
        if self.client is None and self.api_key:
            self.client = PolygonHttpClient(api_key=self.api_key)

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _normalise_symbol(req.symbol)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = self.provider_symbol(req)
        market = str(req.market or "").strip().lower()
        start = _date(req.start, field="start")
        end = _date(req.end, field="end")
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "us":
            raise DataFetchError("Polygon adapter currently supports market=us only")
        if pd.Timestamp(end) < pd.Timestamp(start):
            raise DataFetchError("end must be on or after start")
        if self.client is None:
            raise DataFetchError("Polygon is unavailable: POLYGON_API_KEY is not configured")

        started = time.perf_counter()
        metadata = _metadata(self.client.get_json(f"v3/reference/tickers/{symbol}"), symbol)
        payload = self.client.get_json(
            f"v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}",
            params={
                "adjusted": "true",
                "sort": "asc",
                "limit": "50000",
            },
        )
        out = _bars(payload, symbol=symbol)
        out = out.loc[
            out["date"].between(pd.Timestamp(start), pd.Timestamp(end), inclusive="both")
        ].reset_index(drop=True)
        if out.empty:
            raise DataFetchError(f"Polygon has no rows in request range for {symbol}")
        metadata["request_count"] = 2
        metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        out.attrs["provider_metadata"] = metadata
        out.attrs["price_mode"] = "adjusted_daily_aggregates"
        out.attrs["vwap_semantics"] = "reported_vwap"
        out.attrs["amount_semantics"] = "derived_reported_vwap_times_reported_volume"
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=end,
            df=out,
            provider_symbol=symbol,
        )
