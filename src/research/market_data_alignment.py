"""Automatic train-start alignment for market-data coverage.

Route B: when ``--alignment-mode auto`` the system may move the requested
train-start **later** so that at least *min_symbols* symbols have contiguous
data from the aligned start through *test_end*.  The aligned start is always
``>=`` the requested start — it never shifts earlier (no forward-fill, no
zero-fill, no inference of missing history).

Every function is **fail-closed**: when the alignment cannot retain enough
symbols, or the aligned start is too late to support ≥ 3 half-year OOS
windows, the result is marked ``skipped`` and no symbols leak into the
retained set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.research.multi_market_readiness import MarketReadinessSpec
from src.research.rolling_windows import (
    RollingResearchWindow,
    filter_windows_by_available_range,
    half_year_rolling_windows,
)

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
_MIN_OOS_WINDOWS: int = 3
_FIRST_TEST_YEAR: int = 2024
_LAST_TEST_YEAR: int = 2026


# ══════════════════════════════════════════════════════════════════════════════
# CoverageAlignment
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CoverageAlignment:
    """Result of aligning a train-start to actual data-coverage boundaries.

    All fields are read-only — downstream code must not mutate alignment
    decisions after they are computed.

    Canonical date fields are ``requested_train_start`` and
    ``aligned_train_start``.  Legacy read-only properties ``requested_start``
    and ``aligned_start`` are provided for backward compatibility with
    existing runner code.
    """

    alignment_mode: str
    """``"strict"`` or ``"auto"`` — the mode that produced this result."""

    market: str
    """Market identifier (e.g. ``"us"``, ``"cn"``)."""

    requested_train_start: str
    """The start date originally requested by the caller (YYYY-MM-DD)."""

    aligned_train_start: str
    """The train-start after alignment (always ≥ *requested_train_start*)."""

    retained_symbols: tuple[str, ...]
    """Symbols whose coverage spans *aligned_train_start* through *test_end*."""

    dropped_symbols: tuple[str, ...]
    """Symbols that could not be retained (with per-symbol reasons)."""

    drop_reasons: dict[str, str]
    """Per-symbol reason for every entry in *dropped_symbols*."""

    min_symbols: int
    """Minimum number of symbols required for the universe to be valid."""

    test_end: str
    """The test-end boundary against which last-valid dates are checked."""

    alignment_reason: str
    """Why the alignment decision was made (e.g. ``"strict unchanged"``,
    ``"auto shifted"``, ``"auto unchanged"``, or ``"skipped: …"``)."""

    sufficient: bool
    """``True`` when ``len(retained_symbols) >= min_symbols``."""

    skipped: bool
    """``True`` when the universe is skipped (convenience negation)."""

    skip_reason: str | None
    """Human-readable reason when skipped, else ``None``."""

    viable_windows: int
    """Number of half-year OOS windows the aligned start can support."""

    min_viable_windows: int
    """Minimum required OOS windows (default 3)."""

    # ── legacy property aliases ────────────────────────────────────────────

    @property
    def requested_start(self) -> str:
        """Legacy alias for :attr:`requested_train_start`."""
        return self.requested_train_start

    @property
    def aligned_start(self) -> str:
        """Legacy alias for :attr:`aligned_train_start`."""
        return self.aligned_train_start

    def to_dict(self) -> dict[str, object]:
        return {
            "alignment_mode": self.alignment_mode,
            "market": self.market,
            "requested_train_start": self.requested_train_start,
            "aligned_train_start": self.aligned_train_start,
            "retained_symbols": list(self.retained_symbols),
            "dropped_symbols": list(self.dropped_symbols),
            "drop_reasons": dict(self.drop_reasons),
            "min_symbols": self.min_symbols,
            "test_end": self.test_end,
            "alignment_reason": self.alignment_reason,
            "sufficient": self.sufficient,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "viable_windows": self.viable_windows,
            "min_viable_windows": self.min_viable_windows,
            # Legacy aliases for backward compatibility
            "requested_start": self.requested_train_start,
            "aligned_start": self.aligned_train_start,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Core alignment logic
# ══════════════════════════════════════════════════════════════════════════════


def find_common_coverage_start(
    symbol_dates: dict[str, dict[str, str | None]],
    *,
    min_symbols: int,
    test_end: str,
) -> str | None:
    """Find the earliest date at which ≥ *min_symbols* symbols have coverage.

    A symbol qualifies when its ``first_valid_date`` ≤ the candidate date
    **and** its ``last_valid_date`` ≥ *test_end*.  Symbols with ``None`` dates
    are always excluded.

    Parameters
    ----------
    symbol_dates
        Mapping of ``symbol → {"first_valid_date": str|None,
        "last_valid_date": str|None}``.  Dates must be ISO-format or ``None``.
    min_symbols
        Minimum number of qualifying symbols required.
    test_end
        The test-end boundary (YYYY-MM-DD).  A symbol's last-valid date must
        be ≥ this value.

    Returns
    -------
    str | None
        The earliest common start date (YYYY-MM-DD), or ``None`` when fewer
        than *min_symbols* symbols can cover through *test_end*.
    """
    if min_symbols < 2:
        raise ValueError("min_symbols must be at least 2")
    if not symbol_dates:
        return None

    test_end_ts = pd.Timestamp(test_end)

    # Collect only symbols whose last-valid date covers test_end and whose
    # first-valid date is known (non-None).
    qualified: list[tuple[str, pd.Timestamp]] = []
    dropped: dict[str, str] = {}

    for sym, dates in symbol_dates.items():
        first_raw = dates.get("first_valid_date")
        last_raw = dates.get("last_valid_date")

        if first_raw is None:
            dropped[sym] = "no first_valid_date (never listed or no data)"
            continue
        if last_raw is None:
            dropped[sym] = "no last_valid_date"
            continue

        last_ts = pd.Timestamp(last_raw)
        if last_ts < test_end_ts:
            dropped[sym] = (
                f"last_valid_date {last_raw} is before test_end {test_end}"
            )
            continue

        first_ts = pd.Timestamp(first_raw)
        qualified.append((sym, first_ts))

    if len(qualified) < min_symbols:
        return None

    # Sort by first-valid date ascending.  The *min_symbols*-th symbol's
    # first-valid date is the earliest point at which we have enough coverage.
    qualified.sort(key=lambda item: item[1])
    candidate_start = qualified[min_symbols - 1][1]

    return candidate_start.strftime("%Y-%m-%d")


def get_aligned_windows(
    aligned_start: str,
    available_end: str,
    *,
    first_test_year: int = _FIRST_TEST_YEAR,
    last_test_year: int = _LAST_TEST_YEAR,
) -> list[RollingResearchWindow]:
    """Return adjusted half-year ``RollingResearchWindow`` objects for an aligned start.

    Each window's ``train_start`` is set to ``max(original, aligned_start)``.
    Windows with empty training periods (train_start ≥ train_end) or with
    ``test_end`` beyond *available_end* are dropped.

    This is the **single public helper** that both runners and readiness
    counting must use — it guarantees that the windows used for execution and
    the viable-window count in ``CoverageAlignment`` can never diverge.

    Parameters
    ----------
    aligned_start
        The aligned train-start date (YYYY-MM-DD).  Generated windows whose
        original train-start is earlier are adjusted upward.
    available_end
        The end of available data (YYYY-MM-DD).  Windows whose test-end
        exceeds this boundary are excluded.
    first_test_year / last_test_year
        OOS test-year range forwarded to :func:`half_year_rolling_windows`.

    Returns
    -------
    list[RollingResearchWindow]
        Surviving windows with adjusted train-start fields.  Empty when no
        window can be formed.
    """
    aligned_ts = pd.Timestamp(aligned_start)
    available_end_ts = pd.Timestamp(available_end)

    if aligned_ts > available_end_ts:
        return []

    aligned_year = int(aligned_start[:4])
    start_year = min(aligned_year, first_test_year - 1)
    windows = half_year_rolling_windows(
        start_year=start_year,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )

    adjusted: list[RollingResearchWindow] = []
    for w in windows:
        effective_train = (
            aligned_start
            if pd.Timestamp(w.train_start) < aligned_ts
            else w.train_start
        )
        train_end_ts = pd.Timestamp(w.train_end)
        # Drop windows with empty training period.
        if pd.Timestamp(effective_train) >= train_end_ts:
            continue
        # Drop windows whose test_end exceeds the available range.
        if pd.Timestamp(w.test_end) > available_end_ts:
            continue
        if effective_train != w.train_start:
            w = RollingResearchWindow(
                label=w.label,
                train_start=effective_train,
                train_end=w.train_end,
                test_start=w.test_start,
                test_end=w.test_end,
            )
        adjusted.append(w)

    return adjusted


def _count_viable_oos_windows(
    aligned_start: str,
    test_end: str,
    *,
    first_test_year: int = _FIRST_TEST_YEAR,
    last_test_year: int = _LAST_TEST_YEAR,
) -> int:
    """Count half-year OOS windows that can be formed from *aligned_start*.

    Delegates to :func:`get_aligned_windows` so the count can never diverge
    from the windows a runner would receive.
    """
    return len(
        get_aligned_windows(
            aligned_start,
            test_end,
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        )
    )


def align_train_start_to_coverage(
    spec: MarketReadinessSpec,
    date_coverage_data: dict[str, dict[str, Any]],
    *,
    alignment_mode: str = "strict",
    min_viable_windows: int = _MIN_OOS_WINDOWS,
    first_test_year: int = _FIRST_TEST_YEAR,
    last_test_year: int = _LAST_TEST_YEAR,
) -> CoverageAlignment:
    """Align a single market's train-start to actual data coverage.

    Parameters
    ----------
    spec
        Market readiness specification (symbols, benchmark, requested
        train-start, test-end, min_symbols).
    date_coverage_data
        Per-symbol date-coverage records from
        :func:`~src.research.universe_robustness.load_symbol_date_coverage`.
    alignment_mode
        ``"strict"`` — use the requested start unchanged.  The result is
        skipped when coverage is insufficient at that start.
        ``"auto"`` — attempt to find a later common start that retains ≥
        *min_symbols*, and skip only when no such start exists or the aligned
        start cannot support ≥ *min_viable_windows* OOS windows.
    min_viable_windows
        Minimum number of half-year OOS windows required (default 3).
    first_test_year
        First OOS test year for window viability check.
    last_test_year
        Last OOS test year for window viability check.

    Returns
    -------
    CoverageAlignment
        Frozen alignment result.  The caller reads ``.aligned_start``,
        ``.skipped``, and ``.retained_symbols`` to proceed or bail out.
    """
    if alignment_mode not in ("strict", "auto"):
        raise ValueError(
            f"alignment_mode must be 'strict' or 'auto', got {alignment_mode!r}"
        )

    market = spec.market
    requested_start = spec.train_start
    test_end = spec.test_end
    min_symbols = spec.min_symbols

    # ── Per-symbol classification ──────────────────────────────────────────
    test_end_ts = pd.Timestamp(test_end)
    requested_ts = pd.Timestamp(requested_start)

    retained: list[str] = []
    dropped: list[str] = []
    drop_reasons: dict[str, str] = {}

    for sym in spec.symbols:
        rec = date_coverage_data.get(sym)
        if rec is None:
            dropped.append(sym)
            drop_reasons[sym] = "not found in date_coverage_data"
            continue

        first_raw = rec.get("first_valid_date")
        last_raw = rec.get("last_valid_date")

        if first_raw is None:
            dropped.append(sym)
            drop_reasons[sym] = "missing first_valid_date (no data or never listed)"
            continue
        if last_raw is None:
            dropped.append(sym)
            drop_reasons[sym] = "missing last_valid_date"
            continue

        last_ts = pd.Timestamp(last_raw)
        if last_ts < test_end_ts:
            dropped.append(sym)
            drop_reasons[sym] = (
                f"last_valid_date {last_raw} before test_end {test_end}"
            )
            continue

        # Strict mode: symbol must cover the requested train-start.
        # Prefer the covers_train_start flag (includes boundary tolerance);
        # fall back to first_valid_date <= requested_start.
        if alignment_mode == "strict":
            train_ok = rec.get("covers_train_start")
            if train_ok is False:
                dropped.append(sym)
                drop_reasons[sym] = (
                    f"covers_train_start is False for "
                    f"requested_start {requested_start}"
                )
                continue
            if train_ok is None:
                # Derive equivalent comparison from raw dates.
                if pd.Timestamp(first_raw) > requested_ts:
                    dropped.append(sym)
                    drop_reasons[sym] = (
                        f"first_valid_date {first_raw} after "
                        f"requested_start {requested_start}"
                    )
                    continue

        retained.append(sym)

    # ── Alignment decision ─────────────────────────────────────────────────
    aligned_start = requested_start

    if alignment_mode == "auto":
        # Build symbol_dates dict from retained symbols for find_common_coverage_start
        symbol_dates: dict[str, dict[str, str | None]] = {}
        for sym in retained:
            rec = date_coverage_data.get(sym, {})
            symbol_dates[sym] = {
                "first_valid_date": rec.get("first_valid_date"),
                "last_valid_date": rec.get("last_valid_date"),
            }

        common_start = find_common_coverage_start(
            symbol_dates,
            min_symbols=min_symbols,
            test_end=test_end,
        )

        if common_start is not None:
            common_ts = pd.Timestamp(common_start)
            if common_ts > requested_ts:
                aligned_start = common_start
                # Re-filter retained: drop symbols whose first_valid_date > aligned_start
                still_retained: list[str] = []
                for sym in retained:
                    rec = date_coverage_data.get(sym, {})
                    first_raw = rec.get("first_valid_date")
                    if first_raw is None:
                        dropped.append(sym)
                        drop_reasons[sym] = (
                            "first_valid_date became None during re-filter"
                        )
                        continue
                    if pd.Timestamp(first_raw) > common_ts:
                        dropped.append(sym)
                        drop_reasons[sym] = (
                            f"first_valid_date {first_raw} after aligned start {aligned_start}"
                        )
                        continue
                    still_retained.append(sym)
                retained = still_retained

    # ── Viability check ────────────────────────────────────────────────────
    sufficient = len(retained) >= min_symbols

    viable_windows = 0
    if sufficient:
        viable_windows = _count_viable_oos_windows(
            aligned_start,
            test_end,
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        )

    windows_viable = viable_windows >= min_viable_windows

    # ── Build skip reason ──────────────────────────────────────────────────
    skipped = False
    skip_reason: str | None = None

    if not sufficient:
        skipped = True
        if alignment_mode == "auto":
            skip_reason = (
                f"auto alignment failed: cannot retain ≥ {min_symbols} symbols "
                f"with coverage through {test_end} (retained {len(retained)}/"
                f"{len(spec.symbols)})"
            )
        else:
            skip_reason = (
                f"strict mode: {len(retained)}/{len(spec.symbols)} symbols "
                f"have sufficient coverage (need ≥ {min_symbols})"
            )
    elif not windows_viable:
        skipped = True
        skip_reason = (
            f"aligned start {aligned_start} supports only {viable_windows} "
            f"half-year OOS windows (need ≥ {min_viable_windows})"
        )

    # ── alignment_reason ───────────────────────────────────────────────────
    if skipped:
        alignment_reason = f"skipped: {skip_reason}"
    elif alignment_mode == "strict":
        alignment_reason = "strict unchanged"
    elif aligned_start > requested_start:
        alignment_reason = "auto shifted"
    else:
        alignment_reason = "auto unchanged"

    # Fail-closed: when skipped, empty the retained set.
    final_retained = tuple(retained) if not skipped else ()
    final_dropped = tuple(sorted(set(dropped)))
    final_reasons: dict[str, str] = {}
    for sym in final_dropped:
        final_reasons[sym] = drop_reasons.get(sym, "unknown")

    return CoverageAlignment(
        alignment_mode=alignment_mode,
        market=market,
        requested_train_start=requested_start,
        aligned_train_start=aligned_start,
        retained_symbols=final_retained,
        dropped_symbols=final_dropped,
        drop_reasons=final_reasons,
        min_symbols=min_symbols,
        test_end=test_end,
        alignment_reason=alignment_reason,
        sufficient=sufficient and windows_viable,
        skipped=skipped,
        skip_reason=skip_reason,
        viable_windows=viable_windows,
        min_viable_windows=min_viable_windows,
    )


def build_aligned_market_readiness(
    specs: list[MarketReadinessSpec],
    *,
    alignment_mode: str = "strict",
    min_viable_windows: int = _MIN_OOS_WINDOWS,
    first_test_year: int = _FIRST_TEST_YEAR,
    last_test_year: int = _LAST_TEST_YEAR,
) -> dict[str, dict[str, Any]]:
    """Run coverage alignment across multiple market specs.

    Each market is checked independently — a skipped US market does not
    prevent a passing CN market (or vice versa).

    Parameters
    ----------
    specs
        One or more :class:`MarketReadinessSpec` entries.
    alignment_mode
        ``"strict"`` or ``"auto"``.
    min_viable_windows
        Minimum OOS windows required (default 3).
    first_test_year / last_test_year
        OOS test range for window-viability checks.

    Returns
    -------
    dict[str, dict]
        Mapping of ``market → alignment_report`` where each report is the
        ``to_dict()`` output of :class:`CoverageAlignment`.
    """
    from src.research.universe_robustness import load_symbol_date_coverage

    reports: dict[str, dict[str, Any]] = {}
    for spec in specs:
        market = spec.market

        # Load actual date coverage data
        date_coverage = load_symbol_date_coverage(
            list(spec.symbols), spec.train_start, spec.test_end
        )

        alignment = align_train_start_to_coverage(
            spec,
            date_coverage,
            alignment_mode=alignment_mode,
            min_viable_windows=min_viable_windows,
            first_test_year=first_test_year,
            last_test_year=last_test_year,
        )

        reports[market] = alignment.to_dict()
        reports[market]["benchmark"] = spec.benchmark
        reports[market]["requested_symbols"] = list(spec.symbols)
        n_req = len(spec.symbols)
        n_ret = len(alignment.retained_symbols)
        reports[market]["coverage_ratio"] = round(n_ret / n_req, 4) if n_req else 0.0
        reports[market]["normalization"] = [
            {"original_symbol": s, "normalized_symbol": s, "candidates": [s]}
            for s in spec.symbols
        ]

        logger.info(
            "market=%s mode=%s requested=%s aligned=%s retained=%d/%d skipped=%s",
            market,
            alignment_mode,
            spec.train_start,
            alignment.aligned_train_start,
            len(alignment.retained_symbols),
            len(spec.symbols),
            alignment.skipped,
        )

    return reports
