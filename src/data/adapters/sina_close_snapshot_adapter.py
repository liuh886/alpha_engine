from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import requests

from src.data.adapters.akshare_sina_adapter import _provider_symbol
from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

_QUOTE_PATTERN = re.compile(r'^var hq_str_[^=]+="(?P<payload>.*)";?$')
_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]


def _raw_overlap(symbol: str, provider_symbol: str, date: str) -> pd.DataFrame:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise DataFetchError(f"akshare import failed: {exc}") from exc

    compact = date.replace("-", "")
    try:
        if symbol == "000300":
            frame = ak.stock_zh_index_daily(symbol=provider_symbol)
            required = ("date", "open", "high", "low", "close", "volume")
            missing = [column for column in required if column not in frame.columns]
            if missing:
                raise DataFetchError(f"Sina index overlap missing columns: {missing}")
            out = frame[list(required)].copy()
            out["date"] = pd.to_datetime(out["date"], errors="coerce")
            out = out.loc[out["date"] == pd.Timestamp(date)].copy()
            out["amount"] = float("nan")
        else:
            frame = ak.stock_zh_a_daily(
                symbol=provider_symbol,
                start_date=compact,
                end_date=compact,
                adjust="",
            )
            required = ("date", "open", "high", "low", "close", "volume", "amount")
            missing = [column for column in required if column not in frame.columns]
            if missing:
                raise DataFetchError(f"Sina equity overlap missing columns: {missing}")
            out = frame[list(required)].copy()
    except DataFetchError:
        raise
    except Exception as exc:
        raise DataFetchError(f"Sina raw overlap failed for {provider_symbol}: {exc}") from exc

    if out is None or len(out) != 1:
        raise DataFetchError(f"Sina raw overlap must contain exactly {date} for {provider_symbol}")
    out["factor"] = 1.0
    return out[_BAR_COLUMNS]


def _closed_quote(provider_symbol: str, cutoff: str) -> tuple[pd.DataFrame, str]:
    url = f"https://hq.sinajs.cn/list={provider_symbol}"
    try:
        response = requests.get(
            url,
            headers={
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": "Mozilla/5.0 alpha-engine-research/1.0",
            },
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        raise DataFetchError(
            f"Sina close quote request failed for {provider_symbol}: {exc}"
        ) from exc
    text = response.content.decode("gbk", errors="replace").strip()
    match = _QUOTE_PATTERN.match(text)
    if not match:
        raise DataFetchError(
            f"invalid Sina close quote envelope for {provider_symbol}: {text[:120]!r}"
        )
    fields = match.group("payload").split(",")
    if len(fields) < 32 or not fields[0]:
        raise DataFetchError(
            f"incomplete Sina close quote for {provider_symbol}: field_count={len(fields)}"
        )
    quote_date = fields[30].strip()
    quote_time = fields[31].strip()
    if quote_date != cutoff or quote_time < "15:00:00":
        raise DataFetchError(
            f"Sina quote is not a completed {cutoff} session for {provider_symbol}: "
            f"date={quote_date} time={quote_time}"
        )
    try:
        row = {
            "date": quote_date,
            "open": float(fields[1]),
            "high": float(fields[4]),
            "low": float(fields[5]),
            "close": float(fields[3]),
            "volume": float(fields[8]),
            "amount": float(fields[9]),
            "factor": 1.0,
        }
    except (TypeError, ValueError, IndexError) as exc:
        raise DataFetchError(f"invalid Sina quote values for {provider_symbol}") from exc
    if min(row["open"], row["high"], row["low"], row["close"]) <= 0:
        raise DataFetchError(
            f"Sina quote has no executable completed bar for {provider_symbol}: {row}"
        )
    if row["high"] < max(row["open"], row["close"]) or row["low"] > min(row["open"], row["close"]):
        raise DataFetchError(f"Sina close quote violates OHLC envelope for {provider_symbol}")
    return pd.DataFrame([row], columns=_BAR_COLUMNS), quote_time


@dataclass
class SinaCloseSnapshotAdapter:
    """Return one raw overlap row plus a fail-closed post-close quote row."""

    _name: str = "sina_close_snapshot"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip().upper()
        market = str(req.market or "").strip().lower()
        overlap = str(req.start or "").strip()
        cutoff = str(req.end or "").strip()
        if not symbol or market != "cn" or not overlap or not cutoff:
            raise DataFetchError("Sina close snapshot requires CN symbol, overlap and cutoff")
        provider_symbol = _provider_symbol(symbol)
        raw = _raw_overlap(symbol, provider_symbol, overlap)
        current, quote_time = _closed_quote(provider_symbol, cutoff)
        out = pd.concat([raw, current], ignore_index=True)
        out.attrs["quote_time"] = quote_time
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=overlap,
            end=cutoff,
            df=out,
            provider_symbol=provider_symbol,
        )
