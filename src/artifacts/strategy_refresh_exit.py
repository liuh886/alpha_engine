"""Governed exit-code protocol for formal strategy refresh adapters.

Exit 0 means a refreshed candidate was written. Exit 10
(:data:`DATA_BLOCKED_EXIT_CODE`) means a governed data block: the shared
provider is partial and every symbol this strategy needs-but-lacks is a
declared manifest quarantine. The strategy runner maps exit 10 to
``data_blocked`` (retain, degraded) instead of ``execution_failed`` (fatal
to the whole publish fan-in).

Only quarantine-caused blocks may use this path. :func:`assert_shared_provider_coverage`
pre-checks lifecycle keys against the manifest quarantine set; genuinely
missing symbols (not quarantined) fall through to the adapter's own
fail-closed error and stay fatal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

DATA_BLOCKED_EXIT_CODE = 10

_MANIFEST_RELATIVE = Path("artifacts") / "selected_pool_price_refresh_manifest.json"


class DataBlockedError(ValueError):
    """Raised when quarantined provider symbols block one strategy honestly."""


def _manifest_path(provider_dir: Path) -> Path:
    return provider_dir.resolve().parent.parent.parent / _MANIFEST_RELATIVE


def read_unavailable_symbols(manifest: Mapping[str, Any]) -> frozenset[str]:
    """Return manifest-declared unavailable symbols (upper-cased)."""
    unavailable: set[str] = set()
    for field in (
        "quarantined_symbols",
        "legacy_copied_symbols",
        "unresolved_stale_symbols",
    ):
        values = manifest.get(field)
        if isinstance(values, list):
            unavailable.update(
                str(value).strip().upper() for value in values if str(value).strip()
            )
    return frozenset(unavailable)


def _lifecycle_keys(provider_dir: Path) -> set[str]:
    keys: set[str] = set()
    instruments = provider_dir.resolve() / "instruments"
    if not instruments.is_dir():
        return keys
    for lifecycle_path in sorted(instruments.glob("*.txt")):
        try:
            lines = lifecycle_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if line.strip():
                keys.add(line.split("\t")[0].strip())
    return keys


def _matches(symbol: str, keys: set[str]) -> bool:
    return symbol in keys or symbol.zfill(6) in keys


def assert_shared_provider_coverage(
    provider_dir: Path | str,
    required_symbols: Sequence[str],
    *,
    label: str,
) -> frozenset[str]:
    """Fail with DataBlockedError iff quarantines explain every coverage gap.

    Returns the manifest quarantine set when coverage is complete (so callers
    can bind it into receipts). Silent no-op when the manifest is absent
    (unit-test trees, legacy layouts): downstream fail-closed behavior is
    unchanged.
    """
    provider_path = Path(provider_dir)
    manifest_path = _manifest_path(provider_path)
    if not manifest_path.is_file():
        return frozenset()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(manifest, dict):
        return frozenset()
    unavailable = read_unavailable_symbols(manifest)
    if not unavailable:
        return frozenset()
    keys = _lifecycle_keys(provider_path)
    if not keys:
        return frozenset()
    missing = [symbol for symbol in required_symbols if not _matches(symbol, keys)]
    if not missing:
        return unavailable
    blocked = [
        symbol
        for symbol in missing
        if symbol.upper() in unavailable or symbol.zfill(6).upper() in unavailable
    ]
    if blocked and len(blocked) == len(missing):
        raise DataBlockedError(
            f"{label} blocked by quarantined provider symbols: {sorted(blocked)} "
            "(partial provider; refresh is data_blocked, not failed)"
        )
    return unavailable
