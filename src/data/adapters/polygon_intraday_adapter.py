from __future__ import annotations

import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.data.adapters.base import DataFetchError
from src.data.adapters.polygon_adapter import (
    PolygonClient,
    PolygonHttpClient,
    _date,
    _normalise_symbol,
)

_INTRADAY_COLUMNS = [
    "timestamp_utc",
    "timestamp_et",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "transactions",
]


@dataclass(frozen=True)
class PolygonIntradayRequest:
    symbol: str
    market: str
    start: str
    end: str
    multiplier: int = 30
    timespan: str = "minute"
    adjusted: bool = True
    regular_session_only: bool = True
    maximum_results: int = 50_000
    max_pages: int = 10
    request_delay_seconds: float = 13.0


@dataclass(frozen=True)
class PolygonIntradayResult:
    provider: str
    symbol: str
    market: str
    start: str
    end: str
    df: pd.DataFrame
    provider_symbol: str


def _validate_payload_identity(payload: Any, symbol: str) -> None:
    if not isinstance(payload, dict):
        raise DataFetchError(f"Polygon intraday aggregates are invalid for {symbol}")
    returned = _normalise_symbol(payload.get("ticker", ""))
    if not returned:
        raise DataFetchError(f"Polygon intraday aggregate identity is missing for {symbol}")
    if returned != symbol:
        raise DataFetchError(
            f"Polygon intraday identity mismatch: requested={symbol}, returned={returned}"
        )


