"""Canonical symbol identities for operational market-data ingestion."""

from __future__ import annotations

from collections.abc import Iterable


def normalize_data_symbol(market: str, symbol: object) -> str:
    """Return the stable CSV/provider identity used by data ingestion.

    CN pure-numeric symbols are always represented as six-character strings so
    YAML integer parsing cannot silently remove leading zeroes. Exchange-prefixed
    symbols are preserved in uppercase for compatibility with existing providers.
    """

    market_key = str(market).strip().lower()
    text = str(symbol).strip().upper()
    if not text:
        raise ValueError("market-data symbol must be non-empty")

    if market_key == "cn" and text.isdigit():
        if len(text) > 6:
            raise ValueError(f"CN numeric symbol must have at most six digits: {text}")
        return text.zfill(6)
    return text


def normalize_data_symbols(market: str, symbols: Iterable[object]) -> list[str]:
    """Normalize and de-duplicate symbols without changing first-seen order."""

    result: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = normalize_data_symbol(market, raw)
        if symbol not in seen:
            result.append(symbol)
            seen.add(symbol)
    return result
