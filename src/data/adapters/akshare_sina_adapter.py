from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]
_INDEX_PROVIDER_SYMBOLS = {"000300": "sh000300"}


def _to_yyyymmdd(value: str | None) -> str:
    return str(value or "").strip().replace("-", "")


def _provider_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    if value.startswith(("sh", "sz", "bj")):
        return value.lower()
    if value in _INDEX_PROVIDER_SYMBOLS:
        return _INDEX_PROVIDER_SYMBOLS[value]
    if value.startswith(("60", "68", "50", "51", "52", "56", "58", "90")):
        return f"sh{value}"
    if value.startswith(("4", "8", "92")):
        return f"bj{value}"
    return f"sz{value}"


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _finish(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    out = frame[_BAR_COLUMNS].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = _numeric(
        out,
        ("open", "high", "low", "close", "volume", "amount", "factor"),
    )
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable Sina bars for {symbol}")

    from src.data.validation.schema import validate_market_data

    valid, _, errors = validate_market_data(out, symbol)
    if not valid:
        raise DataFetchError(f"Sina schema validation failed for {symbol}: {'; '.join(errors)}")
    return out


@dataclass
class AkShareSinaAdapter:
    """Independent Sina daily-bar transport exposed through AKShare.

    AKShare documents the equity endpoint's volume in shares and amount in CNY.
    Calls are deliberately paced because repeated requests may trigger temporary
    source-side IP blocking.
    """

    min_interval_seconds: float = 0.75
    _name: str = "akshare_sina"
    _last_request_at: float = field(default=0.0, init=False, repr=False)

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _provider_symbol(req.symbol)

    def _pace(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip().upper()
        market = str(req.market or "").strip().lower()
        start = _to_yyyymmdd(req.start)
        end = _to_yyyymmdd(req.end) or "20500101"
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "cn":
            raise DataFetchError("AKShare Sina adapter currently supports market=cn only")
        if not start:
            raise DataFetchError("start is required")

        try:
            import akshare as ak  # type: ignore
        except Exception as exc:
            raise DataFetchError(f"akshare import failed: {exc}") from exc

        provider_symbol = self.provider_symbol(req)
        self._pace()
        try:
            if symbol in _INDEX_PROVIDER_SYMBOLS:
                frame = ak.stock_zh_index_daily(symbol=provider_symbol)
                required = ("date", "open", "high", "low", "close", "volume")
                missing = [column for column in required if column not in frame.columns]
                if missing:
                    raise DataFetchError(
                        f"Sina index payload missing columns for {symbol}: {missing}"
                    )
                out = frame[list(required)].copy()
                out["date"] = pd.to_datetime(out["date"], errors="coerce")
                start_ts = pd.Timestamp(start)
                end_ts = pd.Timestamp(end)
                out = out.loc[out["date"].between(start_ts, end_ts, inclusive="both")].copy()
                out["amount"] = np.nan
                out["factor"] = 1.0
            else:
                frame = ak.stock_zh_a_daily(
                    symbol=provider_symbol,
                    start_date=start,
                    end_date=end,
                    adjust="qfq",
                )
                if frame is None or frame.empty:
                    raise DataFetchError(f"empty Sina data for {provider_symbol}")
                required = (
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                )
                missing = [column for column in required if column not in frame.columns]
                if missing:
                    raise DataFetchError(
                        f"Sina equity payload missing columns for {symbol}: {missing}"
                    )
                out = frame[list(required)].copy()
                # The AKShare Sina endpoint already reports equity volume in
                # shares and turnover amount in CNY. Do not apply Eastmoney's
                # lot-to-share conversion here.
                out["factor"] = 1.0
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(f"AKShare Sina fetch failed for {provider_symbol}: {exc}") from exc

        normalized = _finish(out, symbol=symbol)
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=str(req.start),
            end=req.end,
            df=normalized,
            provider_symbol=provider_symbol,
        )
