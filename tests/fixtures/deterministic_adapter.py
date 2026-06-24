"""Deterministic mock data adapter for CI-safe full-flow smoke tests.

Returns synthetic daily bar data for a fixed set of symbols.
No network calls, no external dependencies.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.data.adapters.base import FetchRequest, FetchResult

# Deterministic seed data for 3 CN symbols
_DETERMINISTIC_SYMBOLS = {
    "000001": {"name": "Ping An Bank", "base_price": 12.50},
    "600519": {"name": "Kweichow Moutai", "base_price": 1800.00},
    "000300": {"name": "CSI 300 Index", "base_price": 3800.00},
}


def _generate_daily_bars(symbol: str, start: str, end: str, base_price: float) -> pd.DataFrame:
    """Generate deterministic daily OHLCV data."""
    start_date = datetime.strptime(start, "%Y-%m-%d")
    end_date = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()

    dates = []
    current = start_date
    while current <= end_date:
        # Skip weekends
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)

    if not dates:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "factor"])

    # Deterministic price walk based on symbol hash
    seed = hash(symbol) % 10000
    rows = []
    price = base_price
    for i, date in enumerate(dates):
        # Simple deterministic price movement
        change = ((seed + i * 7) % 100 - 50) / 10000.0
        price = price * (1 + change)

        open_price = round(price * 0.998, 2)
        high_price = round(price * 1.005, 2)
        low_price = round(price * 0.995, 2)
        close_price = round(price, 2)
        volume = int((seed + i * 13) % 1000000 + 100000)
        amount = round(volume * close_price, 2)

        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "amount": amount,
            "factor": 1.0,
        })

    return pd.DataFrame(rows)


class DeterministicAdapter:
    """Mock adapter that returns deterministic data for known symbols."""

    @property
    def name(self) -> str:
        return "deterministic"

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = req.symbol.split(".")[0]  # Strip market suffix
        info = _DETERMINISTIC_SYMBOLS.get(symbol)
        if info is None:
            from src.data.adapters.base import DataFetchError
            raise DataFetchError(f"Unknown symbol: {symbol}")

        df = _generate_daily_bars(symbol, req.start, req.end or "2026-06-20", info["base_price"])
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=df,
        )


class FailingAdapter:
    """Mock adapter that always fails, for testing provider failure diagnostics."""

    def __init__(self, error_msg: str = "Simulated provider failure"):
        self._error_msg = error_msg

    @property
    def name(self) -> str:
        return "failing"

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        from src.data.adapters.base import DataFetchError
        raise DataFetchError(self._error_msg)
