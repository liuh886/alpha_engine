from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult


def _to_yyyymmdd(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return value.replace("-", "")


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
        except Exception as e:
            raise DataFetchError(f"akshare import failed: {e}") from e

        beg = _to_yyyymmdd(start)
        end = _to_yyyymmdd(str(req.end)) if req.end else "20500101"
        if not beg:
            raise DataFetchError("invalid start date")

        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=beg, end_date=end, adjust="qfq")
        except Exception as e:
            raise DataFetchError(f"akshare fetch failed for {symbol}: {e}") from e

        if df is None or df.empty:
            raise DataFetchError(f"empty data for {symbol}")

        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        for k in col_map:
            if k not in df.columns:
                raise DataFetchError(f"missing column: {k}")

        out = df[list(col_map.keys())].rename(columns=col_map).copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        for c in ["open", "high", "low", "close", "volume", "amount"]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        out = out.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        if out.empty:
            raise DataFetchError(f"empty usable bars for {symbol}")
        out["factor"] = 1.0

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out[["date", "open", "high", "low", "close", "volume", "amount", "factor"]],
        )

