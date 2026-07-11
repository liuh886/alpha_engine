"""Canonical symbol identities for operational market-data ingestion."""

from __future__ import annotations


def infer_data_market(symbol: object) -> str:
    """Infer the operational market from a CSV/provider symbol identity."""

    text = str(symbol).strip().upper()
    if not text:
        raise ValueError("market-data symbol must be non-empty")
    if text.endswith(".HK"):
        return "hk"
    if text.isdigit():
        return "cn"
    return "us"


def normalize_data_symbol(market: str, symbol: object) -> str:
    """Return the stable CSV/provider identity used by data ingestion.

    CN pure-numeric symbols are always represented as six-character strings so
    YAML integer parsing or legacy numeric filenames cannot silently remove
    leading zeroes. Exchange-prefixed symbols are preserved in uppercase.
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
