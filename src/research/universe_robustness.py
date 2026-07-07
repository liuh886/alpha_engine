"""Universe-robustness validation for fixed-10D ranker + momentum blend evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════
# Shared constants
# ══════════════════════════════════════════════════════════════════════════

# Maximum gap in calendar days between a symbol's first/last valid date and
# the requested evaluation range before the symbol is considered uncovered.
# This accounts for trading-calendar alignment (e.g. a symbol listed 2
# trading days after train_start still qualifies).
_MAX_CALENDAR_BOUNDARY_GAP_DAYS: int = 14

# Frozen ranker configuration for the 10D evidence pass.
# The ranker name encodes feature-group + calibration parameters.
_FEATURE_GROUP: str = "momentum_volatility_volume"
_CALIBRATION: str = "gain5_round100_leaves31_leaf10_lr0.05"
FROZEN_RANKER_NAME: str = f"lgbm:daily_ranker:{_FEATURE_GROUP}:{_CALIBRATION}"

# Fixed 50 / 50 blend weight (the single weight used for universe-robustness).
FROZEN_BLEND_WEIGHT: float = 0.50

# Canonical baseline factor name.
FROZEN_BASELINE_NAME: str = "factor:historical_momentum_10d"


# ══════════════════════════════════════════════════════════════════════════
# UniverseSpec
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UniverseSpec:
    """A named security universe with a minimum-symbol safety gate."""

    name: str
    symbols: tuple[str, ...]
    min_symbols: int = 2

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("UniverseSpec name must be a non-empty string")
        if not isinstance(self.symbols, tuple):
            raise ValueError("UniverseSpec symbols must be a tuple of strings")
        for s in self.symbols:
            if not isinstance(s, str):
                raise ValueError("UniverseSpec symbols must be all strings")
            if not s:
                raise ValueError("UniverseSpec symbols must be non-empty strings")
        if self.min_symbols < 2:
            raise ValueError("UniverseSpec min_symbols must be at least 2")
        seen: set[str] = set()
        duplicates: list[str] = []
        for s in self.symbols:
            if s in seen:
                duplicates.append(s)
            seen.add(s)
        if duplicates:
            raise ValueError(f"UniverseSpec symbols must be unique, duplicates: {sorted(set(duplicates))}")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "symbols": list(self.symbols), "min_symbols": self.min_symbols}

    @staticmethod
    def from_dict(data: dict[str, object]) -> UniverseSpec:
        name = str(data["name"])
        symbols = tuple(str(s) for s in data["symbols"])
        min_symbols = int(data.get("min_symbols", 2))
        return UniverseSpec(name=name, symbols=symbols, min_symbols=min_symbols)


# ══════════════════════════════════════════════════════════════════════════
# Local symbol discovery helpers
# ══════════════════════════════════════════════════════════════════════════


def _discover_watchlist_symbols(
    market: str,
    watchlist_path: str | None = None,
) -> list[str]:
    """Discover symbols from watchlist YAML and instrument files.

    Reads ``configs/watchlist.yaml`` (or *watchlist_path*) for the given
    *market*, then supplements with
    ``data/watchlist/instruments/{market}.txt``.  Returns a sorted deduplicated
    list, or an empty list when no sources can be read.
    """
    watchlist_symbols: list[str] = []
    if watchlist_path is None:
        watchlist_path = "configs/watchlist.yaml"
    try:
        import yaml

        with open(watchlist_path, encoding="utf-8") as fh:
            watchlist_data = yaml.safe_load(fh)
        if isinstance(watchlist_data, dict) and market in watchlist_data:
            raw = watchlist_data[market]
            if isinstance(raw, list):
                watchlist_symbols = sorted({str(s) for s in raw if isinstance(s, str)})
    except Exception:
        pass

    # Also try data/watchlist/instruments/{market}.txt
    instruments_file = Path("data/watchlist/instruments") / f"{market}.txt"
    file_symbols: list[str] = []
    try:
        if instruments_file.exists():
            lines = instruments_file.read_text(encoding="utf-8").strip().splitlines()
            for line in lines:
                parts = line.strip().split("\t")
                if parts and parts[0]:
                    file_symbols.append(str(parts[0]))
    except Exception:
        pass

    return sorted(set(watchlist_symbols + file_symbols))


def _discover_qlib_symbols(market: str) -> list[str]:
    """Discover symbols from Qlib instrument listing.

    Returns a sorted deduplicated list, or an empty list when Qlib is
    unavailable or errors.
    """
    try:
        import qlib
        from qlib.data import D

        all_instruments = D.list_instruments(D.instruments("all"), level="market")
        if hasattr(all_instruments, "tolist"):
            return sorted(set(str(s) for s in all_instruments.tolist()))
        else:
            return sorted(set(str(s) for s in all_instruments))
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════
# Date-coverage: load actual $close data per symbol from Qlib
# ══════════════════════════════════════════════════════════════════════════


def _looks_like_date(s: str) -> bool:
    """Check if a string value resembles an ISO date (YYYY-MM-DD or YYYYMMDD)."""
    s = s.strip()
    # YYYY-MM-DD
    parts = s.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if 1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return True
    # YYYYMMDD
    if s.isdigit() and len(s) == 8:
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
        if 1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return True
    return False


def _identify_index_levels(df: pd.DataFrame) -> tuple[int | None, int | None]:
    """Identify instrument and datetime level indices from a MultiIndex.

    Returns ``(instrument_level, datetime_level)`` or ``(None, None)``
    when the DataFrame is not a MultiIndex or the levels cannot be identified.
    """
    if not isinstance(df.index, pd.MultiIndex):
        return None, None

    names = df.index.names
    instr_level: int | None = None
    dt_level: int | None = None

    # ── Pass 1: identify by level name ─────────────────────────────────
    _INSTR_NAMES = frozenset({"instrument", "code", "symbol", "asset", "order_book_id"})
    _DT_NAMES = frozenset({"datetime", "date", "time", "timestamp", "trade_date", "tradedate"})

    for i, name in enumerate(names):
        if name is not None:
            n = str(name).lower().strip().replace(" ", "_").replace("-", "_")
            if n in _INSTR_NAMES:
                instr_level = i
            elif n in _DT_NAMES:
                dt_level = i

    # ── Pass 2: infer by value types when names are None/ambiguous ─────
    if instr_level is None or dt_level is None:
        for i in range(df.index.nlevels):
            if instr_level is not None and dt_level is not None:
                break
            if i == instr_level or i == dt_level:
                continue
            try:
                vals = df.index.get_level_values(i)
                samples = [vals[j] for j in range(min(len(vals), 30))]
                date_count = sum(1 for v in samples if isinstance(v, pd.Timestamp))
                non_date_str_count = sum(
                    1
                    for v in samples
                    if isinstance(v, str) and v.strip()
                    and not _looks_like_date(v.strip())
                )
                majority = len(samples) * 0.5
                if date_count >= majority and dt_level is None:
                    dt_level = i
                elif non_date_str_count >= majority and instr_level is None:
                    instr_level = i
            except Exception:
                continue

    return instr_level, dt_level


def _parse_qlib_features_frame(
    df: pd.DataFrame,
    instruments: list[str],
    *,
    field: str = "$close",
    req_start: pd.Timestamp,
    req_end: pd.Timestamp,
    pad: pd.Timedelta,
) -> dict[str, dict[str, Any]]:
    """Parse a Qlib ``D.features`` DataFrame into per-symbol coverage records.

    Qlib ``D.features`` returns a DataFrame whose rows are indexed by a
    MultiIndex of ``(instrument, datetime)`` (or ``(datetime, instrument)``)
    and whose columns are the requested field name(s).  This function
    normalises the index, groups by instrument, and derives per-symbol
    date coverage from the non-null values of *field*.

    Returns
    -------
    dict[str, dict]
        Mapping of symbol → coverage record with the same structure as
        :func:`load_symbol_date_coverage`.  Returns an **empty dict** when
        the frame cannot be parsed (missing MultiIndex, unrecognised level
        names, or the requested field is absent) — this is a fail-closed
        design that avoids silently manufacturing zero-coverage records
        from a misinterpreted shape.
    """
    if df is None or df.empty:
        return {}

    instr_level, dt_level = _identify_index_levels(df)
    if instr_level is None or dt_level is None:
        # Cannot interpret the index — fail closed rather than guessing.
        return {}

    # Select the requested field column
    if field not in df.columns:
        return {}
    series = df[field]

    instr_values = series.index.get_level_values(instr_level)

    coverage: dict[str, dict[str, Any]] = {}
    for sym in instruments:
        mask = instr_values == sym
        sym_data = series[mask].dropna()

        if sym_data.empty:
            coverage[sym] = {
                "first_valid_date": None,
                "last_valid_date": None,
                "observations": 0,
                "covers_train_start": False,
                "covers_test_end": False,
                "sufficient_coverage": False,
            }
            continue

        dt_values = sym_data.index.get_level_values(dt_level)
        first_dt: pd.Timestamp = dt_values.min()
        last_dt: pd.Timestamp = dt_values.max()
        obs = int(len(sym_data))

        covers_start = first_dt <= req_start + pad
        covers_end = last_dt >= req_end - pad
        sufficient = bool(covers_start and covers_end)

        coverage[sym] = {
            "first_valid_date": first_dt.strftime("%Y-%m-%d"),
            "last_valid_date": last_dt.strftime("%Y-%m-%d"),
            "observations": obs,
            "covers_train_start": bool(covers_start),
            "covers_test_end": bool(covers_end),
            "sufficient_coverage": sufficient,
        }

    return coverage


def load_symbol_date_coverage(
    symbols: list[str] | tuple[str, ...],
    start: str,
    end: str,
    *,
    field: str = "$close",
) -> dict[str, dict[str, Any]]:
    """Load per-symbol date coverage by querying Qlib *field* data.

    Parameters
    ----------
    symbols
        Symbols to check.
    start / end
        Evaluation date range (YYYY-MM-DD).  The query window is widened by
        ``_MAX_CALENDAR_BOUNDARY_GAP_DAYS`` on each side so symbols that are
        listed or delisted near the boundary are not unfairly dropped.
    field
        Qlib field expression to load (default ``"$close"``).

    Returns
    -------
    dict[str, dict]
        Mapping of symbol → coverage record with keys:

        * ``first_valid_date`` — earliest date with non-NaN data (ISO str)
        * ``last_valid_date`` — latest date with non-NaN data (ISO str)
        * ``observations`` — count of valid (non-NaN) rows
        * ``covers_train_start`` — whether first_valid_date is within
          *start* + boundary tolerance
        * ``covers_test_end`` — whether last_valid_date is within
          *end* - boundary tolerance
        * ``sufficient_coverage`` — True when both bounds are covered

        Returns an empty dict when Qlib is unavailable or errors.
    """
    if not symbols:
        return {}

    try:
        from qlib.data import D

        instruments = sorted(set(str(s) for s in symbols))
        if not instruments:
            return {}

        req_start = pd.Timestamp(start)
        req_end = pd.Timestamp(end)
        pad = pd.Timedelta(days=_MAX_CALENDAR_BOUNDARY_GAP_DAYS)
        query_start = (req_start - pad).strftime("%Y-%m-%d")
        query_end = (req_end + pad).strftime("%Y-%m-%d")

        df = D.features(
            instruments,
            [field],
            start_time=query_start,
            end_time=query_end,
            freq="day",
        )

        return _parse_qlib_features_frame(
            df, instruments,
            field=field,
            req_start=req_start,
            req_end=req_end,
            pad=pad,
        )

    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════
# Candidate naming: frozen ranker, blend, and baseline
# ══════════════════════════════════════════════════════════════════════════


def build_required_candidate_names(
    *,
    ranker_name: str = FROZEN_RANKER_NAME,
    blend_weight: float = FROZEN_BLEND_WEIGHT,
    baseline_name: str = FROZEN_BASELINE_NAME,
) -> dict[str, str]:
    """Return the exact candidate names required in every rolling experiment.

    Uses :func:`src.research.stable_signal_blend.build_blend_candidates` to
    produce the blend name rather than composing it manually — this guarantees
    the name matches what the blending pipeline actually produces.

    Parameters
    ----------
    ranker_name
        Full ranker name (default ``FROZEN_RANKER_NAME``).
    blend_weight
        Ranker weight for the single 50/50 blend (default 0.50).
    baseline_name
        Canonical baseline factor name.

    Returns
    -------
    dict[str, str]
        Keys ``"ranker"``, ``"blend"``, ``"baseline"`` mapping to the exact
        string names that must appear in the experiment candidates dict.
    """
    from src.research.stable_signal_blend import BlendWeight, build_blend_candidates

    # Use build_blend_candidates to produce the contract-correct blend name.
    # The function requires a valid MultiIndex with datetime/instrument levels
    # and a same-date cross-section, but the actual values are irrelevant.
    _dummy_idx = pd.MultiIndex.from_tuples(
        [("2024-01-02", "SYM_A"), ("2024-01-02", "SYM_B")],
        names=["datetime", "instrument"],
    )
    _dummy_score = pd.DataFrame({"score": [0.1, -0.2]}, index=_dummy_idx)

    weight = BlendWeight(ranker_weight=blend_weight, momentum_weight=1.0 - blend_weight)
    blends = build_blend_candidates(
        {ranker_name: _dummy_score},
        _dummy_score,
        weights=[weight],
    )
    blend_name = next(iter(blends))  # single entry

    return {
        "ranker": ranker_name,
        "blend": blend_name,
        "baseline": baseline_name,
    }


# ══════════════════════════════════════════════════════════════════════════
# Input validation: reject all-NaN / zero-filled manufactured inputs
# ══════════════════════════════════════════════════════════════════════════


def validate_no_nan_inputs(
    data: pd.DataFrame,
    *,
    context: str = "unknown",
    min_valid_ratio: float = 0.01,
) -> tuple[bool, str | None]:
    """Check that *data* contains usable (non-NaN, non-zero-filled) values.

    Returns ``(True, None)`` when data is usable.  Returns ``(False, reason)``
    when the data is all-NaN, zero-filled-from-NaN, or below the minimum
    fraction of valid observations — the caller should **skip** the universe
    or window rather than manufacturing inputs.

    Parameters
    ----------
    data
        DataFrame to validate (typically features, scores, or returns).
    context
        Human-readable label for error messages (e.g. ``"features"``,
        ``"raw_returns"``).
    min_valid_ratio
        Minimum fraction of non-NaN, non-zero values required (default 0.01).

    Returns
    -------
    tuple[bool, str | None]
    """
    if data is None or data.size == 0:
        return False, f"{context}: empty data — cannot evaluate"

    values = data.values.ravel()
    if not np.isfinite(values).any():
        return False, f"{context}: all values are NaN or Inf — cannot evaluate"

    finite = values[np.isfinite(values)]
    valid_ratio = float((finite != 0.0).mean())

    if valid_ratio < min_valid_ratio:
        # Distinguish true all-NaN from zero-filled (all zeros after NaN fill)
        if (finite == 0.0).all():
            return False, (
                f"{context}: all finite values are zero (likely NaN→0 fill) — "
                f"refusing to manufacture model inputs"
            )
        return False, (
            f"{context}: only {valid_ratio:.4%} valid non-zero values "
            f"(below {min_valid_ratio:.0%} threshold) — skipping"
        )

    return True, None


# ══════════════════════════════════════════════════════════════════════════
# default_universe_specs – always returns exactly three named specs
# ══════════════════════════════════════════════════════════════════════════


def default_universe_specs(
    session_symbols: list[str],
    *,
    market: str = "us",
    watchlist_path: str | None = None,
    watchlist_symbols: list[str] | None = None,
    qlib_symbols: list[str] | None = None,
) -> list[UniverseSpec]:
    """Build the three standard universe specs in small→large order.

    Parameters
    ----------
    session_symbols
        Symbols from the active session (typically 10).
    market
        Market key for local instrument lookups (default ``"us"``).
    watchlist_path
        Optional explicit path to a watchlist YAML file.
    watchlist_symbols
        Pre-discovered watchlist/instrument symbols.  When omitted the
        function discovers them from local sources.
    qlib_symbols
        Pre-discovered Qlib instrument symbols.  When omitted the function
        discovers them from Qlib (silently falling back to an empty list).

    Returns
    -------
    list[UniverseSpec]
        Always exactly three entries, in nested-total order:

        ``default_10_symbols``
            The deduplicated session symbols (up to 10).  *min_symbols* = 8.
        ``expanded_50_symbols``
            Contains *default_10_symbols* plus locally-discovered symbols up
            to exactly 50 total (not 50 additions).  *min_symbols* = 50.
        ``expanded_100_symbols``
            Contains *expanded_50_symbols* plus locally-discovered symbols up
            to exactly 100 total (not 100 additions).  *min_symbols* = 100.

        Each tier is a strict superset of the prior tier.  When local
        discovery yields too few symbols the expanded specs are still present
        — the coverage layer will mark them skipped rather than fabricating
        tickers.
    """
    # Discover local symbols when not provided
    if watchlist_symbols is None:
        watchlist_symbols = _discover_watchlist_symbols(market, watchlist_path)
    if qlib_symbols is None:
        qlib_symbols = _discover_qlib_symbols(market)

    session_tuple = tuple(sorted(set(session_symbols)))

    # Combine all local sources for the expanded universes
    all_local = sorted(set(watchlist_symbols + qlib_symbols))

    # Nested construction: each tier contains the prior tier plus new symbols.
    # expanded_50: session symbols + local symbols (excluding session) up to exactly 50 total
    expanded_50_base = [s for s in all_local if s not in session_tuple]
    expanded_50 = list(session_tuple) + expanded_50_base
    expanded_50 = expanded_50[:50]

    # expanded_100: expanded_50 symbols + more local symbols up to exactly 100 total
    expanded_50_set = set(expanded_50)
    expanded_100_base = [s for s in all_local if s not in expanded_50_set]
    expanded_100 = list(expanded_50) + expanded_100_base
    expanded_100 = expanded_100[:100]

    return [
        UniverseSpec(name="default_10_symbols", symbols=session_tuple, min_symbols=8),
        UniverseSpec(name="expanded_50_symbols", symbols=tuple(expanded_50), min_symbols=50),
        UniverseSpec(name="expanded_100_symbols", symbols=tuple(expanded_100), min_symbols=100),
    ]


# ══════════════════════════════════════════════════════════════════════════
# filter_universe_by_coverage – structured fail-closed coverage report
# ══════════════════════════════════════════════════════════════════════════


def filter_universe_by_coverage(
    requested_symbols: tuple[str, ...],
    available_symbols: set[str] | None = None,
    *,
    min_symbols: int,
    date_range: tuple[str, str] | None = None,
    date_coverage_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check coverage and return a structured report.

    When *date_coverage_data* is supplied the function validates that each
    symbol has actual data covering the required *date_range* (the tolerance
    is pre-applied by :func:`load_symbol_date_coverage` via
    ``_MAX_CALENDAR_BOUNDARY_GAP_DAYS``).  Symbols with insufficient date
    coverage are dropped alongside symbols absent from *available_symbols*.

    When *date_coverage_data* is ``None`` the function falls back to a
    name-based membership check against *available_symbols*.

    Drops symbols missing from *available_symbols* and reports the outcome.
    When fewer than *min_symbols* remain the universe is marked **skipped**
    and **retained_symbols** is emptied — an insufficient universe can never
    provide symbols for downstream evidence.

    Returns
    -------
    dict
        ``requested_symbols``
            Sorted requested list.
        ``available_symbols``
            Sorted available list (derived from date_coverage_data when
            supplied, otherwise the *available_symbols* parameter).
        ``retained_symbols``
            Sorted intersecting symbols, or **empty** when insufficient.
        ``dropped_symbols``
            Sorted symbols that were requested but not available.
        ``coverage_ratio``
            ``len(retained) / len(requested)`` (unrounded when insufficient,
            the ratio reflects the raw intersection count before zeroing).
        ``date_coverage``
            Per-symbol coverage records (when *date_coverage_data* is
            supplied), keyed by symbol with ``first_valid_date``,
            ``last_valid_date``, ``observations``, ``sufficient_coverage``.
            Symbols not present receive ``None`` entries.
        ``sufficient``
            ``True`` when retained count >= *min_symbols*.
        ``skipped``
            ``True`` when insufficient (convenience negation).
        ``skip_reason``
            Human-readable reason when skipped, else ``None``.
    """
    requested = sorted(set(requested_symbols))

    # ── Determine availability ───────────────────────────────────────────
    # When date_coverage_data is provided, derive availability from actual
    # data; otherwise fall back to name-based membership.
    if date_coverage_data is not None:
        # Symbols with sufficient_coverage = True are available
        available = sorted(
            s for s in requested
            if s in date_coverage_data and date_coverage_data[s].get("sufficient_coverage")
        )
        available_set = set(available)
    elif available_symbols is not None:
        available_set = set(available_symbols)
        available = sorted(available_set)
    else:
        available = []
        available_set = set()

    retained_raw = sorted(set(requested) & available_set)
    dropped = sorted(set(requested) - available_set)
    n_requested = len(requested)
    n_retained = len(retained_raw)
    coverage_ratio = n_retained / n_requested if n_requested else 0.0
    sufficient = n_retained >= min_symbols

    # Fail-closed: insufficient universes must not leak retained symbols
    retained = retained_raw if sufficient else []

    skip_reason: str | None = None
    if not sufficient:
        if n_requested == 0:
            skip_reason = "no symbols requested"
        elif date_coverage_data is not None:
            skip_reason = (
                f"insufficient date coverage: {n_retained}/{n_requested} symbols "
                f"have usable data spanning the evaluation range "
                f"(need >= {min_symbols})"
            )
        else:
            skip_reason = (
                f"insufficient symbols: {n_retained}/{n_requested} available "
                f"(need >= {min_symbols})"
            )

    report: dict[str, Any] = {
        "requested_symbols": requested,
        "available_symbols": available,
        "retained_symbols": retained,
        "dropped_symbols": dropped,
        "coverage_ratio": round(coverage_ratio, 4),
        "sufficient": sufficient,
        "skipped": not sufficient,
        "skip_reason": skip_reason,
    }
    if date_range is not None:
        report["date_range"] = {"start": date_range[0], "end": date_range[1]}

    # Per-symbol date coverage when available
    if date_coverage_data is not None:
        per_symbol: dict[str, Any] = {}
        for s in requested:
            if s in date_coverage_data:
                rec = dict(date_coverage_data[s])
            else:
                rec = {
                    "first_valid_date": None,
                    "last_valid_date": None,
                    "observations": 0,
                    "covers_train_start": False,
                    "covers_test_end": False,
                    "sufficient_coverage": False,
                }
            per_symbol[s] = rec
        report["date_coverage"] = per_symbol

    return report


