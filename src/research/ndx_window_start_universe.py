"""Point-in-time Nasdaq-100 window-start universe contract.

This module provides a deterministic contract for the committed NDX membership
snapshot stored at ``configs/research_universes/ndx_window_start_membership.json``.

Key types
---------
:class:`NdxSnapshotDate`
    One snapshot date with sorted symbols, count, and SHA-256 hash.
:func:`load_snapshot`
    Load the full snapshot from disk — validates schema and hashes.
:func:`validate_snapshot_hash`
    Re-compute and verify the membership hash for one date.
:func:`intersect_with_provider`
    Intersect snapshot symbols with actually-covered provider symbols.
:func:`compute_membership_hash`
    Deterministic SHA-256 of sorted, pipe-joined symbol list.

All functions are **fail-closed**: they raise on missing data, hash mismatch,
or schema violations.  No silent fallback to stale or empty data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Default path to the committed membership snapshot.
DEFAULT_SNAPSHOT_PATH = Path("configs/research_universes/ndx_window_start_membership.json")

# The official Nasdaq endpoint URL template.
SOURCE_URL_TEMPLATE: str = (
    "https://indexes.nasdaqomx.com/Index/WeightingData"
    "?id=NDX&tradeDate={date}T00%3A00%3A00.000&timeOfDay=SOD"
)


# ═══════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class NdxSnapshotDate:
    """One point-in-time NDX membership snapshot."""

    date: str
    """ISO date string (YYYY-MM-DD) for this snapshot."""

    symbols: tuple[str, ...]
    """Sorted, deduplicated NDX constituent tickers for this date."""

    count: int
    """Number of symbols (``len(symbols)``)."""

    sha256_membership_hash: str
    """SHA-256 of the pipe-joined sorted symbol list."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "symbols": list(self.symbols),
            "count": self.count,
            "sha256_membership_hash": self.sha256_membership_hash,
        }


@dataclass(frozen=True)
class NdxWindowStartSnapshot:
    """Full committed NDX window-start membership snapshot."""

    source_url_template: str
    """The Nasdaq endpoint URL template (with ``{date}`` placeholder)."""

    snapshot_dates: tuple[NdxSnapshotDate, ...]
    """One entry per frozen snapshot date."""

    raw: dict[str, Any] = field(repr=False, compare=False)
    """The raw JSON payload (for serialisation round-trips)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.raw.get("schema_version", "1.0"),
            "index": self.raw.get("index", "NDX"),
            "index_name": self.raw.get("index_name", "NASDAQ-100"),
            "source_url_template": self.source_url_template,
            "source_notes": self.raw.get("source_notes"),
            "refresh_command": self.raw.get("refresh_command"),
            "snapshot_dates": [d.to_dict() for d in self.snapshot_dates],
        }


# ═══════════════════════════════════════════════════════════════════════
# Hash computation
# ═══════════════════════════════════════════════════════════════════════


def compute_membership_hash(symbols: list[str]) -> str:
    """Deterministic SHA-256 of sorted, pipe-joined symbol list.

    Parameters
    ----------
    symbols
        List of ticker symbols (will be sorted within this function).

    Returns
    -------
    str
        Lowercase hex SHA-256 digest.
    """
    canonical = "|".join(sorted(symbols)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════


def validate_snapshot_hash(snapshot_date: NdxSnapshotDate) -> bool:
    """Verify that the stored SHA-256 hash matches a recomputation.

    Parameters
    ----------
    snapshot_date
        A snapshot date entry to validate.

    Returns
    -------
    bool
        ``True`` if the hash is valid.

    Raises
    ------
    ValueError
        If the hash does **not** match (fail-closed).
    """
    expected = snapshot_date.sha256_membership_hash
    actual = compute_membership_hash(list(snapshot_date.symbols))
    if expected != actual:
        raise ValueError(
            f"NDX membership hash mismatch for {snapshot_date.date}: "
            f"expected={expected} actual={actual}"
        )
    return True


# ═══════════════════════════════════════════════════════════════════════
# Load
# ═══════════════════════════════════════════════════════════════════════


def load_snapshot(
    path: Path | str = DEFAULT_SNAPSHOT_PATH,
    *,
    validate_hashes: bool = True,
    validate_source: bool = True,
) -> NdxWindowStartSnapshot:
    """Load and validate the committed NDX membership snapshot.

    Parameters
    ----------
    path
        Path to the JSON snapshot file.
    validate_hashes
        When ``True`` (default), recompute and verify every SHA-256 hash.
    validate_source
        When ``True`` (default), verify the source URL template matches the
        expected official Nasdaq endpoint.

    Returns
    -------
    NdxWindowStartSnapshot
        The validated snapshot.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        On schema violations or hash mismatches.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"NDX membership snapshot not found: {p}")

    raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("NDX membership snapshot must be a JSON object")

    # Required top-level fields
    source_url = str(raw.get("source_url_template", ""))
    if validate_source and source_url != SOURCE_URL_TEMPLATE:
        raise ValueError(
            f"NDX source URL template mismatch: expected={SOURCE_URL_TEMPLATE} "
            f"actual={source_url}"
        )

    raw_dates = raw.get("snapshot_dates", [])
    if not isinstance(raw_dates, list) or not raw_dates:
        raise ValueError("NDX membership snapshot must contain at least one snapshot_date")

    snapshot_dates: list[NdxSnapshotDate] = []
    for entry in raw_dates:
        if not isinstance(entry, dict):
            raise ValueError(f"each snapshot_date must be a dict, got {type(entry)}")
        date_str = str(entry.get("date", ""))
        symbols_raw = entry.get("symbols", [])
        if not isinstance(symbols_raw, list):
            raise ValueError(f"symbols must be a list for date {date_str}")
        symbols = tuple(sorted(set(str(s).strip().upper() for s in symbols_raw if s)))
        count = int(entry.get("count", 0))
        if count != len(symbols):
            raise ValueError(
                f"symbol count mismatch for {date_str}: declared={count} actual={len(symbols)}"
            )
        stored_hash = str(entry.get("sha256_membership_hash", ""))
        sd = NdxSnapshotDate(
            date=date_str,
            symbols=symbols,
            count=count,
            sha256_membership_hash=stored_hash,
        )
        if validate_hashes:
            validate_snapshot_hash(sd)
        snapshot_dates.append(sd)

    return NdxWindowStartSnapshot(
        source_url_template=source_url,
        snapshot_dates=tuple(snapshot_dates),
        raw=raw,
    )


