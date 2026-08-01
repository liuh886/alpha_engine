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
class EFinanceAdapter:
    _name: str = "efinance"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if market != "cn":
            raise DataFetchError("efinance adapter currently supports market=cn only")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")

        try:
            import efinance as ef  # type: ignore
        except Exception as exc:
            raise DataFetchError(f"efinance import failed: {exc}") from exc

        beg = _to_yyyymmdd(start)
        end = _to_yyyymmdd(str(req.end)) if req.end else "20500101"
        if not beg:
            raise DataFetchError("invalid start date")

        try:
            frame = ef.stock.get_quote_history(
                symbol, beg=beg, end=end, klt=101, fqt=1
            )
        except Exception as exc:
            raise DataFetchError(f"efinance fetch failed for {symbol}: {exc}") from exc

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
            raise DataFetchError(f"efinance payload missing columns: {missing}")

        out = frame[list(column_map)].rename(columns=column_map).copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        for column in ("open", "high", "low", "close", "volume", "amount"):
            out[column] = pd.to_numeric(out[column], errors="coerce")
        # Eastmoney reports A-share historical volume in lots. Alpha Engine's
        # canonical unit is shares. Turnover amount is already CNY.
        out["volume"] = out["volume"] * 100.0
        out = (
            out.dropna(subset=["date", "open", "high", "low", "close"])
            .sort_values("date")
            .drop_duplicates(subset=["date"], keep="last")
            .reset_index(drop=True)
        )
        if out.empty:
            raise DataFetchError(f"empty usable bars for {symbol}")
        out["factor"] = 1.0

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out[
                [
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "factor",
                ]
            ],
            provider_symbol=symbol,
        )
