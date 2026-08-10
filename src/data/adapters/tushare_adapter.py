from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

TUSHARE_API_URL = "https://api.tushare.pro"
_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]


class TushareClient(Protocol):
    def query(
        self,
        api_name: str,
        *,
        params: dict[str, Any],
        fields: str,
    ) -> pd.DataFrame: ...


@dataclass
class TushareHttpClient:
    token: str
    timeout_seconds: float = 30.0
    api_url: str = TUSHARE_API_URL

    def query(
        self,
        api_name: str,
        *,
        params: dict[str, Any],
        fields: str,
    ) -> pd.DataFrame:
        payload = json.dumps(
            {
                "api_name": api_name,
                "token": self.token,
                "params": params,
                "fields": fields,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DataFetchError(f"tushare request failed for {api_name}: {exc}") from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DataFetchError(f"tushare returned invalid JSON for {api_name}") from exc
        if not isinstance(result, dict):
            raise DataFetchError(f"tushare returned an invalid payload for {api_name}")
        code = int(result.get("code", -1))
        if code != 0:
            raise DataFetchError(
                f"tushare {api_name} failed: code={code} msg={result.get('msg', '')}"
            )
        data = result.get("data")
        if not isinstance(data, dict):
            raise DataFetchError(f"tushare {api_name} response has no data object")
        columns = data.get("fields")
        items = data.get("items")
        if not isinstance(columns, list) or not isinstance(items, list):
            raise DataFetchError(f"tushare {api_name} response has invalid rows")
        return pd.DataFrame(items, columns=[str(item) for item in columns])


def _to_yyyymmdd(value: str | None) -> str:
    return str(value or "").strip().replace("-", "")


def _to_ts_code(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    if value.endswith((".SH", ".SZ", ".BJ")):
        return value
    if value == "000300":
        return "000300.SH"
    if value.startswith(("60", "68", "51", "50", "52", "56", "58", "90")):
        return f"{value}.SH"
    if value.startswith(("4", "8", "92")):
        return f"{value}.BJ"
    return f"{value}.SZ"


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _normalize_index(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    required = {"trade_date", "open", "high", "low", "close", "vol", "amount"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataFetchError(f"tushare index payload missing columns for {symbol}: {missing}")
    out = frame[list(required)].rename(columns={"trade_date": "date", "vol": "volume"})
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out = _numeric(out, ("open", "high", "low", "close", "volume", "amount"))
    out["volume"] = out["volume"] * 100.0
    out["amount"] = out["amount"] * 1000.0
    out["factor"] = 1.0
    return _finish(out, symbol=symbol)


def _normalize_equity(
    daily: pd.DataFrame,
    factors: pd.DataFrame,
    *,
    symbol: str,
) -> pd.DataFrame:
    required_daily = {
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    }
    required_factor = {"trade_date", "adj_factor"}
    missing_daily = sorted(required_daily.difference(daily.columns))
    missing_factor = sorted(required_factor.difference(factors.columns))
    if missing_daily:
        raise DataFetchError(f"tushare daily payload missing columns for {symbol}: {missing_daily}")
    if missing_factor:
        raise DataFetchError(
            f"tushare adj_factor payload missing columns for {symbol}: {missing_factor}"
        )

    bars = daily[list(required_daily)].copy()
    factor_frame = factors[list(required_factor)].copy()
    bars["trade_date"] = bars["trade_date"].astype(str)
    factor_frame["trade_date"] = factor_frame["trade_date"].astype(str)
    out = bars.merge(factor_frame, on="trade_date", how="left", validate="one_to_one")
    out = out.rename(columns={"trade_date": "date", "vol": "volume", "adj_factor": "factor"})
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out = _numeric(
        out,
        ("open", "high", "low", "close", "volume", "amount", "factor"),
    )
    if out["factor"].isna().any() or (out["factor"] <= 0).any():
        raise DataFetchError(f"tushare adjustment factors are incomplete for {symbol}")
    out = out.sort_values("date").reset_index(drop=True)
    anchor = float(out["factor"].iloc[-1])
    if anchor <= 0:
        raise DataFetchError(f"invalid tushare adjustment anchor for {symbol}")
    out["factor"] = out["factor"] / anchor
    for column in ("open", "high", "low", "close"):
        out[column] = out[column] * out["factor"]
    # Tushare CN daily units are lots and CNY thousands. Canonical Alpha Engine
    # units are shares and CNY.
    out["volume"] = out["volume"] * 100.0
    out["amount"] = out["amount"] * 1000.0
    return _finish(out, symbol=symbol)


def _finish(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    out = frame[_BAR_COLUMNS].copy()
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable tushare bars for {symbol}")
    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(out, symbol)
    if not valid:
        raise DataFetchError(f"tushare schema validation failed for {symbol}: {'; '.join(errors)}")
    return out


@dataclass
class TushareAdapter:
    token: str | None = None
    client: TushareClient | None = None
    _name: str = "tushare"

    def __post_init__(self) -> None:
        resolved = str(self.token or os.getenv("TUSHARE_TOKEN", "")).strip()
        self.token = resolved or None
        if self.client is None and self.token:
            self.client = TushareHttpClient(token=self.token)

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _to_ts_code(req.symbol)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip().upper()
        market = str(req.market or "").strip().lower()
        start = _to_yyyymmdd(req.start)
        end = _to_yyyymmdd(req.end) or "20500101"
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "cn":
            raise DataFetchError("tushare adapter currently supports market=cn only")
        if not start:
            raise DataFetchError("start is required")
        if self.client is None:
            raise DataFetchError("tushare is unavailable: TUSHARE_TOKEN is not configured")

        ts_code = self.provider_symbol(req)
        params = {"ts_code": ts_code, "start_date": start, "end_date": end}
        if symbol == "000300":
            daily = self.client.query(
                "index_daily",
                params=params,
                fields="ts_code,trade_date,open,high,low,close,vol,amount",
            )
            out = _normalize_index(daily, symbol=symbol)
        else:
            daily = self.client.query(
                "daily",
                params=params,
                fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount",
            )
            factors = self.client.query(
                "adj_factor",
                params=params,
                fields="ts_code,trade_date,adj_factor",
            )
            out = _normalize_equity(daily, factors, symbol=symbol)

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=str(req.start),
            end=req.end,
            df=out,
            provider_symbol=ts_code,
        )
