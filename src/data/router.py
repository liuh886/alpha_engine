from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult, MarketDataAdapter


@dataclass(frozen=True)
class RouterAttempt:
    provider: str
    ok: bool
    provider_symbol: str
    rows: int = 0
    first_date: str | None = None
    last_date: str | None = None
    error: str | None = None
    schema_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_errors"] = list(self.schema_errors)
        return payload


@dataclass(frozen=True)
class RouterResponse:
    result: FetchResult | None
    attempts: list[RouterAttempt]

    @property
    def ok(self) -> bool:
        return self.result is not None


class MarketDataRouter:
    """Route market-data requests through auditable provider fallback.

    Market defaults use ``{market: [provider, ...]}``. A single logical symbol can
    override that order with ``{"market:SYMBOL": [provider, ...]}`` without
    changing the provider preference for the rest of the market.
    """

    def __init__(self, *, adapters: Iterable[MarketDataAdapter], policy: dict | None = None):
        self._adapters = {adapter.name: adapter for adapter in adapters}
        self._policy = policy or {}

    @staticmethod
    def _provider_list(value: object) -> list[str] | None:
        if not isinstance(value, list) or not value:
            return None
        providers = [str(item).strip() for item in value if str(item).strip()]
        return providers or None

    def providers_for_market(self, market: str) -> list[str]:
        market = str(market or "").strip().lower()
        providers = self._provider_list(self._policy.get(market))
        if providers is not None:
            return providers
        return sorted(self._adapters.keys())

    def providers_for_request(self, market: str, symbol: str) -> list[str]:
        normalized_market = str(market or "").strip().lower()
        normalized_symbol = str(symbol or "").strip().upper()
        symbol_key = f"{normalized_market}:{normalized_symbol}"
        providers = self._provider_list(self._policy.get(symbol_key))
        if providers is not None:
            return providers
        return self.providers_for_market(normalized_market)

    @staticmethod
    def _provider_symbol(adapter: MarketDataAdapter, req: FetchRequest) -> str:
        resolver = getattr(adapter, "provider_symbol", None)
        if callable(resolver):
            resolved = str(resolver(req) or "").strip()
            if resolved:
                return resolved
        return str(req.symbol)

    @staticmethod
    def _frame_evidence(frame: pd.DataFrame | None) -> tuple[int, str | None, str | None]:
        if frame is None or frame.empty:
            return 0, None, None
        if "date" not in frame.columns:
            return int(len(frame)), None, None
        dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        if dates.empty:
            return int(len(frame)), None, None
        return (
            int(len(frame)),
            pd.Timestamp(dates.min()).strftime("%Y-%m-%d"),
            pd.Timestamp(dates.max()).strftime("%Y-%m-%d"),
        )

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        """Fetch daily bars with auditable fallback attempts."""

        req = FetchRequest(symbol=symbol, market=market, start=start, end=end)
        attempts: list[RouterAttempt] = []
        for provider in self.providers_for_request(market, symbol):
            adapter = self._adapters.get(provider)
            if adapter is None:
                attempts.append(
                    RouterAttempt(
                        provider=provider,
                        ok=False,
                        provider_symbol=str(symbol),
                        error="adapter not registered",
                    )
                )
                continue

            provider_symbol = self._provider_symbol(adapter, req)
            try:
                result = adapter.fetch_daily_bars(req)
                provider_symbol = str(result.provider_symbol or provider_symbol)
                rows, first_date, last_date = self._frame_evidence(result.df)

                if validate and result.df is not None and not result.df.empty:
                    try:
                        from src.data.validation.schema import validate_market_data

                        ok, _, errors = validate_market_data(result.df, symbol)
                        if not ok:
                            attempts.append(
                                RouterAttempt(
                                    provider=provider,
                                    ok=False,
                                    provider_symbol=provider_symbol,
                                    rows=rows,
                                    first_date=first_date,
                                    last_date=last_date,
                                    error="schema validation failed",
                                    schema_errors=tuple(str(item) for item in errors),
                                )
                            )
                            continue
                    except ImportError:
                        pass

                attempts.append(
                    RouterAttempt(
                        provider=provider,
                        ok=True,
                        provider_symbol=provider_symbol,
                        rows=rows,
                        first_date=first_date,
                        last_date=last_date,
                    )
                )
                return RouterResponse(result=result, attempts=attempts)
            except DataFetchError as exc:
                attempts.append(
                    RouterAttempt(
                        provider=provider,
                        ok=False,
                        provider_symbol=provider_symbol,
                        error=str(exc),
                    )
                )
            except Exception as exc:
                attempts.append(
                    RouterAttempt(
                        provider=provider,
                        ok=False,
                        provider_symbol=provider_symbol,
                        error=f"unexpected: {exc}",
                    )
                )
        return RouterResponse(result=None, attempts=attempts)

    def fetch_multi_source_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        limit: int = 2,
    ) -> dict[str, FetchResult]:
        """Fetch from multiple providers for consistency checks."""

        req = FetchRequest(symbol=symbol, market=market, start=start, end=end)
        results: dict[str, FetchResult] = {}
        for provider in self.providers_for_request(market, symbol):
            if len(results) >= limit:
                break
            adapter = self._adapters.get(provider)
            if adapter is None:
                continue
            try:
                result = adapter.fetch_daily_bars(req)
                if result and not result.df.empty:
                    results[provider] = result
            except Exception:
                continue
        return results
