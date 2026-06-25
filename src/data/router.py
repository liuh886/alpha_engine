from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult, MarketDataAdapter


@dataclass(frozen=True)
class RouterAttempt:
    provider: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class RouterResponse:
    result: FetchResult | None
    attempts: list[RouterAttempt]

    @property
    def ok(self) -> bool:
        return self.result is not None


class MarketDataRouter:
    """
    A tiny router with fallback across providers.

    Policy is provided as: {market: [provider_name, ...]}.
    """

    def __init__(self, *, adapters: Iterable[MarketDataAdapter], policy: dict | None = None):
        self._adapters = {a.name: a for a in adapters}
        self._policy = policy or {}

    def providers_for_market(self, market: str) -> list[str]:
        market = str(market or "").strip().lower()
        raw = self._policy.get(market)
        if isinstance(raw, list) and raw:
            return [str(x) for x in raw if str(x).strip()]
        # Default: try all adapters in stable order
        return sorted(self._adapters.keys())

    def fetch_daily_bars(
        self, *, symbol: str, market: str, start: str, end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        """Fetch daily bars with optional schema validation fallback.

        When ``validate=True``, each successful response is checked against
        the OHLCV schema.  If validation fails, the router *continues* to
        the next provider instead of returning bad data immediately.
        """
        req = FetchRequest(symbol=symbol, market=market, start=start, end=end)
        attempts: list[RouterAttempt] = []
        for provider in self.providers_for_market(market):
            adapter = self._adapters.get(provider)
            if adapter is None:
                attempts.append(RouterAttempt(provider=provider, ok=False, error="adapter not registered"))
                continue
            try:
                res = adapter.fetch_daily_bars(req)

                # Optional: validate the response before accepting it
                if validate and res.df is not None and not res.df.empty:
                    try:
                        from src.data.validation.schema import validate_market_data
                        ok, _, errs = validate_market_data(res.df, symbol)
                        if not ok:
                            msg = "schema validation failed: " + "; ".join(errs[:2])
                            attempts.append(RouterAttempt(provider=provider, ok=False, error=msg))
                            continue  # try next provider
                    except ImportError:
                        pass  # validation not available — accept as-is

                attempts.append(RouterAttempt(provider=provider, ok=True, error=None))
                return RouterResponse(result=res, attempts=attempts)
            except DataFetchError as e:
                attempts.append(RouterAttempt(provider=provider, ok=False, error=str(e)))
            except Exception as e:
                attempts.append(RouterAttempt(provider=provider, ok=False, error=f"unexpected: {e}"))
        return RouterResponse(result=None, attempts=attempts)

    def fetch_multi_source_bars(self, *, symbol: str, market: str, start: str, end: str | None = None, limit: int = 2) -> dict[str, FetchResult]:
        """
        Fetch from multiple providers (up to limit) even if the first succeeds.
        Used for consistency checks.
        """
        req = FetchRequest(symbol=symbol, market=market, start=start, end=end)
        results = {}
        providers = self.providers_for_market(market)
        
        for provider in providers:
            if len(results) >= limit:
                break
            adapter = self._adapters.get(provider)
            if adapter is None:
                continue
            try:
                res = adapter.fetch_daily_bars(req)
                if res and not res.df.empty:
                    results[provider] = res
            except Exception:
                continue
        return results

