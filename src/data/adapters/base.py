from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


class DataFetchError(RuntimeError):
    pass


class HistoryStartUnreachable(DataFetchError):
    """The vendor has history but nothing near the requested start.

    Typical cause: the symbol listed after the requested start (IPO), so the
    vendor legitimately cannot reach back. Carries the vendor's actual
    earliest session so the caller can refetch from the listing boundary
    instead of failing over to a worse vendor.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_symbol: str,
        requested_start: str,
        available_start: str | None,
    ) -> None:
        super().__init__(message)
        self.provider_symbol = provider_symbol
        self.requested_start = requested_start
        self.available_start = available_start


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
