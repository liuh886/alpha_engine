from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


class DataFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchRequest:
    symbol: str
    market: str
    start: str
    end: str | None = None


@dataclass(frozen=True)
class FetchResult:
    provider: str
    symbol: str
    market: str
    start: str
    end: str | None
    df: pd.DataFrame
    provider_symbol: str | None = None


class MarketDataAdapter(Protocol):
    """
    Minimal adapter interface.

    Return daily bars with columns:
    - date, open, high, low, close, volume, amount, factor
    """

    @property
    def name(self) -> str: ...

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult: ...
