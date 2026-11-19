from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

_INDEX_PROVIDER_SYMBOLS = {
    "000300": "sh000300",
    "399006": "sz399006",
}
# CN exchange-traded funds are not A-share equities. The stock endpoint
# (``stock_zh_a_hist``) does not serve them reliably, so ETF/fund codes route to
# the Eastmoney fund endpoint. Prefixes mirror the governed CN ETF classes:
# 15/16 are Shenzhen ETFs/LOFs, 51/56/58 are Shanghai ETFs (515180 is a 51).
_CN_ETF_PREFIXES = ("15", "16", "51", "56", "58")
_EASTMONEY_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}
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
        raise DataFetchError(f"akshare index payload missing columns for {symbol}: {missing}")

    out = frame[list(required)].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    out = out.loc[out["date"].between(start_ts, end_ts, inclusive="both")].copy()
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable index bars for {symbol}")

    # The selected AKShare index endpoint exposes volume but not turnover
    # amount. Its volume is already an index-specific provider quantity, so it
    # is retained and explicitly separated from equity share volume.
    out["amount"] = np.nan
    out["factor"] = 1.0
    return out[_BAR_COLUMNS]


def _is_cn_etf(symbol: str) -> bool:
    """Return whether ``symbol`` is a CN ETF/fund rather than an A-share stock."""

    return str(symbol or "").strip().upper().startswith(_CN_ETF_PREFIXES)


def _normalize_eastmoney_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str,
    label: str,
) -> pd.DataFrame:
    """Normalize an Eastmoney daily payload with the governed QFQ contract.

    Both the stock and fund endpoints expose the same Chinese schema and report
    volume in lots (手). The canonical Alpha Engine unit is shares and turnover
    is already CNY. Bars are sorted, deduplicated, windowed, and rejected when
    OHLC is non-finite or non-positive; no fill or interpolation is applied.
    """

    if frame is None or frame.empty:
        raise DataFetchError(f"empty {label} data for {symbol}")

    missing = [column for column in _EASTMONEY_COLUMN_MAP if column not in frame.columns]
    if missing:
        raise DataFetchError(
            f"akshare {label} payload missing columns for {symbol}: {missing}"
        )

    out = frame[list(_EASTMONEY_COLUMN_MAP)].rename(columns=_EASTMONEY_COLUMN_MAP).copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    # AKShare/Eastmoney reports volume in lots (手); the canonical unit is shares.
    out["volume"] = out["volume"] * 100.0

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    out = out.loc[out["date"].between(start_ts, end_ts, inclusive="both")].copy()
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable {label} bars for {symbol}")

    prices = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise DataFetchError(
            f"akshare {label} payload contains non-finite or non-positive OHLC "
            f"for {symbol}"
        )

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
            if symbol in _INDEX_PROVIDER_SYMBOLS:
                provider_symbol = _INDEX_PROVIDER_SYMBOLS[symbol]
                frame = ak.stock_zh_index_daily(symbol=provider_symbol)
                out = _normalize_index_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                )
            elif _is_cn_etf(symbol):
                # CN ETFs are not served reliably by the A-share stock endpoint.
                # Route them to the Eastmoney fund endpoint with the same
                # forward-adjusted contract used for stocks.
                frame = ak.fund_etf_hist_em(
                    symbol=symbol,
                    period="daily",
                    start_date=beg,
                    end_date=end,
                    adjust="qfq",
                )
                out = _normalize_eastmoney_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                    label="fund",
                )
            else:
                frame = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=beg,
                    end_date=end,
                    adjust="qfq",
                )
                out = _normalize_eastmoney_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                    label="stock",
                )
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(f"akshare fetch failed for {provider_symbol}: {exc}") from exc

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
            provider_symbol=provider_symbol,
        )
