"""Strict provider and universe identity verification.

Enforces:
- Provider identity must match declared expectation
- Universe membership must be exact (no silent symbol drops)
- All missing symbols must be reported, not silently excluded
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderIdentity:
    """Verified provider identity."""
    market: str
    identity_sha256: str
    instrument_count: int
    session_count: int
    first_session: str
    last_session: str

    def matches(self, expected_sha256: str) -> bool:
        return self.identity_sha256 == expected_sha256


@dataclass(frozen=True)
class UniverseMembership:
    """Verified universe membership with no silent drops."""
    universe_id: str
    declared_count: int
    available_count: int
    symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    extra_symbols: tuple[str, ...]

    @property
    def is_exact_match(self) -> bool:
        return len(self.missing_symbols) == 0 and len(self.extra_symbols) == 0

    @property
    def missing_count(self) -> int:
        return len(self.missing_symbols)

    @property
    def extra_count(self) -> int:
        return len(self.extra_symbols)


def load_provider_identity(manifest_path: str | Path) -> ProviderIdentity:
    """Load and verify a provider manifest.

    Raises FileNotFoundError if manifest doesn't exist.
    Raises ValueError if manifest is malformed.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"provider manifest not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["provider_identity_sha256", "market", "instruments", "calendar"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"provider manifest missing fields: {missing}")

    instruments = data["instruments"]
    calendar = data["calendar"]

    return ProviderIdentity(
        market=str(data["market"]),
        identity_sha256=str(data["provider_identity_sha256"]),
        instrument_count=int(instruments.get("count", 0)),
        session_count=int(calendar.get("session_count", 0)),
        first_session=str(calendar.get("first_day", "")),
        last_session=str(calendar.get("last_day", "")),
    )


def verify_universe_membership(
    declared_symbols: list[str],
    available_symbols: set[str],
    universe_id: str = "",
) -> UniverseMembership:
    """Verify exact universe membership — no silent drops.

    Every symbol in the declared universe must be present in the provider.
    Missing symbols are explicitly reported (not silently excluded).

    Returns UniverseMembership with full accounting.
    """
    declared = [str(s) for s in declared_symbols]
    available = {str(s) for s in available_symbols}

    missing = tuple(sorted(s for s in declared if s not in available))
    present = tuple(sorted(s for s in declared if s in available))
    extra = tuple(sorted(s for s in available if s not in declared))

    return UniverseMembership(
        universe_id=universe_id,
        declared_count=len(declared),
        available_count=len(present),
        symbols=present,
        missing_symbols=missing,
        extra_symbols=extra,
    )


def identity_summary(provider: ProviderIdentity, universe: UniverseMembership) -> str:
    """Human-readable summary of provider and universe identity."""
    lines = [
        f"Provider: {provider.market} | identity={provider.identity_sha256[:16]}...",
        f"  instruments={provider.instrument_count} | sessions={provider.session_count}",
        f"  {provider.first_session} → {provider.last_session}",
        f"Universe: {universe.universe_id}",
        f"  declared={universe.declared_count} | available={universe.available_count}",
    ]
    if universe.missing_symbols:
        lines.append(f"  MISSING ({len(universe.missing_symbols)}): {', '.join(universe.missing_symbols[:10])}{'...' if len(universe.missing_symbols) > 10 else ''}")
    if universe.extra_symbols:
        lines.append(f"  extra in provider: {len(universe.extra_symbols)} symbols")
    if universe.is_exact_match:
        lines.append("  ✓ exact match")
    else:
        lines.append(f"  ✗ {universe.missing_count} symbols missing from provider")
    return "\n".join(lines)
