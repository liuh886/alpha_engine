from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd


class DataFetchError(RuntimeError):
    pass


class ProviderTransientError(DataFetchError):
    """Recoverable provider failure: network, timeout or upstream 5xx.

    Only these classes may be retried. Schema, identity, entitlement and
    invalid-data failures deliberately stay outside this hierarchy so a
    fallback or retry cannot mask a data-contract defect.
    """

    error_class = "transient_provider_error"
    retry_after_seconds: float | None = None

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        if retry_after_seconds is not None:
            self.retry_after_seconds = float(retry_after_seconds)


class ProviderRateLimitError(ProviderTransientError):
    """Provider asked the caller to slow down; carries reset evidence."""

    error_class = "rate_limited"


class ProviderTimeoutError(ProviderTransientError):
    """The provider did not answer inside the bounded timeout."""

    error_class = "timeout"


class ProviderUnavailableError(ProviderTransientError):
    """Transport or provider-side 5xx failure that may clear on retry."""

    error_class = "provider_unavailable"


class ProviderContractError(DataFetchError):
    """Schema, identity or adjustment-contract violation; never retried."""

    error_class = "provider_contract_error"


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
    # Optional immutable provider provenance (source URL, exact response hash,
    # fetch timestamp). Publication manifests retain it when present.
    provenance: dict[str, Any] | None = None


class MarketDataAdapter(Protocol):
    """
    Minimal adapter interface.

    Return daily bars with columns:
    - date, open, high, low, close, volume, amount, factor
    """

    @property
    def name(self) -> str: ...

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult: ...
