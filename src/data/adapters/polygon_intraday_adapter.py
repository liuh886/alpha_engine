from __future__ import annotations

import os
import time
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
    _metadata,
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


@dataclass(frozen=True)
class PolygonIntradayResult:
    provider: str
    symbol: str
    market: str
    start: str
    end: str
    df: pd.DataFrame
    provider_symbol: str


def _normalise_intraday_payload(
    payload: Any,
    *,
    symbol: str,
    regular_session_only: bool,
    maximum_results: int,
) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise DataFetchError(f"Polygon intraday aggregates are invalid for {symbol}")
    if payload.get("next_url"):
        raise DataFetchError(
            f"Polygon intraday response requires pagination for {symbol}; "
            "truncated evidence is prohibited"
        )
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise DataFetchError(f"Polygon returned no intraday aggregates for {symbol}")
    if len(results) >= maximum_results:
        raise DataFetchError(
            f"Polygon intraday result limit reached for {symbol}; "
            "pagination or truncation cannot be ignored"
        )
    frame = pd.DataFrame(results)
    required = {"t", "o", "h", "l", "c", "v"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataFetchError(
            f"Polygon intraday aggregates missing columns for {symbol}: {missing}"
        )

    timestamp_utc = pd.to_datetime(
        frame["t"], unit="ms", errors="coerce", utc=True
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
    out = (
        out.sort_values("timestamp_utc")
        .drop_duplicates(subset=["timestamp_utc"], keep="last")
        .reset_index(drop=True)
    )
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
            self.client = PolygonHttpClient(api_key=self.api_key)

    @property
    def name(self) -> str:
        return self._name

    def fetch_aggregate_bars(
        self, req: PolygonIntradayRequest
    ) -> PolygonIntradayResult:
        symbol = _normalise_symbol(req.symbol)
        market = str(req.market or "").strip().lower()
        start = _date(req.start, field="start")
        end = _date(req.end, field="end")
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "us":
            raise DataFetchError(
                "Polygon intraday adapter currently supports market=us only"
            )
        if pd.Timestamp(end) < pd.Timestamp(start):
            raise DataFetchError("end must be on or after start")
        if req.multiplier <= 0:
            raise DataFetchError("multiplier must be positive")
        if req.timespan not in {"minute", "hour"}:
            raise DataFetchError("timespan must be minute or hour")
        if req.maximum_results <= 0 or req.maximum_results > 50_000:
            raise DataFetchError("maximum_results must be in [1, 50000]")
        if self.client is None:
            raise DataFetchError(
                "Polygon intraday is unavailable: POLYGON_API_KEY is not configured"
            )

        started = time.perf_counter()
        metadata = _metadata(
            self.client.get_json(f"v3/reference/tickers/{symbol}"), symbol
        )
        payload = self.client.get_json(
            (
                f"v2/aggs/ticker/{symbol}/range/{req.multiplier}/"
                f"{req.timespan}/{start}/{end}"
            ),
            params={
                "adjusted": "true" if req.adjusted else "false",
                "sort": "asc",
                "limit": str(req.maximum_results),
            },
        )
        out = _normalise_intraday_payload(
            payload,
            symbol=symbol,
            regular_session_only=req.regular_session_only,
            maximum_results=req.maximum_results,
        )
        boundary = out["session_date"].between(
            pd.Timestamp(start), pd.Timestamp(end), inclusive="both"
        )
        out = out.loc[boundary].reset_index(drop=True)
        if out.empty:
            raise DataFetchError(
                f"Polygon has no intraday rows in the request range for {symbol}"
            )
        metadata.update(
            {
                "request_count": 2,
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "multiplier": int(req.multiplier),
                "timespan": req.timespan,
                "adjusted": bool(req.adjusted),
                "regular_session_only": bool(req.regular_session_only),
                "timezone": "America/New_York",
                "pagination_present": bool(payload.get("next_url")),
                "results_count": int(len(out)),
            }
        )
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
