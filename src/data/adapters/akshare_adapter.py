from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

_CSI300_SYMBOL = "000300"
_CSI300_PROVIDER_SYMBOL = "sh000300"
_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]


def _to_yyyymmdd(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return value.replace("-", "")


def _normalize_index_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Normalize unadjusted index OHLCV without inventing turnover amount."""
    required = ("date", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DataFetchError(
            f"akshare index payload missing columns for {symbol}: {missing}"
        )

    out = frame[list(required)].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    out = out.loc[
        out["date"].between(start_ts, end_ts, inclusive="both")
    ].copy()
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable index bars for {symbol}")

    # The selected AkShare index endpoint exposes volume but not turnover amount.
    # Preserve that absence as NaN instead of fabricating close * volume.
    out["amount"] = np.nan
    out["factor"] = 1.0
    return out[_BAR_COLUMNS]


@dataclass
class AkShareAdapter:
    _name: str = "akshare"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if market != "cn":
            raise DataFetchError("akshare adapter currently supports market=cn only")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")

        try:
            import akshare as ak  # type: ignore
        except Exception as exc:
            raise DataFetchError(f"akshare import failed: {exc}") from exc

        beg = _to_yyyymmdd(start)
        end = _to_yyyymmdd(str(req.end)) if req.end else "20500101"
        if not beg:
            raise DataFetchError("invalid start date")

        provider_symbol = symbol
        try:
            if symbol == _CSI300_SYMBOL:
                provider_symbol = _CSI300_PROVIDER_SYMBOL
                frame = ak.stock_zh_index_daily(symbol=provider_symbol)
                out = _normalize_index_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                )
            else:
                frame = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=beg,
                    end_date=end,
                    adjust="qfq",
                )
                if frame is None or frame.empty:
                    raise DataFetchError(f"empty data for {symbol}")

                column_map = {
                    "日期": "date",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                    "成交额": "amount",
                }
                missing = [column for column in column_map if column not in frame.columns]
                if missing:
                    raise DataFetchError(
                        f"akshare stock payload missing columns for {symbol}: {missing}"
                    )

                out = frame[list(column_map)].rename(columns=column_map).copy()
                out["date"] = pd.to_datetime(out["date"], errors="coerce")
                for column in ("open", "high", "low", "close", "volume", "amount"):
                    out[column] = pd.to_numeric(out[column], errors="coerce")
                out = (
                    out.dropna(subset=["date", "open", "high", "low", "close"])
                    .sort_values("date")
                    .drop_duplicates(subset=["date"], keep="last")
                    .reset_index(drop=True)
                )
                if out.empty:
                    raise DataFetchError(f"empty usable bars for {symbol}")
                out["factor"] = 1.0
                out = out[_BAR_COLUMNS]
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(
                f"akshare fetch failed for {provider_symbol}: {exc}"
            ) from exc

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
            provider_symbol=provider_symbol,
        )
