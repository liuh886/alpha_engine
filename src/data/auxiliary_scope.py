"""Governed auxiliary classes for selected-pool provider publication.

The selected-pool provider carries three kinds of symbols beyond the candidate
cross-section: the benchmark, required formal-holding auxiliaries and optional
reference auxiliaries. A required formal holding is part of accepted strategy
evidence and must be materialized. An optional reference is context (a broad
index or volatility index) that must never substitute for a candidate, a
benchmark or a traded holding, and whose absence must not block publication of
the rest.

This module is the single source of truth for that split. Provider refresh,
publication projection, the formal provider cache and market evidence all read
the same classification.
"""

from __future__ import annotations

from collections.abc import Iterable

# Auxiliaries that carry accepted formal holdings. They stay required.
REQUIRED_FORMAL_AUXILIARIES: dict[str, tuple[str, ...]] = {
    # TIGO is the current governed US87 identity. TYGO is a distinct security
    # retained only because accepted US x1.1 history actually traded it; it is
    # published separately rather than being rewritten or substituted as TIGO.
    # QQQI/TQQQ/SGOV are accepted formal sleeves.
    "us": ("QQQI", "TQQQ", "SGOV", "TYGO"),
    # 515180 plus the five CN_27 strategy-specific names outside the selected
    # pool. All are accepted holdings of a formal baseline.
    "cn": ("515180", "002156", "002281", "300274", "601939", "688183"),
}

# Non-executable context references. They may be published when available, but
# their absence is a scoped gap, never a publication blocker, and they are
# never fabricated or replaced by a tracking / volatility ETF.
OPTIONAL_REFERENCE_AUXILIARIES: dict[str, tuple[str, ...]] = {
    # CGDV is a comparison reference; SPX is the real S&P 500 index; VIX is the
    # real CBOE volatility index. None is a formal traded holding.
    "us": ("CGDV", "SPX", "VIX"),
    "cn": (),
}


def _normalize_market(market: object) -> str:
    return str(market or "").strip().lower()


def _normalize_symbol(symbol: object) -> str:
    return str(symbol or "").strip().upper()


def required_formal_auxiliaries(market: object) -> tuple[str, ...]:
    """Return the required formal-holding auxiliaries for one market."""

    return REQUIRED_FORMAL_AUXILIARIES.get(_normalize_market(market), ())


def optional_reference_auxiliaries(market: object) -> tuple[str, ...]:
    """Return the optional reference auxiliaries for one market."""

    return OPTIONAL_REFERENCE_AUXILIARIES.get(_normalize_market(market), ())


def optional_reference_symbols(market: object) -> frozenset[str]:
    """Return the optional reference symbols for one market as a set."""

    return frozenset(optional_reference_auxiliaries(market))


def is_optional_reference_auxiliary(market: object, symbol: object) -> bool:
    """Whether ``symbol`` is a declared optional reference in ``market``."""

    return _normalize_symbol(symbol) in optional_reference_symbols(market)


def is_required_formal_auxiliary(market: object, symbol: object) -> bool:
    """Whether ``symbol`` is a required formal holding in ``market``."""

    return _normalize_symbol(symbol) in {
        _normalize_symbol(value) for value in required_formal_auxiliaries(market)
    }


def classify_auxiliary(market: object, symbol: object) -> str | None:
    """Classify one auxiliary symbol, or return ``None`` when undeclared."""

    if is_required_formal_auxiliary(market, symbol):
        return "required_formal_holding"
    if is_optional_reference_auxiliary(market, symbol):
        return "optional_reference"
    return None


def validate_auxiliary_scope(market: object) -> None:
    """Fail closed when the declared classes overlap or an alias drifts."""

    market_key = _normalize_market(market)
    if market_key not in REQUIRED_FORMAL_AUXILIARIES:
        raise ValueError(f"unsupported auxiliary market: {market_key}")
    required = {_normalize_symbol(value) for value in required_formal_auxiliaries(market_key)}
    optional = {_normalize_symbol(value) for value in optional_reference_auxiliaries(market_key)}
    overlap = sorted(required & optional)
    if overlap:
        raise ValueError(
            f"auxiliary classes overlap for {market_key}: {', '.join(overlap)}"
        )


def all_governed_auxiliaries(market: object) -> tuple[str, ...]:
    """Return required then optional auxiliaries for one market."""

    validate_auxiliary_scope(market)
    market_key = _normalize_market(market)
    return tuple(
        dict.fromkeys(
            (
                *required_formal_auxiliaries(market_key),
                *optional_reference_auxiliaries(market_key),
            )
        )
    )


def partition_optional_references(
    market: object, symbols: Iterable[object]
) -> tuple[list[str], list[str]]:
    """Split symbols into (optional reference, other) without losing identity."""

    optional = optional_reference_symbols(market)
    normalized = [_normalize_symbol(value) for value in symbols if str(value).strip()]
    optional_symbols = [value for value in normalized if value in optional]
    other = [value for value in normalized if value not in optional]
    return optional_symbols, other
