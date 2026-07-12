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
        if ticker == "000300":
            return "000300.SS"
        if ticker.startswith("60") or ticker.startswith("51"):
            return f"{ticker}.SS"
        if ticker.startswith("00") or ticker.startswith("30") or ticker.startswith("15"):
            return f"{ticker}.SZ"
        return f"{ticker}.SS"

    if region == "hk":
        clean = ticker.replace(".HK", "")
        if len(clean) == 5 and clean.startswith("0"):
            clean = clean[1:]
        return f"{clean}.HK"

    return ticker


def _process_yfinance_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = df.columns.get_level_values(0)
        except Exception:
            pass
    df = df.reset_index()
    df.columns = [str(column).lower() for column in df.columns]
    required = ["date", "open", "high", "low", "close", "volume"]
    for column in required:
        if column not in df.columns:
            return pd.DataFrame()
    if "adj close" in df.columns:
        df["close"] = df["adj close"]
    if "amount" not in df.columns:
        df["amount"] = df["close"] * df["volume"]
    df["factor"] = 1.0
    out = df[["date", "open", "high", "low", "close", "volume", "amount", "factor"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


@dataclass
class YFinanceAdapter:
    _name: str = "yfinance"

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _get_yahoo_ticker(req.symbol, req.market)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        try:
            import yfinance as yf
        except Exception as exc:
            raise DataFetchError(f"yfinance import failed: {exc}") from exc

        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if not market:
            raise DataFetchError("market is required")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")

        yf_ticker = self.provider_symbol(req)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Timestamp.utcnow is deprecated.*")
                df = yf.download(
                    yf_ticker,
                    start=start,
                    end=req.end,
                    progress=False,
                    auto_adjust=True,
                )
        except Exception as exc:
            raise DataFetchError(f"yfinance download failed for {yf_ticker}: {exc}") from exc

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
            provider_symbol=yf_ticker,
        )
