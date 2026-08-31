from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult


ALPACA_DATA_ROOT = "https://data.alpaca.markets"


class AlpacaClient(Protocol):
    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any: ...


class AlpacaHttpError(DataFetchError):
    """Structured provider error that is safe to persist in evidence."""

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
        message = f"Alpaca HTTP {self.status_code} for {path}; attempts={attempts}"
        if retry_after_seconds is not None:
            message += f"; retry_after_seconds={retry_after_seconds:g}"
        super().__init__(message)


@dataclass
class AlpacaHttpClient:
    key_id: str
    secret_key: str
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_retry_after_seconds: float = 30.0
    data_root: str = ALPACA_DATA_ROOT

    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        query = urllib.parse.urlencode(dict(params or {}))
        url = f"{self.data_root.rstrip('/')}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "APCA-API-KEY-ID": self.key_id,
                "APCA-API-SECRET-KEY": self.secret_key,
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
                        raise AlpacaHttpError(
                            status_code=exc.code,
                            path=path,
                            attempts=attempt,
                            retry_after_seconds=retry_after,
                        ) from None
                    time.sleep(
                        retry_after if retry_after is not None else min(2 ** (attempt - 1), 4)
                    )
                    continue
                raise AlpacaHttpError(
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
                raise DataFetchError(f"Alpaca returned invalid JSON for {path}") from exc
        error_name = type(last_error).__name__ if last_error is not None else "unknown"
        raise DataFetchError(f"Alpaca request failed for {path}: {error_name}")


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _date(value: str | None, *, field: str) -> str:
    if value is None or not str(value).strip():
        raise DataFetchError(f"{field} is required")
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception as exc:
        raise DataFetchError(f"invalid {field}: {value!r}") from exc


def _page(payload: Any, *, symbol: str) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict):
        raise DataFetchError(f"Alpaca bars response is invalid for {symbol}")
    returned = _normalise_symbol(payload.get("symbol"))
    if returned != symbol:
        raise DataFetchError(
            f"Alpaca identity mismatch: requested={symbol}, returned={returned or 'missing'}"
        )
    rows = payload.get("bars")
    if not isinstance(rows, list):
        raise DataFetchError(f"Alpaca bars response has no rows list for {symbol}")
    if any(not isinstance(row, dict) for row in rows):
        raise DataFetchError(f"Alpaca bars response contains invalid rows for {symbol}")
    token_value = payload.get("next_page_token")
    token = None if token_value in {None, ""} else str(token_value).strip()
    return rows, token or None


