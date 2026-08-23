"""Canonical symbol identities for operational market-data ingestion."""

from __future__ import annotations


SELECTED_POOL_PROVIDER_IDENTITY_CONTRACTS: dict[
    tuple[str, str], dict[str, str]
] = {
    ("us", "TIGO"): {
        "expected_provider_symbol": "TIGO",
        "expected_issuer": "Millicom International Cellular S.A.",
        "forbidden_substitute": "TYGO",
    }
}


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


def selected_pool_provider_identity_contract(
    market: object, symbol: object
) -> dict[str, str] | None:
    """Return the authoritative provider-symbol boundary for a selected symbol."""

    contract = SELECTED_POOL_PROVIDER_IDENTITY_CONTRACTS.get(
        (str(market).strip().lower(), str(symbol).strip().upper())
    )
    return None if contract is None else dict(contract)


def validate_selected_pool_provider_identity(
    *, market: object, symbol: object, provider_symbol: object
) -> dict[str, str] | None:
    """Fail closed on a governed provider-symbol substitution."""

    normalized_symbol = str(symbol).strip().upper()
    contract = selected_pool_provider_identity_contract(market, normalized_symbol)
    if contract is None:
        return None
    observed = str(provider_symbol or normalized_symbol).strip().upper()
    expected = contract["expected_provider_symbol"].upper()
    forbidden = contract["forbidden_substitute"].upper()
    if observed == forbidden:
        raise ValueError(
            f"forbidden identity substitution for {normalized_symbol}: observed={observed}"
        )
    if observed != expected:
        raise ValueError(
            f"provider identity mismatch for {normalized_symbol}: "
            f"expected={expected} observed={observed}"
        )
    return contract