def get_snapshot_by_date(
    snapshot: NdxWindowStartSnapshot,
    date: str,
) -> NdxSnapshotDate:
    """Retrieve a single snapshot entry by ISO date string.

    Parameters
    ----------
    snapshot
        The full snapshot container.
    date
        ISO date string (YYYY-MM-DD) to look up.

    Returns
    -------
    NdxSnapshotDate
        The matching entry.

    Raises
    ------
    KeyError
        If *date* is not found among the snapshot dates.
    """
    for entry in snapshot.snapshot_dates:
        if entry.date == date:
            return entry
    raise KeyError(
        f"date {date} not found in NDX membership snapshot "
        f"(available: {sorted(d.date for d in snapshot.snapshot_dates)})"
    )


# ═══════════════════════════════════════════════════════════════════════
# Provider intersection
# ═══════════════════════════════════════════════════════════════════════


def intersect_with_provider(
    snapshot_date: NdxSnapshotDate,
    provider_symbols: set[str],
) -> dict[str, Any]:
    """Intersect snapshot symbols with actually-covered provider symbols.

    Parameters
    ----------
    snapshot_date
        One snapshot date entry.
    provider_symbols
        Set of symbols covered by the US market-specific provider.

    Returns
    -------
    dict
        ``requested`` — all snapshot symbols for this date (sorted).
        ``retained`` — symbols present in *provider_symbols* (sorted).
        ``missing`` — snapshot symbols *not* in *provider_symbols* (sorted).
        ``coverage_ratio`` — ``len(retained) / len(requested)``.
        ``complete`` — ``True`` when every official symbol is retained.
        ``date`` — the snapshot date string.
    """
    requested = sorted(snapshot_date.symbols)
    retained = sorted(s for s in requested if s in provider_symbols)
    missing = sorted(s for s in requested if s not in provider_symbols)
    n_requested = len(requested)
    coverage_ratio = round(len(retained) / n_requested, 4) if n_requested else 0.0
    return {
        "date": snapshot_date.date,
        "requested": requested,
        "retained": retained,
        "missing": missing,
        "n_requested": n_requested,
        "n_retained": len(retained),
        "n_missing": len(missing),
        "coverage_ratio": coverage_ratio,
        "complete": len(missing) == 0,
    }
