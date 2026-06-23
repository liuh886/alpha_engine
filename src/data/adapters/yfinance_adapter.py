from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult


def _get_yahoo_ticker(ticker: str, region: str) -> str:
    ticker = str(ticker).upper()
    region = str(region or "").lower().strip()
    if region == "cn":
        if ticker.endswith(".SS") or ticker.endswith(".SZ"):
            return ticker

        # 000300 is CSI300 index (Yahoo uses 000300.SS)
        if ticker == "000300":
            return "000300.SS"

        if ticker.startswith("60") or ticker.startswith("51"):
            return f"{ticker}.SS"
        if ticker.startswith("00") or ticker.startswith("30") or ticker.startswith("15"):
            return f"{ticker}.SZ"
        return f"{ticker}.SS"

    if region == "hk":
        clean = ticker.replace(".HK", "")
        # Yahoo HK tickers are typically 4 digits + .HK (e.g. 0700.HK).
        # Watchlists often use 5-digit zero-padded codes (e.g. 00700.HK).
        if len(clean) == 5 and clean.startswith("0"):
            clean = clean[1:]
        return f"{clean}.HK"

    return ticker


def _process_yfinance_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    # Handle MultiIndex columns (yfinance > 0.2.0)
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass

    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]

    required = ["date", "open", "high", "low", "close", "volume"]
    for c in required:
        if c not in df.columns:
            return pd.DataFrame()

    # Use adj close if present (already adjusted when auto_adjust=True, but keep defensive)
    if "adj close" in df.columns:
        df["close"] = df["adj close"]

    if "amount" not in df.columns:
        df["amount"] = df["close"] * df["volume"]
    df["factor"] = 1.0

    out = df[["date", "open", "high", "low", "close", "volume", "amount", "factor"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out


@dataclass
class YFinanceAdapter:
    _name: str = "yfinance"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        try:
            import yfinance as yf
        except Exception as e:
            raise DataFetchError(f"yfinance import failed: {e}") from e

        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if not market:
            raise DataFetchError("market is required")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")

        yf_ticker = _get_yahoo_ticker(symbol, market)
        try:
            with warnings.catch_warnings():
                # yfinance currently emits Pandas4Warning (Timestamp.utcnow deprecation) very noisily.
                warnings.filterwarnings("ignore", message=".*Timestamp.utcnow is deprecated.*")
                df = yf.download(yf_ticker, start=start, end=req.end, progress=False, auto_adjust=True)
        except Exception as e:
            raise DataFetchError(f"yfinance download failed for {yf_ticker}: {e}") from e

        out = _process_yfinance_df(df)
        if out.empty:
            raise DataFetchError(f"empty data for {yf_ticker}")

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
        )