def _bars(rows: list[dict[str, Any]], *, symbol: str) -> pd.DataFrame:
    if not rows:
        raise DataFetchError(f"Alpaca returned no daily bars for {symbol}")
    frame = pd.DataFrame(rows)
    required = {"t", "o", "h", "l", "c", "v", "vw"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataFetchError(f"Alpaca bars missing columns for {symbol}: {missing}")
    timestamps = pd.to_datetime(frame["t"], errors="coerce", utc=True)
    out = pd.DataFrame(
        {
            "date": timestamps.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize(),
            "open": pd.to_numeric(frame["o"], errors="coerce"),
            "high": pd.to_numeric(frame["h"], errors="coerce"),
            "low": pd.to_numeric(frame["l"], errors="coerce"),
            "close": pd.to_numeric(frame["c"], errors="coerce"),
            "vwap": pd.to_numeric(frame["vw"], errors="coerce"),
            "volume": pd.to_numeric(frame["v"], errors="coerce"),
        }
    )
    if out.isna().any().any():
        raise DataFetchError(f"Alpaca bars contain missing values for {symbol}")
    numeric = out[["open", "high", "low", "close", "vwap", "volume"]]
    if not numeric.map(lambda value: math.isfinite(float(value))).all().all():
        raise DataFetchError(f"Alpaca bars contain non-finite values for {symbol}")
    if (numeric <= 0).any().any():
        raise DataFetchError(f"Alpaca OHLCV and VWAP must be positive for {symbol}")
    if out["date"].duplicated().any():
        raise DataFetchError(f"Alpaca bars contain duplicate dates for {symbol}")
    out = out.sort_values("date").reset_index(drop=True)
    relative_tolerance = out["close"].abs().clip(lower=1.0) * 1e-8
    envelope_distance = pd.concat(
        [
            (out["low"] - out["vwap"]).clip(lower=0.0),
            (out["vwap"] - out["high"]).clip(lower=0.0),
        ],
        axis=1,
    ).max(axis=1)
    strict_violations = envelope_distance > relative_tolerance
    outside_envelope = envelope_distance > relative_tolerance.clip(lower=0.005)
    if outside_envelope.any():
        first_index = outside_envelope[outside_envelope].index[0]
        first = out.loc[first_index]
        raise DataFetchError(
            f"Alpaca VWAP violates the OHLC envelope for {symbol}: "
            f"sessions={int(outside_envelope.sum())}, "
            f"max_distance={float(envelope_distance[outside_envelope].max()):.8f}, "
            f"first_date={first['date'].date().isoformat()}, "
            f"low={float(first['low']):.8f}, high={float(first['high']):.8f}, "
            f"vwap={float(first['vwap']):.8f}"
        )
    out["amount"] = out["vwap"] * out["volume"]
    out["factor"] = 1.0
    out.attrs["rounded_envelope_tolerance_sessions"] = int(strict_violations.sum())
    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(out, symbol)
    if not valid:
        raise DataFetchError(f"Alpaca schema validation failed for {symbol}: {'; '.join(errors)}")
    return out[
        ["date", "open", "high", "low", "close", "vwap", "volume", "amount", "factor"]
    ]


@dataclass
class AlpacaAdapter:
    key_id: str | None = None
    secret_key: str | None = None
    client: AlpacaClient | None = None
    feed: str = "sip"
    max_pages: int = 10

    def __post_init__(self) -> None:
        self.key_id = str(self.key_id or os.getenv("APCA_API_KEY_ID", "")).strip() or None
        self.secret_key = (
            str(self.secret_key or os.getenv("APCA_API_SECRET_KEY", "")).strip() or None
        )
        self.feed = str(self.feed).strip().lower()
        if self.feed not in {"sip", "otc"}:
            raise DataFetchError("Alpaca historical feed must be sip or otc")
        if self.client is None and self.key_id and self.secret_key:
            self.client = AlpacaHttpClient(key_id=self.key_id, secret_key=self.secret_key)

    @property
    def name(self) -> str:
        return f"alpaca_{self.feed}"

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
            raise DataFetchError("Alpaca adapter currently supports market=us only")
        if pd.Timestamp(end) < pd.Timestamp(start):
            raise DataFetchError("end must be on or after start")
        if self.max_pages < 1:
            raise DataFetchError("max_pages must be at least 1")
        if self.client is None:
            raise DataFetchError(
                "Alpaca is unavailable: APCA_API_KEY_ID and APCA_API_SECRET_KEY are required"
            )

        started = time.perf_counter()
        rows: list[dict[str, Any]] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        request_count = 0
        path = f"v2/stocks/{urllib.parse.quote(symbol, safe='')}/bars"
        for _ in range(self.max_pages):
            params = {
                "timeframe": "1Day",
                "feed": self.feed,
                "adjustment": "all",
                "start": start,
                "end": end,
                "limit": "10000",
                "sort": "asc",
            }
            if page_token is not None:
                params["page_token"] = page_token
            payload = self.client.get_json(path, params=params)
            request_count += 1
            page_rows, next_token = _page(payload, symbol=symbol)
            rows.extend(page_rows)
            if next_token is None:
                break
            if next_token in seen_tokens:
                raise DataFetchError(f"Alpaca repeated a pagination token for {symbol}")
            seen_tokens.add(next_token)
            page_token = next_token
        else:
            raise DataFetchError(f"Alpaca pagination exceeded max_pages={self.max_pages} for {symbol}")

        out = _bars(rows, symbol=symbol)
        out = out.loc[
            out["date"].between(pd.Timestamp(start), pd.Timestamp(end), inclusive="both")
        ].reset_index(drop=True)
        if out.empty:
            raise DataFetchError(f"Alpaca has no rows in request range for {symbol}")
        out.attrs["provider_metadata"] = {
            "symbol": symbol,
            "feed": self.feed,
            "timeframe": "1Day",
            "adjustment": "all",
            "request_count": request_count,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        }
        out.attrs["price_mode"] = f"{self.feed}_adjusted_all_daily_bars"
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
