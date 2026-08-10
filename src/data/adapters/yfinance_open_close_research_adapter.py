from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult
from src.data.adapters.yfinance_adapter import (
    _clip_to_request,
    _exclusive_provider_end,
    _get_yahoo_ticker,
    _normalise_boundary,
)


@dataclass
class YFinanceOpenCloseResearchAdapter:
    """Narrow research adapter for strategies that consume only open and close.

    Yahoo occasionally publishes adjusted high/low values that violate the OHLC
    envelope by more than the production adapter's machine-scale tolerance. This
    adapter preserves provider-adjusted open, close and volume, then constructs
    envelope-only high/low fields from open and close. It is prohibited for any
    range, ATR, volatility or intraday feature calculation.
    """

    _name: str = "yfinance_open_close_research"

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
        market = str(req.market or "").strip().lower()
        start = str(req.start or "").strip()
        if not symbol or not market or not start:
            raise DataFetchError("symbol, market and start are required")
        start_ts = _normalise_boundary(start, field_name="start")
        end_ts = _normalise_boundary(req.end, field_name="end") if req.end else None
        if end_ts is not None and end_ts < start_ts:
            raise DataFetchError("end must be on or after start")
        provider_symbol = self.provider_symbol(req)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Timestamp.utcnow is deprecated.*")
                raw = yf.download(
                    provider_symbol,
                    start=start,
                    end=_exclusive_provider_end(req.end),
                    progress=False,
                    auto_adjust=True,
                    repair=True,
                    threads=False,
                )
        except Exception as exc:
            raise DataFetchError(f"yfinance download failed for {provider_symbol}: {exc}") from exc
        if raw is None or raw.empty:
            raise DataFetchError(f"empty data for {provider_symbol}")
        frame = raw.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame = frame.reset_index()
        frame.columns = [str(column).lower() for column in frame.columns]
        required = {"date", "open", "close", "volume"}
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise DataFetchError(
                f"Yahoo open-close payload missing columns for {provider_symbol}: {missing}"
            )
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(frame["date"], errors="coerce"),
                "open": pd.to_numeric(frame["open"], errors="coerce"),
                "close": pd.to_numeric(frame["close"], errors="coerce"),
                "volume": pd.to_numeric(frame["volume"], errors="coerce"),
            }
        ).dropna(subset=["date", "open", "close"])
        out["high"] = out[["open", "close"]].max(axis=1)
        out["low"] = out[["open", "close"]].min(axis=1)
        out["amount"] = out["close"] * out["volume"]
        out["factor"] = 1.0
        out = (
            out[["date", "open", "high", "low", "close", "volume", "amount", "factor"]]
            .sort_values("date")
            .reset_index(drop=True)
        )
        out.attrs["open_close_only_research"] = {
            "provider_adjusted_open_close_preserved": True,
            "high_low_synthetic_envelope_only": True,
            "range_features_authorized": False,
            "reason": "Yahoo adjusted OHLC envelope rounding anomaly",
        }
        out = _clip_to_request(out, start=start, end=req.end)
        if out.empty:
            raise DataFetchError(f"empty clipped data for {provider_symbol}")
        from src.data.validation.schema import validate_market_data

        valid, _, errors = validate_market_data(out, symbol)
        if not valid:
            raise DataFetchError(
                f"Yahoo open-close research schema failed for {provider_symbol}: "
                f"{'; '.join(errors)}"
            )
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
            provider_symbol=provider_symbol,
        )
