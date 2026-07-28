"""Point-in-time Nasdaq-100 window-start universe contract.

This module provides a deterministic contract for the committed NDX membership
snapshot stored at ``configs/research_universes/ndx_window_start_membership.json``.

Key types
---------
:class:`NdxSnapshotDate`
    One snapshot date with sorted symbols, count, and SHA-256 hash.
:class:`NdxUniverseResult`
    Immutable output: aligned train start, training/OOS symbols, provenance.
:func:`load_snapshot`
    Load the full snapshot from disk — validates schema and hashes.
:func:`validate_snapshot_hash`
    Re-compute and verify the membership hash for one date.
:func:`resolve_latest_snapshot_on_or_before`
    Return the latest committed snapshot on or before a date (fail-closed).
:func:`filter_training_by_asof_membership`
    Filter a MultiIndex (datetime,instrument) frame by as-of snapshot membership.
:func:`intersect_with_provider`
    Intersect snapshot symbols with actually-covered provider symbols.
:func:`compute_membership_hash`
    Deterministic SHA-256 of sorted, pipe-joined symbol list.
:func:`plan_ndx_window_universe`
    Pure planner: produce one :class:`NdxUniverseResult` from a plan.
:func:`filter_training_union_by_membership_coverage`
    Retain training symbols whose provider data covers their semiannual
    membership intervals (extracted from the legacy runner).

All functions are **fail-closed**: they raise on missing data, hash mismatch,
or schema violations.  No silent fallback to stale or empty data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

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
# As-of membership resolution
# ═══════════════════════════════════════════════════════════════════════


def resolve_latest_snapshot_on_or_before(
    snapshot: NdxWindowStartSnapshot,
    date: str,
) -> NdxSnapshotDate:
    """Return the latest committed snapshot date on or before *date*.

    Parameters
    ----------
    snapshot
        The full snapshot container.
    date
        ISO date string (YYYY-MM-DD) to resolve membership for.

    Returns
    -------
    NdxSnapshotDate
        The latest snapshot entry whose date is ≤ *date*.

    Raises
    ------
    ValueError
        If no snapshot exists on or before *date* (fail-closed — never
        silently use a future snapshot).
    """
    candidates = [s for s in snapshot.snapshot_dates if s.date <= date]
    if not candidates:
        available = sorted(s.date for s in snapshot.snapshot_dates)
        raise ValueError(
            f"No NDX snapshot on or before {date}. "
            f"Earliest available: {available[0] if available else 'none'}"
        )
    return max(candidates, key=lambda s: s.date)


def filter_training_by_asof_membership(
    frame: pd.DataFrame,
    snapshot: NdxWindowStartSnapshot,
    provider_symbols: set[str],
) -> pd.DataFrame:
    """Filter a MultiIndex (datetime, instrument) frame by as-of snapshot membership.

    For each unique date in *frame*, the latest snapshot on or before that date
    is resolved, and only rows whose instrument appears in that snapshot **and**
    in *provider_symbols* are retained.

    Dates before the earliest committed snapshot have **all** rows dropped
    (fail-closed — never silently keep rows with unknown membership).

    Parameters
    ----------
    frame
        DataFrame with a ``(datetime, instrument)`` MultiIndex.
    snapshot
        Full committed NDX membership snapshot.
    provider_symbols
        Set of provider-covered symbols (snapshot symbols not in this set
        are excluded from membership for every date).

    Returns
    -------
    pd.DataFrame
        Filtered copy of *frame*.

    Raises
    ------
    ValueError
        If *frame* is empty after filtering (fail-closed).
    """
    if frame.empty:
        return frame

    snap_sorted = sorted(snapshot.snapshot_dates, key=lambda s: s.date)
    dates = pd.DatetimeIndex(frame.index.get_level_values("datetime"))
    instruments = frame.index.get_level_values("instrument")
    mask = pd.Series(False, index=frame.index, dtype=bool)

    # One vectorised scan per snapshot interval, rather than one full-frame
    # scan per trading day.  Dates before the earliest snapshot remain False.
    for index, entry in enumerate(snap_sorted):
        interval_start = pd.Timestamp(entry.date)
        interval_end = (
            pd.Timestamp(snap_sorted[index + 1].date)
            if index + 1 < len(snap_sorted)
            else None
        )
        date_match = dates >= interval_start
        if interval_end is not None:
            date_match &= dates < interval_end
        members = set(entry.symbols) & provider_symbols
        if members:
            mask |= date_match & instruments.isin(members)

    return frame.loc[mask].copy()


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


# ═══════════════════════════════════════════════════════════════════════
# First-trading-day mapping for OOS window labels
# ═══════════════════════════════════════════════════════════════════════

# Validated mapping from half-year window label to the first trading day
# of that period.  Callers MUST fail closed for undeclared labels — never
# silently use an older snapshot.
NDX_WINDOW_SNAPSHOT_MAP: dict[str, str] = {
    "2024H1": "2024-01-02",
    "2024H2": "2024-07-01",
    "2025H1": "2025-01-02",
    "2025H2": "2025-07-01",
}

# Maximum allowed gap between required membership coverage bounds and
# actual provider data boundaries for a symbol to be retained.
DEFAULT_MAX_MEMBERSHIP_BOUNDARY_GAP_DAYS: int = 14

# Minimum number of tradable symbols a window must retain.
DEFAULT_MIN_WINDOW_SYMBOLS: int = 50


def resolve_window_snapshot_date(
    window_label: str,
    *,
    snapshot_map: dict[str, str] | None = None,
) -> str:
    """Return the first-trading-day snapshot date for a window label.

    Parameters
    ----------
    window_label
        Half-year label (e.g. ``"2024H1"``).
    snapshot_map
        Optional override mapping.  Defaults to :data:`NDX_WINDOW_SNAPSHOT_MAP`.

    Returns
    -------
    str
        ISO date string (YYYY-MM-DD).

    Raises
    ------
    KeyError
        If *window_label* is not in the mapping (fail-closed).
    """
    mapping = snapshot_map if snapshot_map is not None else NDX_WINDOW_SNAPSHOT_MAP
    if window_label not in mapping:
        available = sorted(mapping)
        raise KeyError(
            f"Window label {window_label!r} has no declared first-trading-day "
            f"snapshot. Available: {available}"
        )
    return mapping[window_label]


# ═══════════════════════════════════════════════════════════════════════
# Shared immutable plan / result types
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class NdxUniverseResult:
    """Immutable output from one NDX window universe plan.

    When ``skipped`` is ``True``, all symbol fields are empty and
    ``skip_reason`` explains why.  When ``skipped`` is ``False``, the
    result contains validated training/OOS symbols and full provenance.
    """

    window_label: str
    """The window label from the plan."""

    skipped: bool
    """``True`` when the window cannot be evaluated."""

    skip_reason: str | None = None
    """Why the window was skipped (``None`` when ``skipped`` is ``False``)."""

    aligned_train_start: str | None = None
    """Aligned training start (50th-earliest first-valid date)."""

    train_symbols: tuple[str, ...] = ()
    """Retained training symbols after membership-interval filter."""

    oos_symbols: tuple[str, ...] = ()
    """Retained OOS test symbols."""

    oos_snapshot_date: str = ""
    """First-trading-day snapshot date used."""

    oos_snapshot_hash: str = ""
    """SHA-256 hash of the OOS snapshot membership."""

    oos_requested_count: int = 0
    """Number of official NDX symbols at the OOS snapshot."""

    oos_retained_count: int = 0
    """Number of OOS symbols retained after provider + coverage filter."""

    oos_missing_symbols: tuple[str, ...] = ()
    """OOS snapshot symbols not in the provider."""

    oos_dropped_symbols: tuple[str, ...] = ()
    """OOS symbols dropped by date-coverage filter."""

    train_requested_union_count: int = 0
    """Number of distinct official NDX symbols across all training snapshots."""

    train_union_provider_retained_count: int = 0
    """Number of training-union symbols retained by the provider."""

    train_date_retained_count: int = 0
    """Number of training symbols after membership-interval filter."""

    train_dropped_symbols: tuple[str, ...] = ()
    """Training symbols dropped by membership-interval filter."""

    train_dropped_reasons: dict[str, str] = field(default_factory=dict)
    """Per-symbol reason for every dropped training symbol."""

    training_snapshot_dates: tuple[str, ...] = ()
    """Snapshot dates used for training (sorted)."""

    per_snapshot_detail: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-snapshot requested/retained counts."""

    pit_flags: dict[str, bool] = field(default_factory=dict)
    """Explicit PIT flags for evidence metadata."""

    provenance: dict[str, Any] = field(default_factory=dict)
    """Complete provenance payload for evidence writing."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_label": self.window_label,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "aligned_train_start": self.aligned_train_start,
            "train_symbols": list(self.train_symbols),
            "oos_symbols": list(self.oos_symbols),
            "oos_snapshot_date": self.oos_snapshot_date,
            "oos_snapshot_hash": self.oos_snapshot_hash,
            "oos_requested_count": self.oos_requested_count,
            "oos_retained_count": self.oos_retained_count,
            "oos_missing_symbols": list(self.oos_missing_symbols),
            "oos_dropped_symbols": list(self.oos_dropped_symbols),
            "train_requested_union_count": self.train_requested_union_count,
            "train_union_provider_retained_count": self.train_union_provider_retained_count,
            "train_date_retained_count": self.train_date_retained_count,
            "train_dropped_symbols": list(self.train_dropped_symbols),
            "train_dropped_reasons": dict(self.train_dropped_reasons),
            "training_snapshot_dates": list(self.training_snapshot_dates),
            "per_snapshot_detail": dict(self.per_snapshot_detail),
            "pit_flags": dict(self.pit_flags),
            "provenance": dict(self.provenance),
        }

    @property
    def coverage_meta(self) -> dict[str, Any]:
        """Evidence-compatible coverage metadata (backward-compatible shape)."""
        return {
            "oos_snapshot_date": self.oos_snapshot_date,
            "oos_requested_symbols": list(
                self.provenance.get("oos_requested_symbols", [])
            ),
            "oos_provider_retained": list(
                self.provenance.get("oos_provider_retained", [])
            ),
            "oos_provider_missing": list(self.oos_missing_symbols),
            "oos_date_coverage_dropped": list(self.oos_dropped_symbols),
            "oos_test_symbols": list(self.oos_symbols),
            "oos_test_retained": self.oos_retained_count,
            "n_oos_requested": self.oos_requested_count,
            "n_oos_test_retained": self.oos_retained_count,
            "training_snapshot_dates": list(self.training_snapshot_dates),
            "n_training_snapshots": len(self.training_snapshot_dates),
            "training_union_requested": self.train_requested_union_count,
            "training_union_provider_retained": self.train_union_provider_retained_count,
            "training_date_retained": self.train_date_retained_count,
            "training_date_dropped": list(self.train_dropped_symbols),
            "training_date_drop_reasons": dict(self.train_dropped_reasons),
            "training_membership_required_bounds": dict(
                self.provenance.get("training_membership_required_bounds", {})
            ),
            "training_symbols": list(self.train_symbols),
            "per_snapshot_requested": dict(
                self.provenance.get("per_snapshot_requested", {})
            ),
            "per_snapshot_retained": dict(
                self.provenance.get("per_snapshot_retained", {})
            ),
            "per_snapshot_missing": dict(
                self.provenance.get("per_snapshot_missing", {})
            ),
            "aligned_train_start": self.aligned_train_start,
            "training_membership_asof_semiannual": self.pit_flags.get(
                "training_membership_asof_semiannual", True
            ),
            "training_uses_future_oos_snapshot": self.pit_flags.get(
                "training_uses_future_oos_snapshot", False
            ),
            "full_daily_point_in_time": self.pit_flags.get(
                "full_daily_point_in_time", False
            ),
            "provider_coverage_incomplete": bool(
                self.oos_missing_symbols
                or self.oos_dropped_symbols
                or self.train_dropped_symbols
            ),
            "oos_membership_point_in_time": self.pit_flags.get(
                "oos_membership_point_in_time", True
            ),
            "research_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
            "ranker_mode": self.provenance.get("ranker_mode", ""),
            "per_snapshot_detail": dict(self.per_snapshot_detail),
        }


# ═══════════════════════════════════════════════════════════════════════
# Training-union membership-interval coverage filter
# ═══════════════════════════════════════════════════════════════════════


def filter_training_union_by_membership_coverage(
    symbols: list[str],
    *,
    snapshot: NdxWindowStartSnapshot,
    aligned_train_start: str,
    train_end: str,
    date_coverage_data: dict[str, dict[str, Any]],
    min_symbols: int = DEFAULT_MIN_WINDOW_SYMBOLS,
    max_gap_days: int = DEFAULT_MAX_MEMBERSHIP_BOUNDARY_GAP_DAYS,
) -> dict[str, Any]:
    """Retain symbols that cover only their actual as-of membership interval.

    A constituent that leaves NDX before ``train_end`` must not be dropped
    merely because it has no later bars. Conversely, bars after a ticker
    rename or index exit must not be required to make its historical rows
    eligible. The semiannual snapshot interval is the coverage contract.

    Parameters
    ----------
    symbols
        Candidate training-union symbols.
    snapshot
        Full committed NDX membership snapshot.
    aligned_train_start
        Aligned training start (ISO date).
    train_end
        Training end boundary (ISO date).
    date_coverage_data
        Per-symbol first/last valid date and observation count.
    min_symbols
        Minimum retained symbols before the result is marked skipped.
    max_gap_days
        Maximum allowed gap between required bounds and actual data.

    Returns
    -------
    dict
        ``skipped``, ``skip_reason``, ``retained_symbols``,
        ``dropped_symbols``, ``dropped_reasons``, ``required_bounds``.
    """
    aligned_start_ts = pd.Timestamp(aligned_train_start)
    train_end_ts = pd.Timestamp(train_end)
    if aligned_start_ts > train_end_ts:
        raise ValueError("aligned_train_start must be on or before train_end")

    entries = sorted(snapshot.snapshot_dates, key=lambda entry: entry.date)
    required_bounds: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for index, entry in enumerate(entries):
        interval_start = pd.Timestamp(entry.date)
        if interval_start > train_end_ts:
            break
        next_start = (
            pd.Timestamp(entries[index + 1].date)
            if index + 1 < len(entries)
            else train_end_ts + pd.Timedelta(days=1)
        )
        interval_end = min(train_end_ts, next_start - pd.Timedelta(days=1))
        active_start = max(aligned_start_ts, interval_start)
        if active_start > interval_end:
            continue
        for symbol in entry.symbols:
            if symbol not in symbols:
                continue
            previous = required_bounds.get(symbol)
            if previous is None:
                required_bounds[symbol] = (active_start, interval_end)
            else:
                required_bounds[symbol] = (
                    min(previous[0], active_start),
                    max(previous[1], interval_end),
                )

    gap = pd.Timedelta(days=max_gap_days)
    retained: list[str] = []
    dropped: list[str] = []
    dropped_reasons: dict[str, str] = {}
    serialized_bounds: dict[str, dict[str, str]] = {}

    for symbol in symbols:
        bounds = required_bounds.get(symbol)
        if bounds is None:
            dropped.append(symbol)
            dropped_reasons[symbol] = (
                "no membership interval in aligned training range"
            )
            continue
        required_start, required_end = bounds
        serialized_bounds[symbol] = {
            "required_start": required_start.strftime("%Y-%m-%d"),
            "required_end": required_end.strftime("%Y-%m-%d"),
        }
        record = date_coverage_data.get(symbol, {})
        first_raw = record.get("first_valid_date")
        last_raw = record.get("last_valid_date")
        observations = int(record.get("observations", 0) or 0)
        if first_raw is None or last_raw is None or observations <= 0:
            dropped.append(symbol)
            dropped_reasons[symbol] = "no valid price observations"
            continue
        first_valid = pd.Timestamp(first_raw)
        last_valid = pd.Timestamp(last_raw)
        if first_valid > required_start + gap:
            dropped.append(symbol)
            dropped_reasons[symbol] = (
                f"history starts {first_valid.date()} after required "
                f"{required_start.date()}"
            )
            continue
        if last_valid < required_end - gap:
            dropped.append(symbol)
            dropped_reasons[symbol] = (
                f"history ends {last_valid.date()} before required "
                f"{required_end.date()}"
            )
            continue
        retained.append(symbol)

    return {
        "skipped": len(retained) < min_symbols,
        "skip_reason": (
            None
            if len(retained) >= min_symbols
            else (
                f"membership-interval coverage retained {len(retained)} symbols; "
                f"minimum is {min_symbols}"
            )
        ),
        "retained_symbols": retained,
        "dropped_symbols": dropped,
        "dropped_reasons": dropped_reasons,
        "required_bounds": serialized_bounds,
    }


# ═══════════════════════════════════════════════════════════════════════
# Pure planner — one window, one result
# ═══════════════════════════════════════════════════════════════════════


def plan_ndx_window_universe(
    snapshot: NdxWindowStartSnapshot,
    provider_symbols: set[str],
    window_label: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    *,
    oos_snapshot_date: str | None = None,
    snapshot_map: dict[str, str] | None = None,
    min_symbols: int = DEFAULT_MIN_WINDOW_SYMBOLS,
    max_gap_days: int = DEFAULT_MAX_MEMBERSHIP_BOUNDARY_GAP_DAYS,
    coverage_loader: Callable[
        [list[str], str, str], dict[str, dict[str, Any]]
    ],
    benchmark_exclusion_set: frozenset[str] | None = None,
) -> NdxUniverseResult:
    """Plan one NDX window-start universe: OOS symbols, training union, alignment.

    This is the **single shared planner** for NDX-window-start point-in-time
    universe construction.  It performs:

    1. OOS symbol resolution from the window-start snapshot.
    2. Training-union symbol collection from all snapshots ≤ train_end.
    3. Aligned training-start derivation (50th-earliest first-valid date).
    4. Membership-interval coverage filtering for training symbols.
    5. Full-provenance result with explicit PIT flags.

    Parameters
    ----------
    snapshot
        Full committed NDX membership snapshot.
    provider_symbols
        Provider-covered symbols (benchmarks already excluded).
    window_label
        Half-year label (e.g. ``"2024H1"``).
    train_start / train_end
        Nominal training boundaries.
    test_start / test_end
        OOS test boundaries.
    oos_snapshot_date
        First-trading-day snapshot date.  If ``None``, resolved from
        *snapshot_map* using *window_label*.
    snapshot_map
        Window-label → first-trading-day mapping.
    min_symbols
        Minimum tradable symbols required.
    max_gap_days
        Maximum gap between required and actual coverage boundaries.
    coverage_loader
        Callable ``(symbols, start, end) -> dict[symbol, coverage_record]``.
    benchmark_exclusion_set
        Symbols to exclude from tradable sets.

    Returns
    -------
    NdxUniverseResult
        Immutable result with all symbols, provenance, and PIT flags.
    """
    exclusion = (
        benchmark_exclusion_set
        if benchmark_exclusion_set is not None
        else frozenset({"QQQ", "SPY", "SPX", "^GSPC", "NDX", "^IXIC"})
    )

    # ── resolve OOS snapshot date ───────────────────────────────────────
    resolved_oos_date: str
    if oos_snapshot_date is not None:
        resolved_oos_date = oos_snapshot_date
    else:
        resolved_oos_date = resolve_window_snapshot_date(
            window_label, snapshot_map=snapshot_map
        )

    # ── OOS test symbols (window-start snapshot) ────────────────────────
    oos_entry = get_snapshot_by_date(snapshot, resolved_oos_date)
    oos_provider_report = intersect_with_provider(oos_entry, provider_symbols)
    oos_requested = oos_provider_report["requested"]
    oos_retained_raw = oos_provider_report["retained"]

    def _exclude(symbols: list[str]) -> list[str]:
        return [s for s in symbols if s.upper() not in exclusion]

    oos_tradable_raw = _exclude(oos_retained_raw)

    if not oos_tradable_raw:
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason="OOS snapshot has no tradable symbols after benchmark exclusion",
            oos_snapshot_date=resolved_oos_date,
        )

    # ── Test-symbol date-coverage filter ────────────────────────────────
    test_coverage = coverage_loader(oos_tradable_raw, test_start, test_end)
    from src.research.universe_robustness import filter_universe_by_coverage

    test_coverage_filter = filter_universe_by_coverage(
        tuple(oos_tradable_raw),
        min_symbols=min_symbols,
        date_range=(test_start, test_end),
        date_coverage_data=test_coverage,
    )
    if test_coverage_filter.get("skipped", True):
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=test_coverage_filter.get(
                "skip_reason", "insufficient OOS test date coverage"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    test_symbols = test_coverage_filter["retained_symbols"]
    if len(test_symbols) < min_symbols:
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=(
                f"fewer than {min_symbols} OOS test symbols retained "
                f"({len(test_symbols)})"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    # ── Training-union symbols (all snapshots ≤ train_end) ──────────────
    training_snapshot_entries = sorted(
        [s for s in snapshot.snapshot_dates if s.date <= train_end],
        key=lambda s: s.date,
    )
    if not training_snapshot_entries:
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=(
                f"no NDX snapshots on or before train_end={train_end}"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    train_official_union: set[str] = set()
    train_union: set[str] = set()
    per_snapshot_retained: dict[str, list[str]] = {}
    per_snapshot_requested: dict[str, int] = {}
    per_snapshot_missing: dict[str, list[str]] = {}
    for s in training_snapshot_entries:
        rep = intersect_with_provider(s, provider_symbols)
        train_official_union.update(_exclude(list(s.symbols)))
        retained = _exclude(rep["retained"])
        train_union.update(retained)
        per_snapshot_retained[s.date] = list(retained)
        per_snapshot_requested[s.date] = rep["n_requested"]
        per_snapshot_missing[s.date] = rep["missing"]

    train_union_list = sorted(train_union)
    if len(train_union_list) < min_symbols:
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=(
                f"training-union symbols ({len(train_union_list)}) below "
                f"minimum {min_symbols}"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    # ── Aligned training start: 50th earliest first-valid date ─────────
    train_union_coverage = coverage_loader(
        train_union_list, train_start, train_end
    )
    first_valid_dates: list[str] = []
    for s in train_union_list:
        rec = train_union_coverage.get(s, {})
        fvd = rec.get("first_valid_date")
        if fvd is not None and int(rec.get("observations", 0)) > 0:
            first_valid_dates.append(str(fvd))

    if len(first_valid_dates) < min_symbols:
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=(
                f"only {len(first_valid_dates)} training-union symbols have "
                f"valid coverage data (need {min_symbols})"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    first_valid_dates_sorted = sorted(first_valid_dates)
    aligned_train_start = first_valid_dates_sorted[min_symbols - 1]

    if pd.Timestamp(aligned_train_start) > pd.Timestamp(train_end):
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=(
                f"aligned training start {aligned_train_start} falls after "
                f"train_end {train_end}"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    # ── Retain symbols over their actual membership intervals ───────────
    aligned_train_coverage = coverage_loader(
        train_union_list, aligned_train_start, train_end
    )
    train_coverage_filter = filter_training_union_by_membership_coverage(
        train_union_list,
        snapshot=snapshot,
        aligned_train_start=aligned_train_start,
        train_end=train_end,
        date_coverage_data=aligned_train_coverage,
        min_symbols=min_symbols,
        max_gap_days=max_gap_days,
    )
    if train_coverage_filter.get("skipped", True):
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=train_coverage_filter.get(
                "skip_reason", "insufficient training date coverage in aligned range"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    train_symbols = train_coverage_filter["retained_symbols"]
    if len(train_symbols) < min_symbols:
        return NdxUniverseResult(
            window_label=window_label,
            skipped=True,
            skip_reason=(
                f"fewer than {min_symbols} training symbols retained "
                f"in aligned range ({len(train_symbols)})"
            ),
            oos_snapshot_date=resolved_oos_date,
        )

    # ── Build result ────────────────────────────────────────────────────
    per_snapshot_detail = {
        s.date: {
            "requested": per_snapshot_requested.get(s.date, 0),
            "retained": len(per_snapshot_retained.get(s.date, [])),
        }
        for s in training_snapshot_entries
    }

    pit_flags = {
        "training_membership_asof_semiannual": True,
        "training_uses_future_oos_snapshot": False,
        "full_daily_point_in_time": False,
        "oos_membership_point_in_time": True,
    }

    provenance: dict[str, Any] = {
        "oos_requested_symbols": oos_requested,
        "oos_provider_retained": oos_retained_raw,
        "per_snapshot_requested": per_snapshot_requested,
        "per_snapshot_retained": {
            d: len(v) for d, v in per_snapshot_retained.items()
        },
        "per_snapshot_missing": per_snapshot_missing,
        "training_membership_required_bounds": train_coverage_filter[
            "required_bounds"
        ],
        "ranker_mode": "",
    }

    return NdxUniverseResult(
        window_label=window_label,
        skipped=False,
        aligned_train_start=aligned_train_start,
        train_symbols=tuple(train_symbols),
        oos_symbols=tuple(test_symbols),
        oos_snapshot_date=resolved_oos_date,
        oos_snapshot_hash=oos_entry.sha256_membership_hash,
        oos_requested_count=len(oos_requested),
        oos_retained_count=len(test_symbols),
        oos_missing_symbols=tuple(oos_provider_report["missing"]),
        oos_dropped_symbols=tuple(test_coverage_filter["dropped_symbols"]),
        train_requested_union_count=len(train_official_union),
        train_union_provider_retained_count=len(train_union_list),
        train_date_retained_count=len(train_symbols),
        train_dropped_symbols=tuple(train_coverage_filter["dropped_symbols"]),
        train_dropped_reasons=train_coverage_filter["dropped_reasons"],
        training_snapshot_dates=tuple(s.date for s in training_snapshot_entries),
        per_snapshot_detail=per_snapshot_detail,
        pit_flags=pit_flags,
        provenance=provenance,
    )