def check_universe_coverage(
    requested_symbols: tuple[str, ...],
    available_symbols: set[str] | None = None,
    *,
    min_symbols: int,
    date_range: tuple[str, str] | None = None,
    date_coverage_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compatibility alias — delegates to :func:`filter_universe_by_coverage`.

    Returns the same field names as the original API (``requested_count``,
    ``retained``, ``dropped``, etc.) for callers that have not yet migrated.
    """
    report = filter_universe_by_coverage(
        requested_symbols,
        available_symbols,
        min_symbols=min_symbols,
        date_range=date_range,
        date_coverage_data=date_coverage_data,
    )
    return {
        "requested_count": len(report["requested_symbols"]),
        "available_count": len(report["available_symbols"]),
        "retained_count": len(report["retained_symbols"]),
        "dropped_count": len(report["dropped_symbols"]),
        "coverage_ratio": report["coverage_ratio"],
        "retained": report["retained_symbols"],
        "dropped": report["dropped_symbols"],
        "min_symbols": min_symbols,
        "sufficient": report["sufficient"],
        "skipped": report["skipped"],
        "skip_reason": report.get("skip_reason"),
        "date_coverage": report.get("date_coverage"),
    }


# ══════════════════════════════════════════════════════════════════════════
# Gate helpers for summarize_universe_robustness
# ══════════════════════════════════════════════════════════════════════════

_MIN_ICIR: float = 0.30
_MIN_DRAWDOWN: float = -0.15
_MIN_READY_RATIO: float = 0.75
_STRONGER_ICIR: float = 0.20


def _check_gates(
    mean_icir: float | None,
    worst_drawdown: float | None,
    ready_ratio: float | None,
) -> list[str]:
    """Return alphabetically-sorted list of gate names that fail.

    Gates (all required for trade readiness):

    * ``mean_icir`` — ``>= 0.30``
    * ``worst_drawdown`` — ``>= -0.15``
    * ``ready_ratio`` — ``>= 0.75``
    """
    failed: list[str] = []
    if mean_icir is None or mean_icir < _MIN_ICIR:
        failed.append("mean_icir")
    if worst_drawdown is None or worst_drawdown < _MIN_DRAWDOWN:
        failed.append("worst_drawdown")
    if ready_ratio is None or ready_ratio < _MIN_READY_RATIO:
        failed.append("ready_ratio")
    failed.sort()
    return failed


# ══════════════════════════════════════════════════════════════════════════
# summarize_universe_robustness
# ══════════════════════════════════════════════════════════════════════════


def summarize_universe_robustness(
    per_universe_results: dict[str, dict[str, Any]],
    *,
    research_label_prefix: str = "blend:",
) -> dict[str, Any]:
    """Compare the fixed blend row across universes.

    Each per-universe result should be the dict returned by
    ``summarize_walk_forward_reports`` (or ``None`` for skipped universes).
    Instead of searching for an arbitrary "best" candidate, the function
    locates the fixed research blend candidate (identified by
    *research_label_prefix*) and evaluates its metrics against every gate.

    Decision gates (all required for **trade readiness**):

    * ``mean_icir >= 0.30``
    * ``worst_drawdown >= -0.15``
    * ``ready_ratio >= 0.75``

    **Stronger research** requires *mean_icir >= 0.20* **and**
    *worst_drawdown >= -0.15*.
    """
    # ------------------------------------------------------------------
    # Helper: locate the fixed research blend within a walk-forward summary
    # ------------------------------------------------------------------
    def _find_blend_candidate(summary: dict[str, Any]) -> dict[str, Any] | None:
        candidates = summary.get("candidates", [])
        # 1. Look for a candidate whose label starts with research_label_prefix
        for c in candidates:
            cname = str(c.get("candidate", ""))
            if cname.startswith(research_label_prefix):
                return dict(c)
        # 2. Fallback: first stable research candidate
        stable = [c for c in candidates if c.get("stable_research_candidate")]
        if stable:
            return dict(stable[0])
        # 3. Last resort: first candidate
        if candidates:
            return dict(candidates[0])
        return None

    universe_rows: list[dict[str, Any]] = []
    skipped_universes: list[str] = []

    for universe_name, summary in sorted(per_universe_results.items()):
        if summary is None:
            skipped_universes.append(universe_name)
            universe_rows.append(
                {
                    "universe": universe_name,
                    "status": "skipped",
                    "blend_candidate": None,
                    "mean_icir": None,
                    "worst_drawdown": None,
                    "ready_ratio": None,
                    "failed_gates": ["mean_icir", "worst_drawdown", "ready_ratio"],
                    "n_windows": 0,
                    "n_candidates": 0,
                }
            )
            continue

        blend = _find_blend_candidate(summary)

        if blend is None:
            skipped_universes.append(universe_name)
            universe_rows.append(
                {
                    "universe": universe_name,
                    "status": "skipped",
                    "blend_candidate": None,
                    "mean_icir": None,
                    "worst_drawdown": None,
                    "ready_ratio": None,
                    "failed_gates": ["mean_icir", "worst_drawdown", "ready_ratio"],
                    "n_windows": int(summary.get("n_reports", 0)),
                    "n_candidates": int(summary.get("n_candidates", 0)),
                }
            )
            continue

        mean_icir = float(blend.get("mean_icir", 0.0))
        worst_drawdown = float(blend.get("worst_drawdown", 0.0))
        ready_ratio = float(blend.get("ready_ratio", 0.0))
        gates = _check_gates(mean_icir, worst_drawdown, ready_ratio)

        universe_rows.append(
            {
                "universe": universe_name,
                "status": "evaluated",
                "blend_candidate": str(blend.get("candidate")),
                "mean_icir": mean_icir,
                "worst_drawdown": worst_drawdown,
                "ready_ratio": ready_ratio,
                "failed_gates": gates,
                "n_windows": int(summary.get("n_reports", 0)),
                "n_candidates": int(summary.get("n_candidates", 0)),
            }
        )

    # ── overall decision ──────────────────────────────────────────────
    evaluated = [r for r in universe_rows if r["status"] == "evaluated" and r["mean_icir"] is not None]
    decision_status = "no_universe_evaluated"
    trade_ready = False

    if evaluated:
        best = max(
            evaluated,
            key=lambda r: (
                float(r["mean_icir"] or 0.0),
                float(r["ready_ratio"] or 0.0),
                float(r["worst_drawdown"] or -999.0),
            ),
        )
        best_icir = float(best["mean_icir"] or 0.0)
        best_drawdown = float(best["worst_drawdown"] or 0.0)
        best_gates = best.get("failed_gates", [])

        if len(best_gates) == 0:
            decision_status = "universe_robust_research_candidate"
            trade_ready = True
        elif best_icir >= _STRONGER_ICIR and best_drawdown >= _MIN_DRAWDOWN:
            decision_status = "universe_stronger_research_candidate"
        else:
            decision_status = "universe_research_candidate"
    else:
        best = None

    return {
        "schema_version": "1.0",
        "n_universes": len(per_universe_results),
        "n_evaluated": len(evaluated),
        "n_skipped": len(skipped_universes),
        "skipped_universes": skipped_universes,
        "universe_rows": universe_rows,
        "decision_status": decision_status,
        "trade_ready": trade_ready,
        "best_universe": best,
        "stronger_research_icir": _STRONGER_ICIR,
        "trade_icir": _MIN_ICIR,
        "min_ready_ratio": _MIN_READY_RATIO,
        "min_drawdown": _MIN_DRAWDOWN,
        "non_trade_ready_warning": (
            "Research evidence is not authorization for live trading or automated execution. "
            "Universe-robustness results require all decision gates to pass: "
            "mean_icir >= 0.30, worst_drawdown >= -0.15, ready_ratio >= 0.75."
        ),
        "recommended_next_step": (
            "Expand data coverage, improve universe construction quality, enhance feature/factor "
            "quality, and validate regime/label robustness before any trade-guidance claim."
        ),
    }