def _next_request(next_url: str) -> tuple[str, dict[str, str]]:
    parsed = urllib.parse.urlparse(str(next_url))
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise DataFetchError("Polygon intraday next_url is invalid")
    path = parsed.path.lstrip("/")
    params = {
        str(key): str(value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if str(key).lower() != "apikey"
    }
    if not path:
        raise DataFetchError("Polygon intraday next_url has no path")
    return path, params


def _collect_payload_results(
    client: PolygonClient,
    *,
    initial_path: str,
    initial_params: dict[str, str],
    symbol: str,
    max_pages: int,
    request_delay_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_pages < 1:
        raise DataFetchError("max_pages must be at least one")
    results: list[dict[str, Any]] = []
    path = initial_path
    params = dict(initial_params)
    pages = 0
    page_counts: list[int] = []
    while True:
        if pages >= max_pages:
            raise DataFetchError(
                f"Polygon intraday pagination exceeded max_pages={max_pages} for {symbol}"
            )
        if pages > 0 and request_delay_seconds > 0.0:
            time.sleep(request_delay_seconds)
        payload = client.get_json(path, params=params)
        _validate_payload_identity(payload, symbol)
        page = payload.get("results")
        if not isinstance(page, list) or not page:
            raise DataFetchError(f"Polygon returned an empty intraday page for {symbol}")
        if not all(isinstance(item, dict) for item in page):
            raise DataFetchError(f"Polygon intraday page contains invalid rows for {symbol}")
        results.extend(page)
        page_counts.append(len(page))
        pages += 1
        next_url = payload.get("next_url")
        if not next_url:
            break
        path, params = _next_request(str(next_url))
    return results, {
        "pages": pages,
        "page_result_counts": page_counts,
        "pagination_completed": True,
        "pagination_used": pages > 1,
        "raw_results_count": len(results),
    }


def _normalise_intraday_results(
    results: list[dict[str, Any]],
    *,
    symbol: str,
    regular_session_only: bool,
) -> pd.DataFrame:
    if not results:
        raise DataFetchError(f"Polygon returned no intraday aggregates for {symbol}")
    frame = pd.DataFrame(results)
    required = {"t", "o", "h", "l", "c", "v"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataFetchError(f"Polygon intraday aggregates missing columns for {symbol}: {missing}")

    timestamp_utc = pd.to_datetime(frame["t"], unit="ms", errors="coerce", utc=True)
    if timestamp_utc.duplicated().any():
        raise DataFetchError(
            f"Polygon intraday pagination produced duplicate timestamps for {symbol}"
        )
    timestamp_et = timestamp_utc.dt.tz_convert(ZoneInfo("America/New_York"))
    out = pd.DataFrame(
        {
            "timestamp_utc": timestamp_utc,
            "timestamp_et": timestamp_et,
            "session_date": timestamp_et.dt.tz_localize(None).dt.normalize(),
            "open": pd.to_numeric(frame["o"], errors="coerce"),
            "high": pd.to_numeric(frame["h"], errors="coerce"),
            "low": pd.to_numeric(frame["l"], errors="coerce"),
            "close": pd.to_numeric(frame["c"], errors="coerce"),
            "volume": pd.to_numeric(frame["v"], errors="coerce"),
            "vwap": pd.to_numeric(frame.get("vw", np.nan), errors="coerce"),
            "transactions": pd.to_numeric(frame.get("n", np.nan), errors="coerce"),
        }
    )
    out = out.dropna(
        subset=[
            "timestamp_utc",
            "timestamp_et",
            "session_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )
    if regular_session_only:
        local_minutes = out["timestamp_et"].dt.hour * 60 + out["timestamp_et"].dt.minute
        out = out.loc[(local_minutes >= 9 * 60 + 30) & (local_minutes < 16 * 60)]
    out = out.sort_values("timestamp_utc").reset_index(drop=True)
    if out.empty:
        raise DataFetchError(f"Polygon returned no usable intraday bars for {symbol}")
    numeric = out[["open", "high", "low", "close", "volume"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise DataFetchError(f"Polygon intraday bars contain non-finite values for {symbol}")
    if not numeric.gt(0.0).all().all():
        raise DataFetchError(f"Polygon intraday bars contain non-positive values for {symbol}")
    if out["timestamp_utc"].duplicated().any():
        raise DataFetchError(f"Polygon intraday bars contain duplicate timestamps for {symbol}")
    return out[_INTRADAY_COLUMNS]


@dataclass
class PolygonIntradayAdapter:
    api_key: str | None = None
    client: PolygonClient | None = None
    _name: str = "polygon_intraday"

    def __post_init__(self) -> None:
        resolved = str(self.api_key or os.getenv("POLYGON_API_KEY", "")).strip()
        self.api_key = resolved or None
        if self.client is None and self.api_key:
            self.client = PolygonHttpClient(
                api_key=self.api_key,
                max_attempts=6,
                max_retry_after_seconds=60.0,
            )

    @property
    def name(self) -> str:
        return self._name

    def fetch_aggregate_bars(self, req: PolygonIntradayRequest) -> PolygonIntradayResult:
        symbol = _normalise_symbol(req.symbol)
        market = str(req.market or "").strip().lower()
        start = _date(req.start, field="start")
        end = _date(req.end, field="end")
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "us":
            raise DataFetchError("Polygon intraday adapter currently supports market=us only")
        if pd.Timestamp(end) < pd.Timestamp(start):
            raise DataFetchError("end must be on or after start")
        if req.multiplier <= 0:
            raise DataFetchError("multiplier must be positive")
        if req.timespan not in {"minute", "hour"}:
            raise DataFetchError("timespan must be minute or hour")
        if req.maximum_results <= 0 or req.maximum_results > 50_000:
            raise DataFetchError("maximum_results must be in [1, 50000]")
        if req.max_pages < 1:
            raise DataFetchError("max_pages must be at least one")
        if req.request_delay_seconds < 0.0:
            raise DataFetchError("request_delay_seconds must be non-negative")
        if self.client is None:
            raise DataFetchError(
                "Polygon intraday is unavailable: POLYGON_API_KEY is not configured"
            )

        started = time.perf_counter()
        path = f"v2/aggs/ticker/{symbol}/range/{req.multiplier}/{req.timespan}/{start}/{end}"
        page_results, pagination = _collect_payload_results(
            self.client,
            initial_path=path,
            initial_params={
                "adjusted": "true" if req.adjusted else "false",
                "sort": "asc",
                "limit": str(req.maximum_results),
            },
            symbol=symbol,
            max_pages=req.max_pages,
            request_delay_seconds=req.request_delay_seconds,
        )
        out = _normalise_intraday_results(
            page_results,
            symbol=symbol,
            regular_session_only=req.regular_session_only,
        )
        boundary = out["session_date"].between(
            pd.Timestamp(start), pd.Timestamp(end), inclusive="both"
        )
        out = out.loc[boundary].reset_index(drop=True)
        if out.empty:
            raise DataFetchError(f"Polygon has no intraday rows in the request range for {symbol}")
        metadata = {
            "ticker": symbol,
            "identity_source": "aggregate_payload_ticker",
            "request_count": int(pagination["pages"]),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "multiplier": int(req.multiplier),
            "timespan": req.timespan,
            "adjusted": bool(req.adjusted),
            "regular_session_only": bool(req.regular_session_only),
            "timezone": "America/New_York",
            "maximum_results_per_page": int(req.maximum_results),
            "max_pages": int(req.max_pages),
            "request_delay_seconds": float(req.request_delay_seconds),
            "results_count": int(len(out)),
            **pagination,
        }
        out.attrs["provider_metadata"] = metadata
        out.attrs["price_mode"] = "adjusted_intraday_aggregates"
        out.attrs["timestamp_semantics"] = "bar_start_utc_and_america_new_york"
        return PolygonIntradayResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=end,
            df=out,
            provider_symbol=symbol,
        )
