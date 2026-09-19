"""Governed listing-lifecycle eligibility for new authoritative runs.

The data plane already honours ``configs/data_quality/symbol_identity_and_lifecycle_v1.yaml``
when it builds governed price history (a terminated symbol's rows stop on its
terminal date). Model selection must honour the same registry: a symbol that has
terminated must not enter a *new* authoritative cross-section on or after its
suspension boundary, while its historical rows remain available for training.

This module is the single shared reader for that boundary so US and CN rankers
cannot drift from the data plane.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

REGISTRY_PATH = Path("configs/data_quality/symbol_identity_and_lifecycle_v1.yaml")
REGISTRY_ID = "symbol_identity_and_lifecycle_v1"


class ListingLifecycleError(ValueError):
    """Raised when the governed listing-lifecycle registry cannot be trusted."""


@dataclass(frozen=True)
class TerminalListing:
    """One governed terminal (delisted / merged-away) listing."""

    symbol: str
    market: str
    terminal_date: str
    suspension_effective_date: str
    reason: str


def _iso_date(value: Any, *, context: str) -> date:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ListingLifecycleError(f"{context} is not an ISO date: {text!r}") from exc


def load_terminal_listings(root: str | Path, *, market: str | None = None) -> dict[str, TerminalListing]:
    """Load governed terminal listings, failing closed on a missing/invalid registry."""

    registry = Path(root) / REGISTRY_PATH
    if not registry.is_file():
        raise ListingLifecycleError(f"listing-lifecycle registry is missing: {REGISTRY_PATH}")
    payload = yaml.safe_load(registry.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("registry_id") != REGISTRY_ID:
        raise ListingLifecycleError("listing-lifecycle registry identity is invalid")
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        raise ListingLifecycleError("listing-lifecycle registry has no rules")
    entries = rules.get("terminal_listings")
    if not isinstance(entries, dict):
        raise ListingLifecycleError("listing-lifecycle registry has no terminal listings")

    market_key = str(market).strip().lower() if market is not None else None
    listings: dict[str, TerminalListing] = {}
    for raw_symbol, entry in entries.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol or not isinstance(entry, dict):
            raise ListingLifecycleError(f"terminal listing entry is invalid: {raw_symbol!r}")
        entry_market = str(entry.get("market", "")).strip().lower()
        if not entry_market:
            raise ListingLifecycleError(f"terminal listing market is missing for {symbol}")
        if entry.get("active_universe_after_terminal_date_allowed") is not False:
            # Not an enforced terminal boundary for new authoritative runs.
            continue
        terminal = _iso_date(entry.get("terminal_date"), context=f"terminal_date for {symbol}")
        suspension_raw = entry.get("suspension_effective_date")
        suspension = (
            _iso_date(suspension_raw, context=f"suspension_effective_date for {symbol}")
            if suspension_raw
            else terminal + timedelta(days=1)
        )
        if suspension <= terminal:
            raise ListingLifecycleError(
                f"suspension boundary for {symbol} must be after its terminal date"
            )
        if market_key is not None and entry_market != market_key:
            continue
        listings[symbol] = TerminalListing(
            symbol=symbol,
            market=entry_market,
            terminal_date=terminal.isoformat(),
            suspension_effective_date=suspension.isoformat(),
            reason=str(entry.get("reason") or entry.get("event_type") or "").strip(),
        )
    return listings


def ineligible_symbols(
    root: str | Path,
    *,
    market: str,
    as_of: str,
    symbols: Iterable[str],
) -> dict[str, TerminalListing]:
    """Return governed terminal listings that must not be selected at ``as_of``.

    A symbol is ineligible when ``as_of`` is on or after its suspension boundary;
    on its terminal date it is still eligible (it traded that session).
    """

    as_of_date = _iso_date(as_of, context="as_of")
    requested = {str(symbol).strip().upper() for symbol in symbols}
    terminal = load_terminal_listings(root, market=market)
    return {
        symbol: listing
        for symbol, listing in terminal.items()
        if symbol in requested
        and as_of_date >= date.fromisoformat(listing.suspension_effective_date)
    }


def eligible_symbols(
    root: str | Path,
    *,
    market: str,
    as_of: str,
    symbols: Iterable[str],
) -> list[str]:
    """Return ``symbols`` in order with governed terminal listings removed."""

    ordered = [str(symbol).strip().upper() for symbol in symbols]
    ineligible = ineligible_symbols(root, market=market, as_of=as_of, symbols=ordered)
    return [symbol for symbol in ordered if symbol not in ineligible]
