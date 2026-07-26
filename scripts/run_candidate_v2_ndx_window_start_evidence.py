"""Candidate v2 Nasdaq-100 window-start point-in-time universe evidence.

This runner evaluates the frozen PR #175 candidate — 50/50 daily-ranker +
inverted 10D momentum score, Top-3 equal weight, 20 bps cash-inclusive one-way
turnover, 50% gross exposure when QQQ historical 20D return is negative —
against four half-year OOS windows where **each window freezes the official
Nasdaq-100 membership known at that window start** for the test set, and uses
**semiannual as-of membership** for the training set.

Unlike the static 10/50/100 cohorts in the universe-robustness experiment, this
runner uses committed point-in-time NDX membership snapshots from the official
Nasdaq endpoint.  For each OOS window the ranker is re-trained on expanding
history where training membership is built from every semiannual snapshot on
or before each training date — no future-OOS-snapshot leakage.

Key properties
--------------
* ``training_membership_asof_semiannual=True`` — training membership uses the
  latest semiannual NDX snapshot on or before each training date.
* ``training_uses_future_oos_snapshot=False`` — training never sees the future
  OOS-window snapshot.
* ``full_daily_point_in_time=False`` — membership is refreshed semiannually,
  not daily.
* ``oos_membership_point_in_time=True`` — the OOS test set uses symbols frozen
  at window start per the official Nasdaq listing.
* ``membership_coverage_complete`` — set to ``True`` only when **every** official
  NDX symbol at a window start is covered by the provider and retained.

Output is written under ``artifacts/evidence/candidate_v2_ndx_window_start/``.

Always:
* research_only=True
* promotion_eligible=False
* trade_ready=False
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_candidate_v2_universe_robustness import (
    EXCLUDED_SYMBOLS,
    FROZEN_BLEND_WEIGHT,
    FROZEN_CALIBRATION,
    FROZEN_COST_BPS,
    FROZEN_EXPOSURE,
    FROZEN_FEATURE_GROUP,
    FROZEN_TOP_N,
    MAX_DRAWDOWN_GATE,
    MIN_COMPOUNDED_RELATIVE_EXCESS,
    MIN_POSITIVE_EXCESS_WINDOWS,
    REQUIRED_WINDOWS,
    _candidate_id,
    _evaluate_window,
    _exclude_benchmark_symbols,
    _load_session,
    _load_us_provider_symbols,
    _verify_us_provider,
)
from src.research.market_data_alignment import get_aligned_windows
from src.research.ndx_window_start_universe import (
    DEFAULT_SNAPSHOT_PATH,
    NdxSnapshotDate,
    NdxWindowStartSnapshot,
    get_snapshot_by_date,
    intersect_with_provider,
    load_snapshot,
    resolve_latest_snapshot_on_or_before,
)
from src.research.notebook_research_api import sanitize_factor_name
from src.research.rolling_windows import RollingResearchWindow
from src.research.selection_tail_diagnostics import summarize_window_diagnostics
from src.research.universe_robustness import (
    filter_universe_by_coverage,
    load_symbol_date_coverage,
)

# ══════════════════════════════════════════════════════════════════════════════
# Window-start → snapshot date mapping
# ══════════════════════════════════════════════════════════════════════════════

# Which NDX snapshot to use for each OOS window label.
# The snapshot date is the first trading day of the half-year period.
WINDOW_SNAPSHOT_MAP: dict[str, str] = {
    "2024H1": "2024-01-02",
    "2024H2": "2024-07-01",
    "2025H1": "2025-01-02",
    "2025H2": "2025-07-01",
}

# A Nasdaq-100 validation that retains fewer than half the index is too
# incomplete to support a useful universe-robustness conclusion.
MIN_WINDOW_SYMBOLS = 50

# Training-membership approach for evidence metadata.
TRAINING_MEMBERSHIP_APPROACH = "asof_semiannual"
TRAINING_USES_FUTURE_OOS_SNAPSHOT = False


# ══════════════════════════════════════════════════════════════════════════════
# Per-window evaluation
# ══════════════════════════════════════════════════════════════════════════════


def _evaluate_ndx_window(
    window: Any,
    benchmark: str,
    expression_columns: dict[str, str],
    feature_exprs: list[str],
    baseline_expr: str,
    snapshot: NdxWindowStartSnapshot,
    provider_set: set[str],
) -> dict[str, Any] | None:
    """Train frozen ranker with semiannual as-of membership, evaluate on OOS window.

    This function:
    1. Resolves the OOS test symbols from the window-start snapshot.
    2. Collects every semiannual snapshot on or before ``window.train_end``
       to build the training-symbol union.
    3. Derives an aligned training start from the 50th-earliest first-valid
       date among all training-union symbols (NOT the latest first-valid).
    4. Retains training symbols whose provider data fully covers the aligned
       start through train_end; retains test symbols whose data covers the
       test window.
    5. Delegates model fitting/backtest to the shared ``_evaluate_window``
       helper with distinct training/test symbols and an as-of membership
       snapshot so that training rows are filtered by the membership known
       on or before each training date.
    6. Wraps the result with per-window membership coverage metadata.

    Parameters
    ----------
    window
        A ``RollingResearchWindow`` from ``get_aligned_windows``.
    benchmark
        Benchmark symbol (e.g. ``"QQQ"``).
    expression_columns / feature_exprs / baseline_expr
        Frozen feature configuration forwarded to ``_evaluate_window``.
    snapshot
        The full committed NDX membership snapshot.
    provider_set
        Set of US-provider-covered symbols.

    Returns
    -------
    dict or None
        Window payload with candidate_v2 result, score diagnostics, and
        coverage metadata, or ``None`` if skipped.
    """
    # ── OOS test symbols (window-start snapshot) ────────────────────────
    oos_snapshot_date_str = WINDOW_SNAPSHOT_MAP[window.label]
    oos_entry = get_snapshot_by_date(snapshot, oos_snapshot_date_str)
    oos_provider_report = intersect_with_provider(oos_entry, provider_set)
    oos_requested = oos_provider_report["requested"]
    oos_retained_raw = oos_provider_report["retained"]
    oos_tradable_raw = list(_exclude_benchmark_symbols(tuple(oos_retained_raw)))

    # ── Test-symbol date-coverage filter ─────────────────────────────────
    if not oos_tradable_raw:
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": "OOS snapshot has no tradable symbols after benchmark exclusion",
        }
    test_coverage = load_symbol_date_coverage(
        oos_tradable_raw,
        window.test_start,
        window.test_end,
    )
    test_coverage_filter = filter_universe_by_coverage(
        tuple(oos_tradable_raw),
        min_symbols=MIN_WINDOW_SYMBOLS,
        date_range=(window.test_start, window.test_end),
        date_coverage_data=test_coverage,
    )
    if test_coverage_filter.get("skipped", True):
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": test_coverage_filter.get(
                "skip_reason", "insufficient OOS test date coverage"
            ),
        }
    test_symbols = test_coverage_filter["retained_symbols"]
    if len(test_symbols) < MIN_WINDOW_SYMBOLS:
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": (
                f"fewer than {MIN_WINDOW_SYMBOLS} OOS test symbols retained "
                f"({len(test_symbols)})"
            ),
        }

    # ── Training-union symbols (all snapshots ≤ train_end) ───────────────
    training_snapshot_entries = sorted(
        [s for s in snapshot.snapshot_dates if s.date <= window.train_end],
        key=lambda s: s.date,
    )
    if not training_snapshot_entries:
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": (
                f"no NDX snapshots on or before train_end={window.train_end}"
            ),
        }
    training_snapshot_dates = [s.date for s in training_snapshot_entries]

    # Union of all provider-retained symbols across training snapshots
    train_official_union: set[str] = set()
    train_union: set[str] = set()
    per_snapshot_retained: dict[str, list[str]] = {}
    per_snapshot_requested: dict[str, int] = {}
    per_snapshot_missing: dict[str, list[str]] = {}
    for s in training_snapshot_entries:
        rep = intersect_with_provider(s, provider_set)
        train_official_union.update(_exclude_benchmark_symbols(s.symbols))
        retained = _exclude_benchmark_symbols(tuple(rep["retained"]))
        train_union.update(retained)
        per_snapshot_retained[s.date] = list(retained)
        per_snapshot_requested[s.date] = rep["n_requested"]
        per_snapshot_missing[s.date] = rep["missing"]

    train_union_list = sorted(train_union)
    if len(train_union_list) < MIN_WINDOW_SYMBOLS:
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": (
                f"training-union symbols ({len(train_union_list)}) below "
                f"minimum {MIN_WINDOW_SYMBOLS}"
            ),
        }

    # ── Aligned training start: 50th earliest first-valid date ──────────
    # Load coverage for every training-union symbol across the full range
    # so we can discover when each symbol's data actually begins.
    train_union_coverage = load_symbol_date_coverage(
        train_union_list,
        window.train_start,
        window.train_end,
    )
    first_valid_dates: list[str] = []
    for s in train_union_list:
        rec = train_union_coverage.get(s, {})
        fvd = rec.get("first_valid_date")
        if fvd is not None and int(rec.get("observations", 0)) > 0:
            first_valid_dates.append(str(fvd))

    if len(first_valid_dates) < MIN_WINDOW_SYMBOLS:
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": (
                f"only {len(first_valid_dates)} training-union symbols have "
                f"valid coverage data (need {MIN_WINDOW_SYMBOLS})"
            ),
        }

    first_valid_dates_sorted = sorted(first_valid_dates)
    aligned_train_start = first_valid_dates_sorted[MIN_WINDOW_SYMBOLS - 1]
    # The 50th-earliest first-valid date is the earliest point at which
    # at least 50 symbols have usable provider data.

    if pd.Timestamp(aligned_train_start) > pd.Timestamp(window.train_end):
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": (
                f"aligned training start {aligned_train_start} falls after "
                f"train_end {window.train_end}"
            ),
        }

    # ── Retain training symbols with full coverage in aligned range ─────
    aligned_train_coverage = load_symbol_date_coverage(
        train_union_list,
        aligned_train_start,
        window.train_end,
    )
    train_coverage_filter = filter_universe_by_coverage(
        tuple(train_union_list),
        min_symbols=MIN_WINDOW_SYMBOLS,
        date_range=(aligned_train_start, window.train_end),
        date_coverage_data=aligned_train_coverage,
    )
    if train_coverage_filter.get("skipped", True):
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": train_coverage_filter.get(
                "skip_reason", "insufficient training date coverage in aligned range"
            ),
        }
    train_symbols = train_coverage_filter["retained_symbols"]
    if len(train_symbols) < MIN_WINDOW_SYMBOLS:
        return {
            "window": window.to_dict(),
            "skipped": True,
            "skip_reason": (
                f"fewer than {MIN_WINDOW_SYMBOLS} training symbols retained "
                f"in aligned range ({len(train_symbols)})"
            ),
        }

    # ── Build aligned window ─────────────────────────────────────────────
    aligned_window = RollingResearchWindow(
        label=window.label,
        train_start=aligned_train_start,
        train_end=window.train_end,
        test_start=window.test_start,
        test_end=window.test_end,
    )

    # ── Delegate model fitting / backtest with as-of membership ─────────
    result = _evaluate_window(
        aligned_window,
        test_symbols,
        benchmark,
        expression_columns,
        feature_exprs,
        baseline_expr,
        train_symbols=train_symbols,
        asof_membership_snapshot=snapshot,
        asof_provider_symbols=provider_set,
    )
    if result is None:
        return None

    # ── Coverage metadata ────────────────────────────────────────────────
    n_retained_train = len(train_symbols)
    n_requested_train_union = len(train_official_union)
    n_provider_train_union = len(train_union_list)
    n_requested_oos = len(oos_requested)
    n_retained_oos = len(test_symbols)

    training_union_requested = n_requested_train_union
    training_date_retained = n_retained_train

    # Provider coverage may be incomplete when some snapshot symbols are
    # missing from the provider or filtered by date coverage.
    provider_coverage_incomplete = (
        any(per_snapshot_missing.values())
        or bool(oos_provider_report["missing"])
        or bool(test_coverage_filter["dropped_symbols"])
        or bool(train_coverage_filter["dropped_symbols"])
    )

    coverage_meta = {
        # OOS (test) membership
        "oos_snapshot_date": oos_snapshot_date_str,
        "oos_requested_symbols": oos_requested,
        "oos_provider_retained": oos_retained_raw,
        "oos_provider_missing": oos_provider_report["missing"],
        "oos_date_coverage_dropped": test_coverage_filter["dropped_symbols"],
        "oos_test_symbols": test_symbols,
        "oos_test_retained": len(test_symbols),
        "n_oos_requested": n_requested_oos,
        "n_oos_test_retained": n_retained_oos,
        # Training membership
        "training_snapshot_dates": training_snapshot_dates,
        "n_training_snapshots": len(training_snapshot_dates),
        "training_union_requested": training_union_requested,
        "training_union_provider_retained": n_provider_train_union,
        "training_date_retained": training_date_retained,
        "training_date_dropped": train_coverage_filter["dropped_symbols"],
        "training_symbols": train_symbols,
        "per_snapshot_requested": per_snapshot_requested,
        "per_snapshot_retained": {
            d: len(v) for d, v in per_snapshot_retained.items()
        },
        "per_snapshot_missing": per_snapshot_missing,
        "aligned_train_start": aligned_train_start,
        # Flags
        "training_membership_asof_semiannual": True,
        "training_uses_future_oos_snapshot": False,
        "full_daily_point_in_time": False,
        "provider_coverage_incomplete": provider_coverage_incomplete,
        "oos_membership_point_in_time": True,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        # Per-snapshot detail
        "per_snapshot_detail": {
            s.date: {
                "requested": per_snapshot_requested.get(s.date, 0),
                "retained": len(per_snapshot_retained.get(s.date, [])),
            }
            for s in training_snapshot_entries
        },
    }
    result["nominal_window"] = window.to_dict()
    result["coverage_meta"] = coverage_meta

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Aggregate windows
# ══════════════════════════════════════════════════════════════════════════════


def _aggregate_ndx_windows(
    window_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate per-window results into a cross-window summary."""
    valid = [p for p in window_payloads if not p.get("skipped", False)]
    n_windows = len(window_payloads)
    n_valid = len(valid)

    if n_valid == 0:
        return {
            "n_windows_total": n_windows,
            "n_windows_evaluated": 0,
            "skipped": True,
            "skip_reason": "no valid windows",
        }

    rel_excesses = [p["candidate_v2"]["relative_excess_return"] for p in valid]
    sharpes = [p["candidate_v2"]["sharpe_ratio"] for p in valid]
    drawdowns = [p["candidate_v2"]["max_drawdown"] for p in valid]
    turnovers = [p["candidate_v2"]["turnover"] for p in valid]
    costs = [p["candidate_v2"]["costs"] for p in valid]
    gross_exposures = [p["candidate_v2"]["mean_gross_exposure"] for p in valid]

    all_period_returns = [r for p in valid for r in p["candidate_v2"]["period_returns"]]
    all_bench_returns = [r for p in valid for r in p["candidate_v2"]["benchmark_period_returns"]]
    compounded_portfolio = float(np.prod(1.0 + np.asarray(all_period_returns)) - 1.0) if all_period_returns else 0.0
    compounded_benchmark = float(np.prod(1.0 + np.asarray(all_bench_returns)) - 1.0) if all_bench_returns else 0.0
    compounded_rel_excess = (
        (1.0 + compounded_portfolio) / (1.0 + compounded_benchmark) - 1.0
        if compounded_benchmark > -1.0
        else 0.0
    )

    ic_irs = [p["score_diagnostics"]["ic_ir"] for p in valid]
    rank_ic_irs = [p["score_diagnostics"]["rank_ic_ir"] for p in valid]
    ic_means = [p["score_diagnostics"]["ic_mean"] for p in valid]
    rank_ic_means = [p["score_diagnostics"]["rank_ic_mean"] for p in valid]
    spreads = [p["score_diagnostics"]["top_bottom_spread_mean"] for p in valid]

    def finite(values: list[float]) -> list[float]:
        return [v for v in values if np.isfinite(v)]

    def finite_mean(values: list[float]) -> float | None:
        usable = finite(values)
        return float(np.mean(usable)) if usable else None

    mean_ic = finite_mean(ic_means)
    mean_ic_ir = finite_mean(ic_irs)
    mean_rank_ic = finite_mean(rank_ic_means)
    mean_rank_ic_ir = finite_mean(rank_ic_irs)
    mean_spread = finite_mean(spreads)
    positive_excess_windows = sum(1 for e in rel_excesses if e > 0)
    worst_drawdown = float(min(drawdowns))

    gate_checks = {
        "exactly_four_windows": n_valid == REQUIRED_WINDOWS,
        "positive_excess_windows": (
            positive_excess_windows >= MIN_POSITIVE_EXCESS_WINDOWS
        ),
        "compounded_relative_excess": (
            compounded_rel_excess > MIN_COMPOUNDED_RELATIVE_EXCESS
        ),
        "worst_drawdown": worst_drawdown >= MAX_DRAWDOWN_GATE,
        "positive_mean_icir": mean_ic_ir is not None and mean_ic_ir > 0,
        "positive_mean_rank_icir": (
            mean_rank_ic_ir is not None and mean_rank_ic_ir > 0
        ),
        "positive_mean_top_bottom_spread": (
            mean_spread is not None and mean_spread > 0
        ),
    }
    failed_gates = [name for name, passed in gate_checks.items() if not passed]
    passes_gate = not failed_gates

    return {
        "n_windows_total": n_windows,
        "n_windows_evaluated": n_valid,
        "skipped": False,
        "candidate": _candidate_id(),
        "candidate_v2": {
            "compounded_total_return": compounded_portfolio,
            "compounded_benchmark_return": compounded_benchmark,
            "compounded_relative_excess_return": compounded_rel_excess,
            "mean_relative_excess": float(np.mean(rel_excesses)),
            "mean_sharpe": float(np.mean(sharpes)),
            "worst_drawdown": worst_drawdown,
            "mean_drawdown": float(np.mean(drawdowns)),
            "mean_turnover": float(np.mean(turnovers)),
            "mean_costs": float(np.mean(costs)),
            "cost_bps": FROZEN_COST_BPS,
            "turnover_model": "cash_inclusive_one_way",
            "mean_gross_exposure": float(np.mean(gross_exposures)),
            "min_gross_exposure": float(min(gross_exposures)),
            "max_gross_exposure": float(max(gross_exposures)),
            "positive_excess_windows": positive_excess_windows,
            "gate_thresholds": {
                "required_windows": REQUIRED_WINDOWS,
                "min_positive_excess_windows": MIN_POSITIVE_EXCESS_WINDOWS,
                "min_compounded_relative_excess": MIN_COMPOUNDED_RELATIVE_EXCESS,
                "max_drawdown": MAX_DRAWDOWN_GATE,
                "require_positive_mean_icir": True,
                "require_positive_mean_rank_icir": True,
                "require_positive_mean_top_bottom_spread": True,
            },
            "gate_checks": gate_checks,
            "failed_gates": failed_gates,
            "passes_candidate_v2_gate": passes_gate,
        },
        "score_diagnostics": {
            "mean_ic": mean_ic,
            "mean_ic_ir": mean_ic_ir,
            "mean_rank_ic": mean_rank_ic,
            "mean_rank_ic_ir": mean_rank_ic_ir,
            "mean_top_bottom_spread": mean_spread,
        },
        "selection_tail_diagnostics": summarize_window_diagnostics(
            [p.get("selection_tail_diagnostics", {}) for p in valid]
        ),
        "coverage_summary": {
            "snapshots_loaded": len(set(
                p["coverage_meta"]["oos_snapshot_date"] for p in valid
            )),
            "membership_coverage_complete": all(
                p["coverage_meta"].get("provider_coverage_incomplete", True) is False
                for p in valid
            ),
            "all_coverages_complete": all(
                p["coverage_meta"].get("provider_coverage_incomplete", True) is False
                for p in valid
            ),
            "training_membership_asof_semiannual": True,
            "training_uses_future_oos_snapshot": False,
            "full_daily_point_in_time": False,
            "per_window": {
                p["coverage_meta"]["oos_snapshot_date"]: {
                    "n_oos_requested": p["coverage_meta"]["n_oos_requested"],
                    "n_oos_test_retained": p["coverage_meta"]["n_oos_test_retained"],
                    "n_training_union_requested": p["coverage_meta"]["training_union_requested"],
                    "n_training_union_retained": p["coverage_meta"]["training_union_provider_retained"],
                    "n_training_date_retained": p["coverage_meta"]["training_date_retained"],
                    "aligned_train_start": p["coverage_meta"]["aligned_train_start"],
                    "n_training_snapshots": p["coverage_meta"]["n_training_snapshots"],
                    "provider_coverage_incomplete": p["coverage_meta"]["provider_coverage_incomplete"],
                }
                for p in valid
            },
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Comparison vs static-100 evidence
# ══════════════════════════════════════════════════════════════════════════════


def _build_comparison_vs_static_100(
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    """Compare NDX window-start result against the committed static-100 evidence.

    The static-100 reference values are taken from the corrected evidence run:
    relative excess 176.68%, mean Sharpe 1.51, worst DD -22.39%, mean ICIR .223,
    mean Rank ICIR .155.
    """
    cv2 = aggregate.get("candidate_v2", {})
    diag = aggregate.get("score_diagnostics", {})

    static_100 = {
        "compounded_relative_excess_return": 1.7668,
        "mean_sharpe": 1.51,
        "worst_drawdown": -0.2239,
        "mean_ic_ir": 0.223,
        "mean_rank_ic_ir": 0.155,
    }

    ndx_result = {
        "compounded_relative_excess_return": cv2.get("compounded_relative_excess_return"),
        "mean_sharpe": cv2.get("mean_sharpe"),
        "worst_drawdown": cv2.get("worst_drawdown"),
        "mean_ic_ir": diag.get("mean_ic_ir"),
        "mean_rank_ic_ir": diag.get("mean_rank_ic_ir"),
    }

    deltas: dict[str, float | None] = {}
    for key in static_100:
        s = static_100[key]
        n = ndx_result.get(key)
        if n is not None and isinstance(n, (int, float)) and np.isfinite(n):
            deltas[key] = round(float(n) - float(s), 4)
        else:
            deltas[key] = None

    return {
        "schema_version": "1.0",
        "comparison_label": "NDX window-start PIT universe vs static-100 universe",
        "static_100_source": "corrected evidence (66129d... provider, 100-symbol cohort)",
        "static_100_values": static_100,
        "ndx_window_start_values": ndx_result,
        "absolute_deltas": deltas,
        "note": (
            "Comparison is informational only.  The static-100 cohort uses "
            "current Qlib instrument listings (survivorship-biased), while the "
            "NDX window-start cohort uses committed Nasdaq-100 membership at "
            "each window start.  Differences reflect both membership coverage "
            "and point-in-time methodology."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Main runner
# ══════════════════════════════════════════════════════════════════════════════


def run(
    root: Path,
    *,
    data_root: Path | None = None,
    first_test_year: int = 2024,
    last_test_year: int = 2026,
    snapshot_path: Path | str = DEFAULT_SNAPSHOT_PATH,
) -> dict[str, Any]:
    """Execute the candidate_v2 NDX window-start evidence experiment."""
    session = _load_session(root)
    market = str(session["market"])
    benchmark = str(session["benchmark"])
    train_start = str(session["train_start"])
    test_end = str(session["test_end"])

    effective_data_root = data_root if data_root is not None else root

    # ── Verify US provider ─────────────────────────────────────────────────
    provider_manifest = _verify_us_provider(effective_data_root)
    from src.data.market_provider import market_provider_path

    provider_uri = str(market_provider_path(effective_data_root, "us"))

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    safe_qlib_init(
        build_qlib_init_cfg(None, market=market, provider_uri_default=provider_uri)
    )
    from qlib.data import D

    calendar = pd.DatetimeIndex(
        D.calendar(start_time=train_start, end_time=test_end, freq="day")
    )
    if calendar.empty:
        raise ValueError("Qlib calendar has no data in configured session range")
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")

    # ── Load NDX membership snapshot ───────────────────────────────────────
    resolved_snapshot_path = Path(snapshot_path)
    if not resolved_snapshot_path.is_absolute():
        resolved_snapshot_path = root / resolved_snapshot_path
    snapshot = load_snapshot(
        resolved_snapshot_path,
        validate_hashes=True,
        validate_source=True,
    )
    print(f"\nLoaded NDX membership snapshot: {resolved_snapshot_path}")
    for sd in snapshot.snapshot_dates:
        print(f"  {sd.date}: {sd.count} symbols  hash={sd.sha256_membership_hash}")

    # ── Load provider symbols ──────────────────────────────────────────────
    provider_symbols_list = _load_us_provider_symbols(effective_data_root)
    provider_set = set(provider_symbols_list)
    print(f"\nProvider symbols: {len(provider_set)} US tradable tickers")

    # ── Snapshot coverage report (all dates, informational) ────────────────
    membership_readiness: dict[str, Any] = {}
    for sd in snapshot.snapshot_dates:
        inter = intersect_with_provider(sd, provider_set)
        membership_readiness[sd.date] = inter
        flag = "COMPLETE" if inter["complete"] else "PARTIAL"
        print(f"  [{flag}] {sd.date}: {inter['n_retained']}/{inter['n_requested']} "
              f"retained ({inter['coverage_ratio']:.1%})")

    # ── Output directories ─────────────────────────────────────────────────
    base_out = root / "artifacts" / "evidence" / "candidate_v2_ndx_window_start"
    per_window_dir = base_out / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)

    print("\nCandidate v2 NDX Window-Start Evidence")
    print(f"  market:       {market}")
    print(f"  benchmark:    {benchmark}")
    print(f"  data-root:    {effective_data_root}")
    print(f"  provider:     {provider_uri}")
    print(f"  output:       {base_out}")
    print("  research_only: true")
    print("  promotion_eligible: false")
    print("  trade_ready: false")
    print("  training_membership: asof_semiannual")
    print("  training_uses_future_oos_snapshot: false")
    print()

    # ── Feature expressions ────────────────────────────────────────────────
    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {expr: sanitize_factor_name(expr) for expr in feature_exprs}
    dollar_sign = chr(36)
    baseline_expr = f"{dollar_sign}close/Ref({dollar_sign}close,10)-1"

    # ── Write membership readiness ─────────────────────────────────────────
    readiness_path = base_out / "membership_readiness.json"
    readiness_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "evidence_type": "candidate_v2_ndx_membership_readiness",
                "provider": {
                    "uri": provider_uri,
                    "market": provider_manifest["market"],
                    "identity_sha256": provider_manifest["provider_identity_sha256"],
                },
                "membership_coverage": membership_readiness,
                "note": (
                    "Official NDX window-start symbols intersected with "
                    "actually-covered US provider symbols."
                ),
                "training_membership_approach": TRAINING_MEMBERSHIP_APPROACH,
                "training_uses_future_oos_snapshot": TRAINING_USES_FUTURE_OOS_SNAPSHOT,
            },
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"  readiness: {readiness_path}")

    # ── Per-window evaluation ──────────────────────────────────────────────
    windows = get_aligned_windows(
        train_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    if len(windows) != REQUIRED_WINDOWS:
        raise ValueError(
            f"requires exactly {REQUIRED_WINDOWS} complete OOS windows, "
            f"found {len(windows)}"
        )

    window_payloads: list[dict[str, Any]] = []
    for window in windows:
        ndx_date = WINDOW_SNAPSHOT_MAP.get(window.label)
        if ndx_date is None:
            print(f"  SKIP {window.label}: no NDX snapshot mapped")
            continue

        # Quick pre-check: OOS snapshot must have tradable symbols
        get_snapshot_by_date(snapshot, ndx_date)
        oos_rep = membership_readiness[ndx_date]
        oos_tradable = _exclude_benchmark_symbols(tuple(oos_rep["retained"]))
        if len(oos_tradable) < max(2, FROZEN_TOP_N):
            print(f"  SKIP {window.label}: insufficient OOS tradable symbols "
                  f"({len(oos_tradable)} after benchmark exclusion)")
            continue

        # Count training snapshots for this window
        n_train_snaps = sum(
            1 for s in snapshot.snapshot_dates if s.date <= window.train_end
        )

        print(f"\n── {window.label}  OOS snapshot={ndx_date}  "
              f"training snapshots={n_train_snaps} ──")
        print(f"  train={window.train_start}->{window.train_end}  "
              f"test={window.test_start}->{window.test_end}")

        payload = _evaluate_ndx_window(
            window,
            benchmark,
            expression_columns,
            feature_exprs,
            baseline_expr,
            snapshot,
            provider_set,
        )
        if payload is None:
            continue

        window_payloads.append(payload)

        if payload.get("skipped"):
            print(f"    SKIPPED: {payload.get('skip_reason', 'unknown')}")
        else:
            cv2 = payload["candidate_v2"]
            diag = payload["score_diagnostics"]
            cm = payload["coverage_meta"]
            print(
                f"    cv2: rel_xs={cv2['relative_excess_return']:.4f}  "
                f"SR={cv2['sharpe_ratio']:.2f}  MDD={cv2['max_drawdown']:.4f}  "
                f"IC_IR={diag['ic_ir']:.3f}  Rank_IC_IR={diag['rank_ic_ir']:.3f}  "
                f"train_sym={cm['training_date_retained']}  "
                f"test_sym={cm['oos_test_retained']}"
            )

        out_path = per_window_dir / f"ndx_window_start_{window.label}.json"
        out_path.write_text(
            json.dumps(
                payload,
                sort_keys=True,
                default=str,
                allow_nan=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    # ── Aggregate ──────────────────────────────────────────────────────────
    aggregate = _aggregate_ndx_windows(window_payloads)
    agg_path = base_out / "aggregate.json"
    agg_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "evidence_type": "candidate_v2_ndx_window_start",
                "candidate": _candidate_id(),
                "research_only": True,
                "promotion_eligible": False,
                "trade_ready": False,
                "training_membership_asof_semiannual": True,
                "training_uses_future_oos_snapshot": False,
                "full_daily_point_in_time": False,
                "oos_membership_point_in_time": True,
                "aggregate": aggregate,
            },
            sort_keys=True,
            default=str,
            allow_nan=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"\n  aggregate: {agg_path}")

    # ── Comparison vs static-100 ───────────────────────────────────────────
    comparison = _build_comparison_vs_static_100(aggregate)
    comp_path = base_out / "comparison_vs_static_100.json"
    comp_path.write_text(
        json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    print(f"  comparison: {comp_path}")

    # ── Evidence manifest ──────────────────────────────────────────────────
    cv2 = aggregate.get("candidate_v2", {})
    passes = cv2.get("passes_candidate_v2_gate", False)
    membership_complete = aggregate.get("coverage_summary", {}).get(
        "membership_coverage_complete", False
    )

    # Determine promotion eligibility
    # A model-gate pass with incomplete coverage is promising-but-incomplete
    promotion_label: str = "not_promoted"
    if not passes:
        promotion_label = "gate_not_passed"
    elif not membership_complete:
        promotion_label = "promising_but_incomplete"

    decision_status: str = "ndx_window_start_not_evaluated"
    if aggregate.get("skipped", False):
        decision_status = "ndx_window_start_skipped"
    elif passes and membership_complete:
        decision_status = "ndx_window_start_gate_passed"
    elif passes and not membership_complete:
        decision_status = "ndx_window_start_promising_but_incomplete"
    else:
        decision_status = "ndx_window_start_gate_failed"

    manifest = {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_ndx_window_start",
        "candidate": _candidate_id(),
        "frozen_from_pr": 175,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "training_membership_asof_semiannual": True,
        "training_uses_future_oos_snapshot": False,
        "full_daily_point_in_time": False,
        "oos_membership_point_in_time": True,
        "membership_coverage_complete": membership_complete,
        "cost_bps": FROZEN_COST_BPS,
        "turnover_model": "cash_inclusive_one_way",
        "n_windows": len(windows),
        "n_windows_evaluated": aggregate.get("n_windows_evaluated", 0),
        "passes_candidate_v2_gate": passes,
        "failed_gates": cv2.get("failed_gates", []),
        "promotion_label": promotion_label,
        "decision_status": decision_status,
        "provider_uri": provider_uri,
        "provider_identity_sha256": provider_manifest["provider_identity_sha256"],
        "membership_source": "committed_ndx_window_start_snapshot",
        "membership_source_path": str(resolved_snapshot_path),
        "survivorship_bias_documented": True,
        "point_in_time_notes": {
            "training_membership_asof_semiannual": (
                "Training membership is resolved from the latest semiannual "
                "NDX snapshot on or before each training date"
            ),
            "training_uses_future_oos_snapshot": (
                "Training never uses the future OOS-window snapshot — "
                "membership is strictly as-of each training date"
            ),
            "full_daily_point_in_time": (
                "Membership refreshes semiannually, not daily — true daily "
                "point-in-time would require daily Nasdaq records"
            ),
            "oos_membership_point_in_time": "OOS test set uses NDX membership frozen at window start",
            "membership_coverage_complete": (
                "True only if every official NDX symbol at every used snapshot "
                "is retained by provider coverage"
            ),
        },
    }
    manifest_path = base_out / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    print(f"  manifest: {manifest_path}")

    print("\n── Decision ──")
    print(f"  status:        {decision_status}")
    print(f"  gate:          {'PASS' if passes else 'FAIL'}")
    print(f"  promotion:     {promotion_label}")
    print(f"  coverage:      {'complete' if membership_complete else 'partial'}")

    return {
        "readiness_path": str(readiness_path),
        "per_window_dir": str(per_window_dir),
        "agg_path": str(agg_path),
        "comp_path": str(comp_path),
        "manifest_path": str(manifest_path),
        "aggregate": aggregate,
        "comparison": comparison,
        "manifest": manifest,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Project root directory",
    )
    parser.add_argument(
        "--data-root", type=Path, default=None,
        help="Read-only data root (Qlib provider URI = <data-root>/data/providers/us)",
    )
    parser.add_argument(
        "--first-test-year", type=int, default=2024,
        help="First OOS test year",
    )
    parser.add_argument(
        "--last-test-year", type=int, default=2026,
        help="Last OOS test year",
    )
    parser.add_argument(
        "--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT_PATH,
        help="Path to committed NDX membership snapshot JSON",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run(
        args.root,
        data_root=args.data_root,
        first_test_year=args.first_test_year,
        last_test_year=args.last_test_year,
        snapshot_path=args.snapshot_path,
    )
    print(f"\n  readiness: {result['readiness_path']}")
    print(f"  aggregate: {result['agg_path']}")
    print(f"  manifest:  {result['manifest_path']}")


if __name__ == "__main__":
    main()
