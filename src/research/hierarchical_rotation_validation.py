"""Authoritative validation of frozen US hierarchical cross-sectional rotation v2.

Produces after-cost evidence for four predeclared baselines against observed
data, with fail-closed provider/symbol/coverage checks and conservative gates.
All rows >= 2026-07-01 are reserved and excluded before any computation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.focus_watchlist_signal import (
    canonical_sha256,
    generate_signal_history,
    load_long_ohlcv_csv,
    sha256_file,
)
from src.research.hierarchical_pool_rotation import (
    BASKET_SCORE_FIELDS,
    SECURITY_SCORE_FIELDS,
    _candidate_symbols,
    _rank_percentile,
    _repository_root,
    build_hierarchical_portfolio_history,
    build_hierarchical_rotation_history,
    build_runtime_timing_spec,
    compute_hierarchical_indicators,
    load_hierarchical_contract,
)
from src.research.research_artifacts import write_json

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load_prices_raw(path: Path) -> pd.DataFrame:
    """Load OHLCV CSV returning raw provider symbols (no alias mapping)."""
    df = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "symbol", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Prices CSV missing columns: {sorted(missing)}")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _load_observed_slice(
    prices_csv: Path, reserved_start: pd.Timestamp
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load raw prices, return observed-only DataFrame and partial slice identity.

    This is the FIRST data-boundary operation — applied before alias mapping,
    duplicate checks, provider readiness, indicators, or any computation.
    Rows whose date is at or after *reserved_start* are discarded; the identity
    dict records how many were excluded.

    Returns
    -------
    observed : pd.DataFrame
        Raw rows with ``date < reserved_start`` (columns normalised to lower-case).
    identity : dict[str, Any]
        Row-count and date-boundary information (caller must add
        ``raw_source_sha256``, ``observed_row_count``, and the processed-price
        date range after the pipeline loads the temp CSV).
    """
    raw = pd.read_csv(prices_csv, dtype={"symbol": "string"})
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    total = int(len(raw))
    date_min = raw["date"].min()
    date_max = raw["date"].max()

    observed = raw[raw["date"] < reserved_start].copy()
    excluded = total - int(len(observed))

    identity = {
        "raw_row_count": total,
        "raw_date_min": date_min.date().isoformat() if pd.notna(date_min) else None,
        "raw_date_max": date_max.date().isoformat() if pd.notna(date_max) else None,
        "reserved_start": reserved_start.date().isoformat(),
        "reserved_rows_excluded": excluded,
        "observed_row_count": int(observed.shape[0]),
        "observed_date_min": (
            observed["date"].min().date().isoformat() if not observed.empty else None
        ),
        "observed_date_max": (
            observed["date"].max().date().isoformat() if not observed.empty else None
        ),
    }
    return observed, identity


def _compound(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod() - 1.0) if not clean.empty else 0.0


def _max_drawdown(returns: pd.Series) -> float:
    clean = returns.fillna(0.0).astype(float)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _annualized_return(total_return: float, sessions: int) -> float:
    if sessions < 1 or total_return <= -1.0:
        return float(total_return)
    years = sessions / 252.0
    return float((1.0 + total_return) ** (1.0 / max(years, 1e-12)) - 1.0)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if not np.isfinite(denominator) or abs(denominator) < 1e-12:
        return None
    return float(numerator / denominator)


def _weighted_portfolio_return(
    weights: dict[str, float],
    ret_row: pd.Series,
    candidates: list[str],
) -> float:
    """Compute portfolio return from target weights and a performance-return row.

    Skips weights that are effectively zero (abs < 1e-12).  Raises
    ``ValueError`` when a symbol with a **positive held weight** has a missing
    or non-finite return — the caller must ensure the return frame has been
    trimmed to fully observable dates first (see
    ``_trim_return_frame_to_observable``).
    """
    port_ret = 0.0
    for sym in candidates:
        w = weights.get(sym, 0.0)
        if abs(w) < 1e-12:
            continue
        r = ret_row.get(sym)
        if r is None:
            raise ValueError(
                f"Symbol '{sym}' has positive weight {w:.6f} but its "
                f"performance return is missing (None) at this date"
            )
        try:
            r_val = float(r)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Symbol '{sym}' has positive weight {w:.6f} but its "
                f"performance return is non-numeric: {r!r}"
            ) from exc
        if not np.isfinite(r_val):
            raise ValueError(
                f"Symbol '{sym}' has positive weight {w:.6f} but its "
                f"performance return is non-finite: {r_val}"
            )
        port_ret += w * r_val
    return port_ret


def _drift_weights(
    prev_weights: dict[str, float],
    drift_row: pd.Series | None,
    candidates: list[str],
) -> dict[str, float]:
    """Drift prior holdings by PRIOR-interval return to get cost-basis weights.

    Missing drift is harmless for a zero-weight, not-yet-listed symbol.  It is
    not harmless for an existing holding because substituting zero would
    understate the next rebalance's turnover and cost; fail closed instead.
    """
    prev_total = sum(prev_weights.values())
    if prev_total <= 0 or drift_row is None:
        return dict(prev_weights)
    raw_drifted: dict[str, float] = {}
    for s in candidates:
        weight = prev_weights.get(s, 0.0)
        if abs(weight) < 1e-12:
            raw_drifted[s] = 0.0
            continue
        r = drift_row.get(s)
        try:
            r_val = float(r) if r is not None else np.nan
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Symbol '{s}' has prior weight {weight:.6f} but its "
                f"drift return is non-numeric: {r!r}"
            ) from exc
        if not np.isfinite(r_val):
            raise ValueError(
                f"Symbol '{s}' has prior weight {weight:.6f} but its "
                f"drift return is missing or non-finite: {r_val}"
            )
        raw_drifted[s] = weight * (1.0 + r_val)
    cash_weight = 1.0 - prev_total
    total_value = sum(raw_drifted.values()) + max(cash_weight, 0.0)
    if total_value > 1e-12:
        return {s: v / total_value for s, v in raw_drifted.items()}
    return dict(prev_weights)


# ---------------------------------------------------------------------------
# provider readiness (with short-history support)
# ---------------------------------------------------------------------------


def _verify_provider_readiness(
    prices_csv: Path,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed on incomplete provider coverage, missing symbols, or stale data.

    Short-history candidates are measured from their actual first available date
    through 2026-06-30.  Full-history references must cover the declared
    development start.  Internal gaps below threshold, stale end coverage,
    missing required symbols, and absent full reference history still fail closed.
    """
    prices_csv = Path(prices_csv)
    provider_sha256 = sha256_file(prices_csv)
    raw = _load_prices_raw(prices_csv)
    provider_symbols = set(raw["symbol"].unique())

    # Collect all required symbols
    candidates = _candidate_symbols(pool)
    references = dict(pool.get("references", {}))
    required_provider: set[str] = set()
    provider_to_display: dict[str, str] = {}

    for symbol in candidates:
        meta = pool.get("symbol_metadata", {}).get(symbol, {})
        provider = str(meta.get("provider_symbol", symbol))
        required_provider.add(provider)
        provider_to_display[provider] = symbol

    for display, meta in references.items():
        provider = str(meta.get("provider_symbol", display))
        required_provider.add(provider)
        provider_to_display[provider] = display

    missing_provider = sorted(required_provider - provider_symbols)
    extra_symbols = sorted(provider_symbols - required_provider)

    # Verify reference symbols explicitly
    ref_required = list(
        spec.get("validation", {})
        .get("provider_requirements", {})
        .get("reference_symbols_required", [])
    )
    missing_refs = [s for s in ref_required if s not in provider_symbols]

    # Coverage check: full-history references must cover declared development start
    dev_start = pd.Timestamp(spec["evidence"]["development_observed"]["start"])
    falsification_end = pd.Timestamp(spec["evidence"]["falsification_only"]["end"])

    stale: list[str] = []
    short_history_diagnostics: dict[str, dict[str, Any]] = {}
    internal_gap_failures: list[str] = []
    missing_full_history_refs: list[str] = []

    ref_set = set(references.keys())
    full_span_dates = pd.date_range(dev_start, falsification_end, freq="B")
    min_coverage = float(
        spec.get("validation", {})
        .get("provider_requirements", {})
        .get("minimum_coverage_ratio", 0.95)
    )
    # Short-history candidates need only cover 60% of their own listing span
    short_history_min_coverage = float(
        spec.get("validation", {})
        .get("provider_requirements", {})
        .get("short_history_minimum_coverage_ratio", 0.90)
    )

    coverage_ratios: dict[str, float] = {}
    actual_first_dates: dict[str, str] = {}

    for provider in required_provider:
        sym_dates = raw.loc[raw["symbol"] == provider, "date"]
        if sym_dates.empty:
            stale.append(provider)
            actual_first_dates[provider] = "missing"
            coverage_ratios[provider] = 0.0
            continue

        sym_max = sym_dates.max()
        sym_min = sym_dates.min()
        actual_first_dates[provider] = sym_min.date().isoformat()

        if sym_max < falsification_end:
            stale.append(provider)

        display = provider_to_display.get(provider, provider)
        is_reference = display in ref_set
        is_candidate = display in set(candidates)

        if is_reference:
            # Full-history references must span dev_start through falsification_end
            if sym_min > dev_start:
                missing_full_history_refs.append(provider)
            ref_dates = pd.date_range(max(sym_min, dev_start), falsification_end, freq="B")
            matched = len(set(sym_dates.dt.date) & set(ref_dates.date))
            coverage_ratios[provider] = matched / max(len(ref_dates), 1)
        elif is_candidate:
            # Candidates measured from actual first date
            candidate_start = max(sym_min, dev_start)
            candidate_span = pd.date_range(candidate_start, falsification_end, freq="B")
            matched = len(set(sym_dates.dt.date) & set(candidate_span.date))
            coverage_ratios[provider] = matched / max(len(candidate_span), 1)

            # Record short-history diagnostics for recent listings
            if sym_min > dev_start:
                short_history_diagnostics[provider] = {
                    "display_symbol": display,
                    "actual_first_date": sym_min.date().isoformat(),
                    "development_start": dev_start.date().isoformat(),
                    "listing_is_recent": True,
                    "own_span_coverage": coverage_ratios[provider],
                }
        else:
            matched = len(set(sym_dates.dt.date) & set(full_span_dates.date))
            coverage_ratios[provider] = matched / max(len(full_span_dates), 1)

    # Internal gap check for candidates (not references)
    for provider in required_provider:
        display = provider_to_display.get(provider, provider)
        if display in ref_set:
            continue
        sym_dates = raw.loc[raw["symbol"] == provider, "date"]
        if sym_dates.empty:
            continue
        sym_dates_sorted = sym_dates.sort_values()
        gaps = sym_dates_sorted.diff().dropna()
        # A gap > 10 business days in the active span is suspicious
        big_gaps = gaps[gaps > pd.Timedelta(days=14)]
        if len(big_gaps) > 0:
            internal_gap_failures.append(provider)

    # Coverage evaluation: full-history refs use min_coverage; candidates use short_history_min_coverage
    low_coverage: list[str] = []
    for provider in required_provider:
        display = provider_to_display.get(provider, provider)
        threshold = short_history_min_coverage if display in set(candidates) else min_coverage
        if coverage_ratios[provider] < threshold:
            low_coverage.append(provider)

    ready = not (
        missing_provider
        or stale
        or low_coverage
        or missing_refs
        or internal_gap_failures
        or missing_full_history_refs
    )

    return {
        "schema_version": "1.0",
        "provider_file": "observed_slice.csv",
        "provider_identity_sha256": provider_sha256,
        "required_provider_symbols": sorted(required_provider),
        "required_provider_count": len(required_provider),
        "found_provider_count": len(provider_symbols & required_provider),
        "missing_provider_symbols": missing_provider,
        "stale_provider_symbols": stale,
        "low_coverage_symbols": low_coverage,
        "missing_reference_symbols": missing_refs,
        "missing_full_history_reference_symbols": missing_full_history_refs,
        "internal_gap_failures": internal_gap_failures,
        "extra_symbols_in_provider": extra_symbols,
        "coverage_ratios": coverage_ratios,
        "actual_first_dates": actual_first_dates,
        "short_history_diagnostics": short_history_diagnostics,
        "falsification_end": falsification_end.date().isoformat(),
        "development_start": dev_start.date().isoformat(),
        "provider_ready": ready,
    }


# ---------------------------------------------------------------------------
# return frames (performance + drift)
# ---------------------------------------------------------------------------


def _build_return_frames(
    prices: pd.DataFrame,
    candidates: list[str],
    benchmark: str,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build performance and drift return frames.

    Returns
    -------
    perf_frame : DataFrame index=date, columns=symbols+benchmark
        Next-session open-to-open performance returns: open(t+2)/open(t+1) - 1.
        Signal at close(t) -> execute at open(t+1) -> return open(t+1)->open(t+2).
    drift_frame : DataFrame index=date, columns=symbols+benchmark
        Prior-interval open-to-open drift returns: open(t+1)/open(t) - 1.
        Used to drift prior holdings from open(t) to open(t+1) before rebalancing.
    """
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    symbols = [*candidates, benchmark]
    perf_frames: dict[str, pd.Series] = {}
    drift_frames: dict[str, pd.Series] = {}

    for symbol in symbols:
        sub = prices[prices["symbol"] == symbol].sort_values("date").copy()
        sub = sub[(sub["date"] >= start_dt) & (sub["date"] <= end_dt)]
        sub = sub.set_index("date")

        # Performance: open[t+2] / open[t+1] - 1  (positional shift, not DatetimeIndex.shift)
        sub["perf_ret"] = sub["open"].shift(-2) / sub["open"].shift(-1) - 1.0
        # Drift: open[t+1] / open[t] - 1  (prior-interval return for holdings established at open(t))
        sub["drift_ret"] = sub["open"].shift(-1) / sub["open"] - 1.0

        # Mark performance returns whose realisation date exceeds end_dt as NaN
        # realisation date for perf_ret at row i is index[i+2]
        idx_vals = sub.index.values
        n = len(idx_vals)
        realisation = np.empty(n, dtype=object)
        realisation[:] = pd.NaT
        for i in range(n - 2):
            realisation[i] = idx_vals[i + 2]
        realisation_series = pd.Series(realisation, index=sub.index)
        sub.loc[realisation_series > end_dt, "perf_ret"] = np.nan

        # Mark drift returns whose realisation date exceeds end_dt
        drift_realisation = np.empty(n, dtype=object)
        drift_realisation[:] = pd.NaT
        for i in range(n - 1):
            drift_realisation[i] = idx_vals[i + 1]
        drift_real_series = pd.Series(drift_realisation, index=sub.index)
        sub.loc[drift_real_series > end_dt, "drift_ret"] = np.nan

        perf_frames[symbol] = sub["perf_ret"]
        drift_frames[symbol] = sub["drift_ret"]

    perf_result = pd.DataFrame(perf_frames)
    perf_result.index = pd.to_datetime(perf_result.index)
    drift_result = pd.DataFrame(drift_frames)
    drift_result.index = pd.to_datetime(drift_result.index)
    perf_result = perf_result.sort_index()
    drift_result = drift_result.sort_index()
    return _trim_return_frame_to_observable(
        perf_result,
        drift_result,
        benchmark,
    )


def _build_return_frame(
    prices: pd.DataFrame,
    candidates: list[str],
    benchmark: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Compatibility wrapper — returns only the performance frame."""
    perf, _drift = _build_return_frames(prices, candidates, benchmark, start, end)
    return perf


def _trim_return_frame_to_observable(
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame,
    benchmark: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop trailing dates where the benchmark return is not fully realisable.

    The performance return for a signal date requires open(t+2)/open(t+1)-1.
    If the benchmark's performance return is NaN at a trailing date, no
    portfolio path can compute a valid return for that date — drop it and
    every later date so that all remaining sessions are fully observable.
    """
    if benchmark not in perf_frame.columns:
        return perf_frame, drift_frame
    bench_perf = perf_frame[benchmark]
    valid_mask = bench_perf.notna() & np.isfinite(bench_perf.astype(float))
    if valid_mask.all():
        return perf_frame, drift_frame
    # Find the last valid date
    last_valid_idx = valid_mask[::-1].idxmax() if valid_mask.any() else None
    if last_valid_idx is None:
        return (
            perf_frame.iloc[:0].copy(),
            drift_frame.iloc[:0].copy(),
        )
    # Keep all dates up to and including the last valid one
    pos = perf_frame.index.get_loc(last_valid_idx)
    trimmed_perf = perf_frame.iloc[: pos + 1].copy()
    trimmed_drift = drift_frame.iloc[: pos + 1].copy()
    return trimmed_perf, trimmed_drift


# ---------------------------------------------------------------------------
# baseline (a): equal-weight pool buy-and-hold (genuine, no daily rebalance)
# ---------------------------------------------------------------------------


def _ew_buy_hold_returns(
    perf_frame: pd.DataFrame,
    candidates: list[str],
    cost_bps: float = 10.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Genuine equal-weight buy-and-hold with short_history_policy.

    At the evaluation window start, buy equal notional only in frozen members
    that have an available executable return at that first date.  Never add
    future listings or rebalance; let weights drift naturally.

    Returns (return_frame, ew_diagnostics) where diagnostics records eligible
    count, symbols, and excluded short-history names.
    """
    n = len(candidates)
    if n == 0:
        raise ValueError("candidates must not be empty")

    # Determine which candidates have an available return at the FIRST session
    first_date = perf_frame.index[0]
    first_row = perf_frame.loc[first_date]
    eligible: list[str] = []
    excluded_short_history: list[str] = []
    for sym in candidates:
        r = first_row.get(sym) if isinstance(first_row, pd.Series) else first_row[sym]
        if r is not None and np.isfinite(float(r)):
            eligible.append(sym)
        else:
            excluded_short_history.append(sym)

    if not eligible:
        # No eligible candidates → cash throughout
        rows = []
        for idx in range(len(perf_frame)):
            rows.append(
                {
                    "portfolio_return": 0.0,
                    "turnover": 0.0,
                    "cost": 0.0,
                    "gross_exposure": 0.0,
                    **{c: 0.0 for c in candidates},
                }
            )
        result = pd.DataFrame(rows, index=perf_frame.index)
        result.index.name = "date"
        return result, {
            "eligible_count": 0,
            "eligible_symbols": [],
            "excluded_short_history": excluded_short_history,
            "total_candidates": n,
        }

    n_eligible = len(eligible)
    weight_array = np.full(n_eligible, 1.0 / n_eligible, dtype=float)
    rows: list[dict[str, Any]] = []
    initial_cost_applied = False
    # Track per-candidate weights (full candidate list, zero for ineligible)
    current_weights = {c: (1.0 / n_eligible if c in eligible else 0.0) for c in candidates}

    for idx in range(len(perf_frame)):
        ret_row = perf_frame.iloc[idx]

        port_ret = _weighted_portfolio_return(current_weights, ret_row, candidates)

        # Build rets for eligible-only drift
        rets_list: list[float] = []
        for s in eligible:
            r = ret_row.get(s)
            try:
                r_val = float(r) if r is not None else np.nan
            except (ValueError, TypeError):
                r_val = np.nan
            if not np.isfinite(r_val):
                r_val = 0.0  # only for drift computation
            rets_list.append(r_val)
        rets = np.array(rets_list)

        cost = 0.0
        if not initial_cost_applied:
            cost = 1.0 * cost_bps / 10_000.0
            initial_cost_applied = True

        row_data: dict[str, Any] = {
            "portfolio_return": port_ret - cost,
            "turnover": 0.0,
            "cost": cost,
            "gross_exposure": 1.0,
        }
        # Per-candidate weights
        for c in candidates:
            row_data[c] = current_weights.get(c, 0.0)
        rows.append(row_data)

        # Drift weights naturally for next period (eligible only)
        drifted = weight_array * (1.0 + rets)
        total = float(np.sum(drifted))
        if total > 1e-12:
            weight_array = drifted / total
        # Update per-candidate tracking
        for i, sym in enumerate(eligible):
            current_weights[sym] = float(weight_array[i])

    result = pd.DataFrame(rows, index=perf_frame.index)
    result.index.name = "date"
    diagnostics = {
        "eligible_count": n_eligible,
        "eligible_symbols": eligible,
        "excluded_short_history": excluded_short_history,
        "total_candidates": n,
    }
    return result, diagnostics


# ---------------------------------------------------------------------------
# baseline (b): time-series state machine only
# ---------------------------------------------------------------------------


def _state_only_returns(
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame,
    signal_history: list[dict[str, Any]],
    candidates: list[str],
    state_multipliers: Mapping[str, float],
    cost_bps: float,
) -> pd.DataFrame:
    """Equal-weight all candidates with positive state multiplier; daily rebalance.

    Drift uses prior-interval returns (drift_frame), not future performance returns.
    Initial entry incurs cost based on full exposure change.
    Per-candidate weight columns are included for holding-duration measurement.
    """
    states_df = _signal_to_frame(signal_history)
    multipliers = {str(k): float(v) for k, v in state_multipliers.items()}

    rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {c: 0.0 for c in candidates}
    all_dates = sorted(perf_frame.index)

    for date in all_dates:
        target: dict[str, float] = {}
        for sym in candidates:
            state_row = states_df[(states_df["date"] == date) & (states_df["symbol"] == sym)]
            if state_row.empty:
                target[sym] = 0.0
            else:
                state = str(state_row.iloc[0]["state"])
                target[sym] = multipliers.get(state, 0.0)

        total_mult = sum(target.values())
        if total_mult > 0:
            target = {s: v / total_mult for s, v in target.items()}
        else:
            target = {s: 0.0 for s in candidates}

        # Drift previous weights using PRIOR-interval return
        drift_row = drift_frame.loc[date] if date in drift_frame.index else None
        drifted = _drift_weights(prev_weights, drift_row, candidates)

        # Turnover: compare target vs drifted prior holdings
        turnover = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0)) for s in candidates)
        cost = turnover * cost_bps / 10_000.0

        # Performance return using target weights
        if date in perf_frame.index:
            ret_row = perf_frame.loc[date]
            port_ret = _weighted_portfolio_return(target, ret_row, candidates)
        else:
            port_ret = 0.0

        gross = sum(target.values())
        row_data: dict[str, Any] = {
            "portfolio_return": port_ret - cost,
            "turnover": turnover,
            "cost": cost,
            "gross_exposure": gross,
        }
        for c in candidates:
            row_data[c] = target.get(c, 0.0)
        rows.append(row_data)
        prev_weights = target

    result = pd.DataFrame(rows, index=all_dates)
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    return result


# ---------------------------------------------------------------------------
# baseline (c): hierarchical cross-section only (no state filter)
# ---------------------------------------------------------------------------


def _build_state_free_basket_selection(
    date: pd.Timestamp,
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> list[str]:
    """Select baskets by composite score on *date*, ignoring market regime.

    Replicates the ``_basket_snapshots`` scoring pipeline but never consults
    ``risk_on`` and never references individual-security states.  Returns the
    ordered list of basket names whose composite percentile meets the frozen
    score gate, sorted descending.
    """
    eligibility = spec["rotation"]["eligibility"]
    basket_components = spec["rotation"]["score"]["components"]
    basket_min = float(spec["rotation"]["score"]["minimum_composite_percentile"])
    max_baskets = int(spec["rotation"]["maximum_selected_baskets"])

    snapshots: list[dict[str, Any]] = []
    for basket_name, basket_def in pool["baskets"].items():
        members = [str(s) for s in basket_def["symbols"]]
        day = indicators[(indicators["date"] == date) & indicators["symbol"].isin(members)].copy()
        ready = day.dropna(
            subset=[
                "relative_momentum_63_vs_benchmark",
                "momentum_20",
                "sma_50",
                "drawdown_from_63d_high",
            ]
        )
        count = int(ready.shape[0])
        coverage = count / max(len(members), 1)
        breadth = None if ready.empty else float((ready["close"] > ready["sma_50"]).mean())
        relative = (
            None if ready.empty else float(ready["relative_momentum_63_vs_benchmark"].median())
        )
        mom20 = None if ready.empty else float(ready["momentum_20"].median())
        dd = None if ready.empty else float(ready["drawdown_from_63d_high"].median())

        pre = True
        if count < int(eligibility["minimum_eligible_constituents"]):
            pre = False
        if coverage < float(eligibility["minimum_constituent_coverage_ratio"]):
            pre = False
        if breadth is None or breadth < float(eligibility["minimum_breadth_above_sma50"]):
            pre = False
        if bool(eligibility.get("require_positive_median_relative_momentum_63", True)) and (
            relative is None or relative <= 0
        ):
            pre = False

        snapshots.append(
            {
                "basket": str(basket_name),
                "median_relative_momentum_63_vs_benchmark": relative,
                "median_momentum_20": mom20,
                "breadth_above_sma50": breadth,
                "median_drawdown_from_63d_high": dd,
                "pre_score_eligible": pre,
                "composite_percentile": 0.0,
                "score_gate_passed": False,
            }
        )

    eligible_idx = [i for i, s in enumerate(snapshots) if s["pre_score_eligible"]]
    if eligible_idx:
        for field in BASKET_SCORE_FIELDS:
            values = pd.Series(
                [float(snapshots[i][field]) for i in eligible_idx],
                index=eligible_idx,
                dtype="float64",
            )
            ranks = _rank_percentile(values, direction=str(basket_components[field]["direction"]))
            for idx, val in ranks.items():
                snapshots[int(idx)][f"{field}_percentile"] = float(val)
        for idx in eligible_idx:
            composite = sum(
                float(snapshots[idx].get(f"{field}_percentile", 0.0))
                * float(basket_components[field]["weight"])
                for field in BASKET_SCORE_FIELDS
            )
            snapshots[idx]["composite_percentile"] = float(composite)
            snapshots[idx]["score_gate_passed"] = composite >= basket_min

    passed = [s for s in snapshots if s["score_gate_passed"]]
    passed.sort(key=lambda x: (-x["composite_percentile"], x["basket"]))
    return [s["basket"] for s in passed[:max_baskets]]


def _build_state_free_security_selection(
    date: pd.Timestamp,
    basket_name: str,
    members: list[str],
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
) -> list[str]:
    """Select securities within *basket_name* by cross-sectional score only.

    Requires indicator completeness and score-gate passage.  Does **not**
    consult individual-security states — the baseline is state-free.
    """
    components = spec["security_selection"]["cross_section"]["components"]
    min_pct = float(spec["security_selection"]["cross_section"]["minimum_composite_percentile"])
    limit = int(spec["rotation"]["maximum_selected_symbols_per_basket"])

    score_fields = list(SECURITY_SCORE_FIELDS)
    day = indicators[(indicators["date"] == date) & indicators["symbol"].isin(members)].copy()
    ready = day.dropna(subset=score_fields)
    if ready.empty:
        return []

    for field in score_fields:
        direction = str(components[field]["direction"])
        ready[f"{field}_percentile"] = _rank_percentile(ready[field], direction=direction)

    ready["composite"] = sum(
        ready[f"{field}_percentile"] * float(components[field]["weight"]) for field in score_fields
    )
    passed = ready[ready["composite"] >= min_pct]
    if passed.empty:
        return []
    passed = passed.sort_values(["composite", "symbol"], ascending=[False, True])
    return [str(s) for s in passed.head(limit)["symbol"]]


def _cross_section_only_returns(
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame,
    rotations: list[dict[str, Any]],
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
    candidates: list[str],
    cost_bps: float,
) -> pd.DataFrame:
    """Basket + security selection WITHOUT state filter or market-regime gate.

    Truly state-free baseline:
    - On each rotation date, independently computes basket scores and selects
      top-N baskets by composite percentile, regardless of QQQ risk_on.
    - Within selected baskets, ranks securities by cross-sectional score only
      (indicator completeness + score gate) — no absolute-state filter.
    - Freezes both selected baskets AND selected securities until the next
      rotation date; no daily recomputation.
    - Missing/unready symbols remain cash (not forced selection).

    The *rotations* parameter is used only for the rotation-date schedule
    (dates come from the spec's ``rotation_anchor_date`` /
    ``rebalance_every_n_benchmark_sessions``).  ``selected_baskets`` and
    ``selected_symbols_by_basket`` from the supplied rotations are **ignored**
    — this baseline builds its own selections from *indicators*.
    """
    rotation_dates_map: dict[pd.Timestamp, dict[str, Any]] = {}
    for rot in rotations:
        rotation_dates_map[pd.Timestamp(rot["date"])] = rot

    basket_members: dict[str, list[str]] = {}
    for basket_name, basket_def in pool["baskets"].items():
        basket_members[str(basket_name)] = [str(s) for s in basket_def["symbols"]]

    rot_dates_sorted = sorted(rotation_dates_map.keys())
    rot_dates_set = set(rot_dates_sorted)

    rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {c: 0.0 for c in candidates}
    all_dates = sorted(perf_frame.index)

    frozen_target: dict[str, float] = {c: 0.0 for c in candidates}

    for date in all_dates:
        if date in rot_dates_set:
            frozen_target = {c: 0.0 for c in candidates}
            selected_baskets = _build_state_free_basket_selection(date, indicators, spec, pool)

            if selected_baskets:
                basket_weight = 1.0 / len(selected_baskets)
                for basket_name in selected_baskets:
                    members = basket_members.get(basket_name, [])
                    if not members:
                        continue
                    selected_symbols = _build_state_free_security_selection(
                        date,
                        basket_name,
                        members,
                        indicators,
                        spec,
                    )
                    if not selected_symbols:
                        continue
                    sym_weight = basket_weight / len(selected_symbols)
                    for sym in selected_symbols:
                        frozen_target[sym] = frozen_target.get(sym, 0.0) + sym_weight

        target = dict(frozen_target)

        drift_row = drift_frame.loc[date] if date in drift_frame.index else None
        drifted = _drift_weights(prev_weights, drift_row, candidates)

        turnover = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0)) for s in candidates)
        cost = turnover * cost_bps / 10_000.0

        if date in perf_frame.index:
            ret_row = perf_frame.loc[date]
            port_ret = _weighted_portfolio_return(target, ret_row, candidates)
        else:
            port_ret = 0.0

        gross = sum(target.values())
        row_data: dict[str, Any] = {
            "portfolio_return": port_ret - cost,
            "turnover": turnover,
            "cost": cost,
            "gross_exposure": gross,
        }
        for c in candidates:
            row_data[c] = target.get(c, 0.0)
        rows.append(row_data)
        prev_weights = target

    result = pd.DataFrame(rows, index=all_dates)
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    return result


# ---------------------------------------------------------------------------
# baseline (d): hierarchical cross-section + state (full engine)
# ---------------------------------------------------------------------------


def _hierarchical_plus_state_returns(
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame,
    portfolio_history: list[dict[str, Any]],
    candidates: list[str],
    cost_bps: float,
) -> pd.DataFrame:
    """Full engine portfolio with daily state multiplier adjustments.

    Drift uses prior-interval returns (drift_frame), not future performance.
    Per-candidate weight columns included for holding-duration measurement.
    """
    rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {c: 0.0 for c in candidates}
    all_dates = sorted(perf_frame.index)
    date_index_set = set(all_dates)

    for entry in portfolio_history:
        date = pd.Timestamp(entry["date"])
        if date not in date_index_set:
            continue

        target: dict[str, float] = {c: 0.0 for c in candidates}
        for pos in entry.get("positions", []):
            sym = str(pos["symbol"])
            target[sym] = float(pos.get("target_weight", 0.0))

        # Drift previous weights using PRIOR-interval return
        drift_row = drift_frame.loc[date] if date in drift_frame.index else None
        drifted = _drift_weights(prev_weights, drift_row, candidates)

        turnover = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0)) for s in candidates)
        cost = turnover * cost_bps / 10_000.0

        ret_row = perf_frame.loc[date]
        port_ret = _weighted_portfolio_return(target, ret_row, candidates)

        gross = sum(target.values())
        row_data: dict[str, Any] = {
            "date": date,
            "portfolio_return": port_ret - cost,
            "turnover": turnover,
            "cost": cost,
            "gross_exposure": gross,
        }
        for c in candidates:
            row_data[c] = target.get(c, 0.0)
        rows.append(row_data)
        prev_weights = target

    if not rows:
        zero_row: dict[str, Any] = {
            "portfolio_return": 0.0,
            "turnover": 0.0,
            "cost": 0.0,
            "gross_exposure": 0.0,
        }
        for c in candidates:
            zero_row[c] = 0.0
        return pd.DataFrame(
            zero_row,
            index=pd.to_datetime(all_dates),
        ).rename_axis("date")

    result = pd.DataFrame(rows)
    result["date"] = pd.to_datetime(result["date"])
    return result.set_index("date")


# ---------------------------------------------------------------------------
# signal helpers
# ---------------------------------------------------------------------------


def _signal_to_frame(signal_history: list[dict[str, Any]]) -> pd.DataFrame:
    columns = ["date", "symbol", "state", "reason_codes"]
    rows: list[dict[str, Any]] = []
    for row in signal_history:
        rows.append(
            {
                "date": pd.Timestamp(row["date"]),
                "symbol": str(row["symbol"]),
                "state": str(row["state"]),
                "reason_codes": list(row.get("reason_codes", [])),
            }
        )
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# portfolio metrics
# ---------------------------------------------------------------------------


def _baseline_metrics(
    port_returns: pd.DataFrame,
    qqq_returns: pd.Series,
    label: str,
    window_name: str,
    candidates: list[str],
) -> dict[str, Any]:
    """Compute standardised metrics for one baseline portfolio."""
    merged = pd.DataFrame(
        {
            "portfolio_return": port_returns["portfolio_return"],
            "qqq_return": qqq_returns.reindex(port_returns.index),
        }
    ).dropna()

    if merged.empty:
        return {
            "baseline": label,
            "window": window_name,
            "sessions": 0,
            "status": "no_data",
        }

    port_ret = merged["portfolio_return"]
    qqq_ret = merged["qqq_return"]
    sessions = int(merged.shape[0])

    port_total = _compound(port_ret)
    qqq_total = _compound(qqq_ret)
    port_ann = _annualized_return(port_total, sessions)
    qqq_ann = _annualized_return(qqq_total, sessions)

    port_dd = _max_drawdown(port_ret)
    qqq_dd = _max_drawdown(qqq_ret)

    qqq_up = qqq_ret > 0
    qqq_down = qqq_ret < 0
    upside = (
        _safe_ratio(float(port_ret[qqq_up].mean()), float(qqq_ret[qqq_up].mean()))
        if qqq_up.any()
        else None
    )
    downside = (
        _safe_ratio(float(port_ret[qqq_down].mean()), float(qqq_ret[qqq_down].mean()))
        if qqq_down.any()
        else None
    )

    avg_exposure = (
        float(port_returns["gross_exposure"].mean()) if "gross_exposure" in port_returns else None
    )
    total_turnover = float(port_returns["turnover"].sum()) if "turnover" in port_returns else None
    annual_turnover = (
        float(total_turnover / (sessions / 252.0))
        if total_turnover is not None and sessions > 0
        else None
    )

    # Average holding duration from position weight changes
    holding_sessions = _average_holding_sessions_from_weights(port_returns, candidates)

    # Drawdown improvements (positive = less drawdown than reference)
    drawdown_vs_qqq = float(port_dd - qqq_dd)
    drawdown_vs_ew = None  # filled later

    if "positive_basket_contribution_ratio" in port_returns.attrs:
        pbcr = float(port_returns.attrs["positive_basket_contribution_ratio"])
    else:
        pbcr = None  # filled later

    return {
        "baseline": label,
        "window": window_name,
        "sessions": sessions,
        "status": "observed",
        "total_return_after_costs": port_total,
        "annualized_return_after_costs": port_ann,
        "qqq_total_return": qqq_total,
        "qqq_annualized_return": qqq_ann,
        "qqq_relative_return": float(port_total - qqq_total),
        "ew_relative_return": None,  # filled later
        "maximum_drawdown": port_dd,
        "qqq_maximum_drawdown": qqq_dd,
        "drawdown_improvement_vs_qqq": drawdown_vs_qqq,
        "drawdown_improvement_vs_ew": drawdown_vs_ew,  # filled later
        "upside_capture_vs_qqq": upside,
        "downside_capture_vs_qqq": downside,
        "average_gross_exposure": avg_exposure,
        "average_cash_weight": (None if avg_exposure is None else float(1.0 - avg_exposure)),
        "total_turnover": total_turnover,
        "annual_turnover": annual_turnover,
        "average_holding_sessions": holding_sessions,
        "total_cost_drag": float(port_returns["cost"].sum()) if "cost" in port_returns else 0.0,
        "positive_basket_contribution_ratio": pbcr,  # filled later
    }


def _average_holding_sessions_from_weights(
    port_returns: pd.DataFrame, candidates: list[str]
) -> float:
    """Estimate average holding duration from position membership/weight changes.

    Tracks when each candidate's positive-weight run begins and ends,
    measuring the average duration of continuous nonzero-weight membership.
    """
    if "gross_exposure" not in port_returns.columns:
        return 0.0

    # If we have per-candidate weight columns, use them for precise measurement
    candidate_cols = [c for c in candidates if c in port_returns.columns]
    if candidate_cols:
        holding_lengths: list[int] = []
        for col in candidate_cols:
            active = port_returns[col].fillna(0.0).gt(0.0)
            if not active.any():
                continue
            starts = active & ~active.shift(1, fill_value=False)
            groups = starts.cumsum()
            lengths = active.groupby(groups).sum()
            lengths = lengths[lengths > 0]
            holding_lengths.extend(int(v) for v in lengths.values)
        return float(np.mean(holding_lengths)) if holding_lengths else 0.0

    # Fallback: use gross exposure persistence
    active = port_returns["gross_exposure"].fillna(0.0).gt(0.0)
    if active.empty or not active.any():
        return 0.0
    starts = active & ~active.shift(1, fill_value=False)
    groups = starts.cumsum()
    lengths = active.groupby(groups).sum()
    lengths = lengths[lengths > 0]
    return float(lengths.mean()) if not lengths.empty else 0.0


# ---------------------------------------------------------------------------
# attribution — internal counterfactuals for decomposition
# ---------------------------------------------------------------------------


def _counterfactual_no_market_regime(
    indicators: pd.DataFrame,
    timing_spec: Mapping[str, Any],
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Counterfactual: full strategy with market regime always *risk_on*.

    Performs a **true recomputation**: copies the already-computed indicators,
    forces ``risk_on=True`` and ``market_regime="counterfactual_risk_on"``
    for every row, then re-runs ``generate_signal_history``,
    ``build_hierarchical_rotation_history``, and
    ``build_hierarchical_portfolio_history`` on the forced inputs.

    All counterfactual entries are marked with reason code
    ``COUNTERFACTUAL_NO_MARKET_REGIME``.

    This replaces the previous approximation that tried to post-process an
    already-built portfolio — which could never truly undo the market-regime
    gate because ``generate_signal_history`` embeds ``risk_on`` into
    individual security states.
    """
    forced = indicators.copy()
    forced["risk_on"] = True
    forced["market_regime"] = "counterfactual_risk_on"

    forced_signals, _forced_reference = generate_signal_history(forced, timing_spec)
    _, _, forced_rotations = build_hierarchical_rotation_history(forced, forced_signals, spec, pool)
    forced_portfolio = build_hierarchical_portfolio_history(
        forced, forced_signals, forced_rotations, spec
    )

    for entry in forced_portfolio:
        entry["risk_on"] = True
        entry["market_regime"] = "counterfactual_risk_on"
        entry["reason_codes"] = list(entry.get("reason_codes", [])) + [
            "COUNTERFACTUAL_NO_MARKET_REGIME"
        ]

    return forced_portfolio


# ---------------------------------------------------------------------------
# attribution counterfactual portfolios (basket-rank, security-rank)
# ---------------------------------------------------------------------------


def _cs_equal_weight_baskets_returns(
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame,
    rotations: list[dict[str, Any]],
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
    candidates: list[str],
    cost_bps: float,
) -> pd.DataFrame:
    """Counterfactual: equal-weight basket selection (all gate-passing baskets).

    Same security scoring as the cross-section-only baseline but **every**
    basket whose composite percentile meets the frozen score gate is included
    at equal weight instead of selecting only the top-N.  This isolates the
    *basket-rank* contribution.
    """
    rotation_dates_map: dict[pd.Timestamp, dict[str, Any]] = {}
    for rot in rotations:
        rotation_dates_map[pd.Timestamp(rot["date"])] = rot

    basket_members: dict[str, list[str]] = {}
    for basket_name, basket_def in pool["baskets"].items():
        basket_members[str(basket_name)] = [str(s) for s in basket_def["symbols"]]

    rot_dates_set = set(rotation_dates_map.keys())

    rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {c: 0.0 for c in candidates}
    all_dates = sorted(perf_frame.index)
    frozen_target: dict[str, float] = {c: 0.0 for c in candidates}

    for date in all_dates:
        if date in rot_dates_set:
            frozen_target = {c: 0.0 for c in candidates}
            # All gate-passing baskets, not just top-N
            selected_baskets = _build_state_free_basket_selection(date, indicators, spec, pool)
            # Override: include ALL gate-passing baskets, not just top-N
            # Recompute to get ALL passing baskets
            all_passing = _all_state_free_gate_passing_baskets(date, indicators, spec, pool)
            selected_baskets = all_passing

            if selected_baskets:
                basket_weight = 1.0 / len(selected_baskets)
                for basket_name in selected_baskets:
                    members = basket_members.get(basket_name, [])
                    if not members:
                        continue
                    selected_symbols = _build_state_free_security_selection(
                        date,
                        basket_name,
                        members,
                        indicators,
                        spec,
                    )
                    if not selected_symbols:
                        continue
                    sym_weight = basket_weight / len(selected_symbols)
                    for sym in selected_symbols:
                        frozen_target[sym] = frozen_target.get(sym, 0.0) + sym_weight

        target = dict(frozen_target)
        drift_row = drift_frame.loc[date] if date in drift_frame.index else None
        drifted = _drift_weights(prev_weights, drift_row, candidates)
        turnover = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0)) for s in candidates)
        cost = turnover * cost_bps / 10_000.0
        if date in perf_frame.index:
            ret_row = perf_frame.loc[date]
            port_ret = _weighted_portfolio_return(target, ret_row, candidates)
        else:
            port_ret = 0.0
        gross = sum(target.values())
        row_data: dict[str, Any] = {
            "portfolio_return": port_ret - cost,
            "turnover": turnover,
            "cost": cost,
            "gross_exposure": gross,
        }
        for c in candidates:
            row_data[c] = target.get(c, 0.0)
        rows.append(row_data)
        prev_weights = target

    result = pd.DataFrame(rows, index=all_dates)
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    return result


def _all_state_free_gate_passing_baskets(
    date: pd.Timestamp,
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> list[str]:
    """Return ALL baskets that pass the score gate (not limited to top-N)."""
    eligibility = spec["rotation"]["eligibility"]
    basket_components = spec["rotation"]["score"]["components"]
    basket_min = float(spec["rotation"]["score"]["minimum_composite_percentile"])

    snapshots: list[dict[str, Any]] = []
    for basket_name, basket_def in pool["baskets"].items():
        members = [str(s) for s in basket_def["symbols"]]
        day = indicators[(indicators["date"] == date) & indicators["symbol"].isin(members)].copy()
        ready = day.dropna(
            subset=[
                "relative_momentum_63_vs_benchmark",
                "momentum_20",
                "sma_50",
                "drawdown_from_63d_high",
            ]
        )
        count = int(ready.shape[0])
        coverage = count / max(len(members), 1)
        breadth = None if ready.empty else float((ready["close"] > ready["sma_50"]).mean())
        relative = (
            None if ready.empty else float(ready["relative_momentum_63_vs_benchmark"].median())
        )
        mom20 = None if ready.empty else float(ready["momentum_20"].median())
        dd = None if ready.empty else float(ready["drawdown_from_63d_high"].median())

        pre = True
        if count < int(eligibility["minimum_eligible_constituents"]):
            pre = False
        if coverage < float(eligibility["minimum_constituent_coverage_ratio"]):
            pre = False
        if breadth is None or breadth < float(eligibility["minimum_breadth_above_sma50"]):
            pre = False
        if bool(eligibility.get("require_positive_median_relative_momentum_63", True)) and (
            relative is None or relative <= 0
        ):
            pre = False

        snapshots.append(
            {
                "basket": str(basket_name),
                "median_relative_momentum_63_vs_benchmark": relative,
                "median_momentum_20": mom20,
                "breadth_above_sma50": breadth,
                "median_drawdown_from_63d_high": dd,
                "pre_score_eligible": pre,
                "composite_percentile": 0.0,
                "score_gate_passed": False,
            }
        )

    eligible_idx = [i for i, s in enumerate(snapshots) if s["pre_score_eligible"]]
    if eligible_idx:
        for field in BASKET_SCORE_FIELDS:
            values = pd.Series(
                [float(snapshots[i][field]) for i in eligible_idx],
                index=eligible_idx,
                dtype="float64",
            )
            ranks = _rank_percentile(values, direction=str(basket_components[field]["direction"]))
            for idx, val in ranks.items():
                snapshots[int(idx)][f"{field}_percentile"] = float(val)
        for idx in eligible_idx:
            composite = sum(
                float(snapshots[idx].get(f"{field}_percentile", 0.0))
                * float(basket_components[field]["weight"])
                for field in BASKET_SCORE_FIELDS
            )
            snapshots[idx]["composite_percentile"] = float(composite)
            snapshots[idx]["score_gate_passed"] = composite >= basket_min

    passed = [s for s in snapshots if s["score_gate_passed"]]
    passed.sort(key=lambda x: (-x["composite_percentile"], x["basket"]))
    return [s["basket"] for s in passed]


def _cs_equal_weight_securities_returns(
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame,
    rotations: list[dict[str, Any]],
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
    candidates: list[str],
    cost_bps: float,
) -> pd.DataFrame:
    """Counterfactual: equal-weight security selection within selected baskets.

    Same basket selection as the cross-section-only baseline but **all**
    gate-passing securities within each selected basket are included at equal
    weight instead of selecting only the top-M by composite score.  This
    isolates the *security-rank* contribution.
    """
    rotation_dates_map: dict[pd.Timestamp, dict[str, Any]] = {}
    for rot in rotations:
        rotation_dates_map[pd.Timestamp(rot["date"])] = rot

    basket_members: dict[str, list[str]] = {}
    for basket_name, basket_def in pool["baskets"].items():
        basket_members[str(basket_name)] = [str(s) for s in basket_def["symbols"]]

    rot_dates_set = set(rotation_dates_map.keys())

    rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {c: 0.0 for c in candidates}
    all_dates = sorted(perf_frame.index)
    frozen_target: dict[str, float] = {c: 0.0 for c in candidates}

    for date in all_dates:
        if date in rot_dates_set:
            frozen_target = {c: 0.0 for c in candidates}
            selected_baskets = _build_state_free_basket_selection(date, indicators, spec, pool)

            if selected_baskets:
                basket_weight = 1.0 / len(selected_baskets)
                for basket_name in selected_baskets:
                    members = basket_members.get(basket_name, [])
                    if not members:
                        continue
                    # ALL gate-passing securities, not just top-M
                    all_selected = _all_state_free_gate_passing_securities(
                        date,
                        basket_name,
                        members,
                        indicators,
                        spec,
                    )
                    if not all_selected:
                        continue
                    sym_weight = basket_weight / len(all_selected)
                    for sym in all_selected:
                        frozen_target[sym] = frozen_target.get(sym, 0.0) + sym_weight

        target = dict(frozen_target)
        drift_row = drift_frame.loc[date] if date in drift_frame.index else None
        drifted = _drift_weights(prev_weights, drift_row, candidates)
        turnover = sum(abs(target.get(s, 0.0) - drifted.get(s, 0.0)) for s in candidates)
        cost = turnover * cost_bps / 10_000.0
        if date in perf_frame.index:
            ret_row = perf_frame.loc[date]
            port_ret = _weighted_portfolio_return(target, ret_row, candidates)
        else:
            port_ret = 0.0
        gross = sum(target.values())
        row_data: dict[str, Any] = {
            "portfolio_return": port_ret - cost,
            "turnover": turnover,
            "cost": cost,
            "gross_exposure": gross,
        }
        for c in candidates:
            row_data[c] = target.get(c, 0.0)
        rows.append(row_data)
        prev_weights = target

    result = pd.DataFrame(rows, index=all_dates)
    result.index = pd.to_datetime(result.index)
    result.index.name = "date"
    return result


def _all_state_free_gate_passing_securities(
    date: pd.Timestamp,
    basket_name: str,
    members: list[str],
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
) -> list[str]:
    """Return ALL securities within *basket_name* that pass the score gate."""
    components = spec["security_selection"]["cross_section"]["components"]
    min_pct = float(spec["security_selection"]["cross_section"]["minimum_composite_percentile"])
    score_fields = list(SECURITY_SCORE_FIELDS)

    day = indicators[(indicators["date"] == date) & indicators["symbol"].isin(members)].copy()
    ready = day.dropna(subset=score_fields)
    if ready.empty:
        return []

    for field in score_fields:
        direction = str(components[field]["direction"])
        ready[f"{field}_percentile"] = _rank_percentile(ready[field], direction=direction)

    ready["composite"] = sum(
        ready[f"{field}_percentile"] * float(components[field]["weight"]) for field in score_fields
    )
    passed = ready[ready["composite"] >= min_pct]
    if passed.empty:
        return []
    return [
        str(s)
        for s in passed.sort_values(["composite", "symbol"], ascending=[False, True])["symbol"]
    ]


def _incremental_attribution(
    ew_metrics: dict[str, Any],
    state_metrics: dict[str, Any],
    cross_section_metrics: dict[str, Any],
    full_metrics: dict[str, Any],
    *,
    no_market_regime_metrics: dict[str, Any] | None = None,
    cs_ew_baskets_metrics: dict[str, Any] | None = None,
    cs_ew_securities_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decompose full-strategy excess return using named counterfactuals.

    Each effect isolates one component by varying it while holding the others
    as constant as the architecture permits.  Effects are **not** guaranteed
    additive — a residual is reported explicitly.

    Counterfactual definitions
    --------------------------
    market_regime_effect
        *full* minus *no-market-regime*.
        Counterfactual: full strategy with ``risk_on`` forced ``True`` every
        session, preserving rotation selections and state mechanics.
        **Positive sign → market regime improved total return.**
    basket_rank_effect
        *cs_only* minus *cs_equal_weight_baskets*.
        Counterfactual: cross-section-only with ALL gate-passing baskets
        included equally instead of selecting only the top-N by composite
        score.  Security scoring within baskets is unchanged.
    security_rank_effect
        *cs_only* minus *cs_equal_weight_securities*.
        Counterfactual: cross-section-only with ALL gate-passing securities
        within each selected basket included equally instead of selecting
        only the top-M by composite score.  Basket selection is unchanged.
    state_overlay_effect
        *full* minus *cs_only*.
        Counterfactual: add absolute-state multipliers on top of the
        state-free cross-sectional basket + security selection.
    """

    def _excess(m: dict[str, Any] | None) -> float:
        if m is None:
            return 0.0
        return float(m.get("total_return_after_costs", 0.0) or 0.0)

    ew_total = _excess(ew_metrics)
    state_total = _excess(state_metrics)
    cs_total = _excess(cross_section_metrics)
    full_total = _excess(full_metrics)
    no_mr_total = _excess(no_market_regime_metrics)
    cs_ew_b_total = _excess(cs_ew_baskets_metrics)
    cs_ew_s_total = _excess(cs_ew_securities_metrics)

    # ---- named counterfactual effects ------------------------------------
    market_regime_effect: float | None = None
    market_regime_definition: str = (
        "full minus no-market-regime: full strategy return minus return when "
        "risk_on is forced True every session (rotation selections and state "
        "mechanics preserved). Positive sign → market regime improved return."
    )
    if no_market_regime_metrics is not None:
        market_regime_effect = full_total - no_mr_total

    basket_rank_effect: float | None = None
    basket_rank_definition: str = (
        "cs_only minus cs_equal_weight_baskets: top-N score-ranked basket "
        "selection minus all gate-passing baskets at equal weight (security "
        "scoring held constant). Positive sign → basket ranking improved return."
    )
    if cs_ew_baskets_metrics is not None:
        basket_rank_effect = cs_total - cs_ew_b_total

    security_rank_effect: float | None = None
    security_rank_definition: str = (
        "cs_only minus cs_equal_weight_securities: top-M score-ranked security "
        "selection minus all gate-passing securities at equal weight within "
        "the same baskets. Positive sign → security ranking improved return."
    )
    if cs_ew_securities_metrics is not None:
        security_rank_effect = cs_total - cs_ew_s_total

    state_overlay_effect = no_mr_total - cs_total
    state_overlay_definition: str = (
        "no-market-regime full minus state-free cs_only: state eligibility "
        "at rotation plus daily state multipliers applied on top of "
        "state-free cross-sectional basket + security selection, with "
        "risk_on forced True — market-regime gate held constant. "
        "Positive sign → state overlay improved return."
    )

    # Non-additivity check: the four marginal effects do not sum to
    # full - ew because counterfactuals use different baselines.
    sum_named = (
        (market_regime_effect or 0.0)
        + (basket_rank_effect or 0.0)
        + (security_rank_effect or 0.0)
        + (state_overlay_effect or 0.0)
    )
    total_excess = full_total - ew_total
    residual = total_excess - sum_named

    return {
        "schema_version": "1.0",
        "baseline_ew_total": ew_total,
        "baseline_state_total": state_total,
        "baseline_cross_section_total": cs_total,
        "baseline_full_total": full_total,
        "counterfactual_no_market_regime_total": (
            no_mr_total if no_market_regime_metrics is not None else None
        ),
        "counterfactual_equal_weight_baskets_total": (
            cs_ew_b_total if cs_ew_baskets_metrics is not None else None
        ),
        "counterfactual_equal_weight_securities_total": (
            cs_ew_s_total if cs_ew_securities_metrics is not None else None
        ),
        # Named effects with honest counterfactual definitions
        "market_regime_effect": market_regime_effect,
        "market_regime_effect_definition": market_regime_definition,
        "basket_rank_effect": basket_rank_effect,
        "basket_rank_effect_definition": basket_rank_definition,
        "security_rank_effect": security_rank_effect,
        "security_rank_effect_definition": security_rank_definition,
        "state_overlay_effect": state_overlay_effect,
        "state_overlay_effect_definition": state_overlay_definition,
        # Non-additivity
        "effects_are_non_additive": True,
        "non_additivity_note": (
            "The four marginal effects (market_regime, basket_rank, "
            "security_rank, state_overlay) do not sum to total_excess_vs_ew "
            "because each uses a different counterfactual baseline.  The "
            "residual captures the non-additive component."
        ),
        "sum_of_named_effects": sum_named,
        "total_excess_vs_ew": total_excess,
        "residual": residual,
    }


# ---------------------------------------------------------------------------
# concentration
# ---------------------------------------------------------------------------


def _concentration_analysis(
    portfolio_history: list[dict[str, Any]],
    basket_scores: list[dict[str, Any]],
    perf_frame: pd.DataFrame | None = None,
    drift_frame: pd.DataFrame | None = None,
    candidates: list[str] | None = None,
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    """Concentration by symbol and basket, selection frequency, and contributions.

    When perf_frame and drift_frame are provided, computes actual gross
    contribution by basket and symbol on the lagged performance frame,
    and derives positive_basket_contribution_ratio.
    """
    symbol_exposure: dict[str, list[float]] = {}
    basket_selection_count: dict[str, int] = {}
    total_dates = 0

    for entry in portfolio_history:
        total_dates += 1
        selected = set()
        for pos in entry.get("positions", []):
            sym = str(pos["symbol"])
            weight = float(pos.get("target_weight", 0.0))
            if sym not in symbol_exposure:
                symbol_exposure[sym] = []
            symbol_exposure[sym].append(weight)
            basket = str(pos.get("basket", ""))
            if basket:
                selected.add(basket)
        for basket in selected:
            basket_selection_count[basket] = basket_selection_count.get(basket, 0) + 1

    symbol_avg: dict[str, float] = {}
    for sym, weights in symbol_exposure.items():
        nonzero = [w for w in weights if w > 0]
        symbol_avg[sym] = float(np.mean(nonzero)) if nonzero else 0.0

    max_symbol = max(symbol_avg, key=symbol_avg.get) if symbol_avg else None
    max_concentration = symbol_avg.get(max_symbol, 0.0) if max_symbol else 0.0

    basket_freq = {b: float(c / max(total_dates, 1)) for b, c in basket_selection_count.items()}

    pos_counts = []
    for entry in portfolio_history:
        pos_count = sum(
            1 for p in entry.get("positions", []) if float(p.get("target_weight", 0.0)) > 0
        )
        pos_counts.append(pos_count)
    avg_breadth = float(np.mean(pos_counts)) if pos_counts else 0.0

    # ---- contribution analysis (Correction 6) -------------------------------
    basket_contribution: dict[str, float] = {}
    symbol_contribution: dict[str, float] = {}
    positive_basket_contribution_ratio: float | None = None

    if perf_frame is not None and candidates is not None:
        contribs = _compute_portfolio_contributions(
            portfolio_history=portfolio_history,
            perf_frame=perf_frame,
            drift_frame=drift_frame,
            candidates=candidates,
            cost_bps=cost_bps,
        )
        basket_contribution = contribs.get("basket_contributions", {})
        symbol_contribution = contribs.get("symbol_contributions", {})
        positive_basket_contribution_ratio = contribs.get("positive_basket_contribution_ratio")

    return {
        "schema_version": "1.0",
        "symbol_average_nonzero_weight": symbol_avg,
        "max_single_symbol_concentration": max_concentration,
        "max_concentration_symbol": max_symbol,
        "basket_selection_frequency": basket_freq,
        "basket_selection_count": basket_selection_count,
        "average_portfolio_breadth": avg_breadth,
        "basket_contributions": basket_contribution,
        "symbol_contributions": symbol_contribution,
        "positive_basket_contribution_ratio": positive_basket_contribution_ratio,
    }


def _compute_portfolio_contributions(
    portfolio_history: list[dict[str, Any]],
    perf_frame: pd.DataFrame,
    drift_frame: pd.DataFrame | None,
    candidates: list[str],
    cost_bps: float = 10.0,
) -> dict[str, Any]:
    """Compute gross contribution by basket and symbol on the lagged performance frame.

    Contributions are computed as weight * return for each position on each date,
    without subtracting costs (gross).  Costs are attributed proportionally.
    positive_basket_contribution_ratio = fraction of baskets with positive
    total gross contribution.
    """
    basket_gross: dict[str, float] = {}
    symbol_gross: dict[str, float] = {}

    for entry in portfolio_history:
        date = pd.Timestamp(entry["date"])
        if date not in perf_frame.index:
            continue
        ret_row = perf_frame.loc[date]
        for pos in entry.get("positions", []):
            sym = str(pos["symbol"])
            weight = float(pos.get("target_weight", 0.0))
            if weight <= 0:
                continue
            r = ret_row.get(sym)
            if r is None:
                raise ValueError(
                    f"Symbol '{sym}' has positive contribution weight "
                    f"{weight:.6f} but its performance return is missing "
                    f"(None) at {date.date().isoformat()}"
                )
            try:
                r_val = float(r)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Symbol '{sym}' has positive contribution weight "
                    f"{weight:.6f} but its performance return is "
                    f"non-numeric: {r!r}"
                ) from exc
            if not np.isfinite(r_val):
                raise ValueError(
                    f"Symbol '{sym}' has positive contribution weight "
                    f"{weight:.6f} but its performance return is "
                    f"non-finite: {r_val}"
                )
            contrib = weight * r_val
            symbol_gross[sym] = symbol_gross.get(sym, 0.0) + contrib
            basket = str(pos.get("basket", ""))
            if basket:
                basket_gross[basket] = basket_gross.get(basket, 0.0) + contrib

    # positive_basket_contribution_ratio
    all_baskets = set(basket_gross.keys())
    positive_count = sum(1 for b in all_baskets if basket_gross.get(b, 0.0) > 0)
    pbcr = float(positive_count / max(len(all_baskets), 1)) if all_baskets else None

    return {
        "basket_contributions": basket_gross,
        "symbol_contributions": symbol_gross,
        "positive_basket_contribution_ratio": pbcr,
    }


# ---------------------------------------------------------------------------
# selection stability
# ---------------------------------------------------------------------------


def _selection_stability(
    rotations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure how often selected baskets/symbols persist across rotations."""
    if len(rotations) < 2:
        return {
            "schema_version": "1.0",
            "basket_stability": None,
            "symbol_stability": None,
            "rapid_replacement_rate": None,
            "rotation_count": len(rotations),
        }

    basket_changes = 0
    symbol_changes = 0
    rapid_replacements = 0

    for i in range(1, len(rotations)):
        prev_baskets = set(rotations[i - 1].get("selected_baskets", []))
        curr_baskets = set(rotations[i].get("selected_baskets", []))
        if prev_baskets != curr_baskets:
            basket_changes += 1
        if not curr_baskets and prev_baskets:
            rapid_replacements += 1

        prev_symbols: set[str] = set()
        curr_symbols: set[str] = set()
        for s in rotations[i - 1].get("selected_symbols_by_basket", {}).values():
            for item in s:
                prev_symbols.add(str(item.get("symbol", "")))
        for s in rotations[i].get("selected_symbols_by_basket", {}).values():
            for item in s:
                curr_symbols.add(str(item.get("symbol", "")))
        if prev_symbols != curr_symbols:
            symbol_changes += 1

    n = len(rotations) - 1
    basket_stability = 1.0 - basket_changes / n
    symbol_stability = 1.0 - symbol_changes / n
    rapid_rate = rapid_replacements / n

    return {
        "schema_version": "1.0",
        "basket_stability": float(basket_stability),
        "symbol_stability": float(symbol_stability),
        "rapid_replacement_rate": float(rapid_rate),
        "basket_changes": basket_changes,
        "symbol_changes": symbol_changes,
        "rapid_replacements": rapid_replacements,
        "rotation_count": len(rotations),
    }


# ---------------------------------------------------------------------------
# gate checking — tightened with all comparisons exposed
# ---------------------------------------------------------------------------


def _check_gates(
    full_metrics: dict[str, Any],
    gates: Mapping[str, Any],
    concentration: dict[str, Any],
    stability: dict[str, Any],
    all_baseline_metrics: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate predeclared gates against observed metrics.

    Every gate comparison is exposed in the output.  Gate failures include
    the specific threshold and observed value.
    """

    def _resolve_metric(gate_key: str, window_metrics: dict[str, Any]) -> float | None:
        metric_key = _gate_to_metric(gate_key)
        v = window_metrics.get(metric_key)
        if v is not None:
            return float(v)
        v = concentration.get(metric_key)
        if v is not None:
            return float(v)
        return None

    comparisons: dict[str, bool] = {}
    details: dict[str, dict[str, Any]] = {}

    # Development gates
    dev_gates = gates.get("development", {})
    for gate_key, threshold in dev_gates.items():
        metric_val = _resolve_metric(gate_key, full_metrics["development_observed"])
        passed = _evaluate_gate(gate_key, metric_val, float(threshold))
        comparisons[f"development.{gate_key}"] = passed
        details[f"development.{gate_key}"] = {
            "threshold": float(threshold),
            "observed": metric_val,
            "passed": passed,
        }

    # Falsification gates
    fals_gates = gates.get("falsification", {})
    for gate_key, threshold in fals_gates.items():
        metric_val = _resolve_metric(gate_key, full_metrics["falsification_only"])
        passed = _evaluate_gate(gate_key, metric_val, float(threshold))
        comparisons[f"falsification.{gate_key}"] = passed
        details[f"falsification.{gate_key}"] = {
            "threshold": float(threshold),
            "observed": metric_val,
            "passed": passed,
        }

    # Robustness: selection stability
    rob_gates = gates.get("robustness", {})
    if "selection_stability_min" in rob_gates:
        threshold = float(rob_gates["selection_stability_min"])
        stability_val = stability.get("symbol_stability")
        passed = stability_val is not None and float(stability_val) >= threshold
        comparisons["robustness.selection_stability_min"] = passed
        details["robustness.selection_stability_min"] = {
            "threshold": threshold,
            "observed": stability_val,
            "passed": passed,
        }

    # Robustness: baseline improvement ratio (full vs EW)
    if "minimum_baseline_improvement_ratio" in rob_gates:
        threshold = float(rob_gates["minimum_baseline_improvement_ratio"])
        ew_ret = float(
            (
                all_baseline_metrics.get("equal_weight_pool_buy_and_hold", {})
                .get("development_observed", {})
                .get("total_return_after_costs", 0.0)
                or 0.0
            )
        )
        full_ret = float(
            full_metrics.get("development_observed", {}).get("total_return_after_costs", 0.0) or 0.0
        )
        ratio = (full_ret - ew_ret) / max(abs(ew_ret), 1e-12) if ew_ret != 0 else 0.0
        passed = ratio >= threshold
        comparisons["robustness.minimum_baseline_improvement_ratio"] = passed
        details["robustness.minimum_baseline_improvement_ratio"] = {
            "threshold": threshold,
            "observed": float(ratio),
            "passed": passed,
        }

    all_passed = all(comparisons.values()) if comparisons else False
    return {
        "comparisons": comparisons,
        "details": details,
        "all_passed": all_passed,
    }


_GATE_METRIC_MAP: dict[str, str] = {
    "aggregate_qqq_relative_return_after_costs_min": "qqq_relative_return",
    "ew_relative_return_after_costs_min": "ew_relative_return",
    "maximum_drawdown_min": "maximum_drawdown",
    "drawdown_improvement_vs_qqq_min": "drawdown_improvement_vs_qqq",
    "drawdown_improvement_vs_ew_min": "drawdown_improvement_vs_ew",
    "downside_capture_vs_qqq_max": "downside_capture_vs_qqq",
    "annual_turnover_max": "annual_turnover",
    "average_holding_sessions_min": "average_holding_sessions",
    "max_single_symbol_concentration_max": "max_single_symbol_concentration",
    "positive_basket_contribution_ratio_min": "positive_basket_contribution_ratio",
}


def _gate_to_metric(gate_key: str) -> str:
    return _GATE_METRIC_MAP.get(gate_key, gate_key)


def _evaluate_gate(gate_key: str, observed: float | None, threshold: float) -> bool:
    """Evaluate a single gate: _min -> observed >= threshold, _max -> observed <= threshold.

    For negative-valued metrics (e.g. drawdown), a _min gate means the observed
    value must not be worse (more negative) than the floor threshold.  For a
    _max gate, the observed must not exceed the ceiling.
    """
    if observed is None or not np.isfinite(observed):
        return False
    if gate_key.endswith("_min"):
        return observed >= threshold
    if gate_key.endswith("_max"):
        return observed <= threshold
    return False


# ---------------------------------------------------------------------------
# provider manifest validation
# ---------------------------------------------------------------------------


def _validate_provider_manifest(
    manifest_path: Path,
    prices_csv: Path,
    *,
    required_symbols: set[str] | None = None,
    required_count: int | None = None,
    expected_spec_sha256: str | None = None,
    expected_pool_sha256: str | None = None,
    expected_experiment_id: str | None = None,
) -> dict[str, Any]:
    """Load and validate a provider manifest, proving the supplied prices_csv
    is bound to the manifest.

    Handles two manifest types:

    * **snapshot** (``manifest_type == "provider_snapshot"``): the manifest's
      ``snapshot.prices_csv_sha256`` must match the supplied *prices_csv*.
    * **upstream** (no ``manifest_type`` or legacy): every source CSV hash is
      verified against the actual file on disk (resolved relative to the
      manifest directory), and the supplied *prices_csv* hash must match one
      of the source entries.

    In both cases the manifest's own identity hash is recomputed and verified,
    and the calendar must cover through 2026-06-30 with no rows on or after
    2026-07-01.

    Returns a structured validation dict.  Raises ``ValueError`` or
    ``FileNotFoundError`` on any hash/symbol/coverage mismatch.
    """
    manifest_path = Path(manifest_path).resolve()
    prices_csv = Path(prices_csv).resolve()

    if not manifest_path.is_file():
        raise FileNotFoundError(f"provider manifest not found: {manifest_path}")
    if not prices_csv.is_file():
        raise FileNotFoundError(f"prices CSV not found: {prices_csv}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prices_sha256 = sha256_file(prices_csv)

    # ---- recompute and verify manifest identity hash -----------------------
    manifest_declared_hash = manifest.get("provider_identity_sha256", "")
    recomputed = _recompute_manifest_identity(manifest)
    if manifest_declared_hash and recomputed != manifest_declared_hash:
        raise ValueError(
            f"provider manifest identity hash mismatch: "
            f"declared={manifest_declared_hash}, recomputed={recomputed}"
        )

    # ---- market ------------------------------------------------------------
    market = str(manifest.get("market", "")).lower()
    if market != "us":
        raise ValueError(f"provider manifest market mismatch: expected=us, actual={market}")

    manifest_type = str(manifest.get("manifest_type", "upstream_provider"))

    # ---- prove prices_csv is bound to this manifest ------------------------
    source_hashes_verified = False
    source_attestation: str | None = None
    verified_sources: list[dict[str, Any]] = []
    manifest_symbols: list[str] = []

    if manifest_type == "provider_snapshot":
        # Snapshot manifest: prices CSV hash must match snapshot entry
        snapshot = manifest.get("snapshot", {})
        bound_hash = str(snapshot.get("prices_csv_sha256", ""))
        if not bound_hash:
            raise ValueError("snapshot manifest missing snapshot.prices_csv_sha256")
        if prices_sha256 != bound_hash:
            raise ValueError(
                f"supplied prices_csv hash {prices_sha256} does not match "
                f"snapshot manifest bound hash {bound_hash}"
            )
        manifest_symbols = list(snapshot.get("symbols", []))
        source_hashes_verified = bool(
            manifest.get("upstream", {}).get("source_hashes_verified", False)
        )
        source_attestation = str(manifest.get("upstream", {}).get("source_attestation", ""))
        snapshot_spec = manifest.get("spec", {})
        declared_spec_sha256 = str(snapshot_spec.get("sha256", ""))
        declared_pool_sha256 = str(snapshot_spec.get("pool_sha256", ""))
        declared_experiment_id = str(snapshot_spec.get("experiment_id", ""))
        if expected_spec_sha256 is not None and declared_spec_sha256 != expected_spec_sha256:
            raise ValueError(
                "snapshot manifest spec hash mismatch: "
                f"expected={expected_spec_sha256}, "
                f"actual={declared_spec_sha256 or 'missing'}"
            )
        if expected_pool_sha256 is not None and declared_pool_sha256 != expected_pool_sha256:
            raise ValueError(
                "snapshot manifest pool hash mismatch: "
                f"expected={expected_pool_sha256}, "
                f"actual={declared_pool_sha256 or 'missing'}"
            )
        if expected_experiment_id is not None and declared_experiment_id != expected_experiment_id:
            raise ValueError(
                "snapshot manifest experiment mismatch: "
                f"expected={expected_experiment_id}, "
                f"actual={declared_experiment_id or 'missing'}"
            )
    else:
        # Upstream provider manifest: verify every source CSV hash
        source_csvs = manifest.get("source_csvs", [])
        if not source_csvs:
            raise ValueError("upstream provider manifest has no source_csvs entries")

        manifest_dir = manifest_path.parent
        prices_matched = False

        for src in source_csvs:
            src_name = str(src.get("name", src.get("path", "")))
            declared_hash = str(src.get("sha256", ""))
            # Resolve source file relative to manifest directory
            src_path = manifest_dir / src_name
            if not src_path.is_file():
                raise FileNotFoundError(f"provider manifest source file missing: {src_path}")
            actual_hash = sha256_file(src_path)
            if actual_hash != declared_hash:
                raise ValueError(
                    f"provider source hash mismatch for {src_name}: "
                    f"declared={declared_hash}, actual={actual_hash}"
                )
            verified_sources.append(
                {
                    "name": src_name,
                    "declared_sha256": declared_hash,
                    "verified": True,
                }
            )
            if actual_hash == prices_sha256:
                prices_matched = True

        if not prices_matched:
            raise ValueError(
                f"supplied prices_csv hash {prices_sha256} does not match "
                f"any source CSV hash in the upstream provider manifest"
            )

        source_hashes_verified = True
        source_attestation = (
            "source_hashes_verified_by_validator; no_independent_third_party_attestation"
        )

        # Collect symbols from instruments if available
        instruments = manifest.get("instruments", {})
        inst_count = int(instruments.get("count", 0))
        if inst_count > 0:
            # Read instrument file for symbol list
            inst_path = manifest_dir / str(instruments.get("path", ""))
            if inst_path.is_file():
                manifest_symbols = sorted(
                    line.strip()
                    for line in inst_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )

    # ---- verify exact symbol set -------------------------------------------
    actual_symbols_set = set(manifest_symbols) if manifest_symbols else None
    if required_symbols is not None and actual_symbols_set is not None:
        if actual_symbols_set != required_symbols:
            missing = sorted(required_symbols - actual_symbols_set)
            extra = sorted(actual_symbols_set - required_symbols)
            raise ValueError(f"manifest symbol set mismatch: missing={missing}, extra={extra}")

    symbol_count = (
        len(manifest_symbols)
        if manifest_symbols
        else (manifest.get("snapshot", {}).get("symbol_count", 0))
    )
    if required_count is not None and symbol_count < required_count:
        raise ValueError(f"manifest symbol count {symbol_count} below required {required_count}")

    # ---- verify calendar / observed coverage -------------------------------
    calendar = manifest.get("calendar", {})
    first_day = calendar.get("first_day")
    last_day = calendar.get("last_day")
    if first_day and last_day:
        last_dt = pd.Timestamp(last_day)
        if last_dt < pd.Timestamp("2026-06-30"):
            raise ValueError(f"manifest calendar ends at {last_day}, before required 2026-06-30")

    # Verify no reserved rows in the prices CSV
    reserved_start = pd.Timestamp("2026-07-01")
    prices_df = pd.read_csv(prices_csv, dtype={"symbol": "string"})
    prices_df.columns = [str(c).strip().lower() for c in prices_df.columns]
    prices_df["date"] = pd.to_datetime(prices_df["date"], errors="coerce")
    reserved_rows = int((prices_df["date"] >= reserved_start).sum())
    if reserved_rows > 0:
        raise ValueError(
            f"prices CSV contains {reserved_rows} rows on or after "
            f"{reserved_start.date().isoformat()}; all such rows must be "
            f"excluded before snapshot generation"
        )

    # ---- identity ----------------------------------------------------------
    manifest_identity = manifest_declared_hash or recomputed
    manifest_content_sha256 = sha256_file(manifest_path)

    return {
        "manifest_path": manifest_path.name,
        "manifest_identity_sha256": manifest_identity,
        "manifest_content_sha256": manifest_content_sha256,
        "manifest_type": manifest_type,
        "market": market,
        "symbol_count": symbol_count,
        "symbols": manifest_symbols if manifest_symbols else None,
        "calendar_first_day": first_day,
        "calendar_last_day": last_day,
        "source_hashes_verified": source_hashes_verified,
        "source_attestation": source_attestation,
        "verified_sources": verified_sources if verified_sources else None,
        "spec_sha256": (
            str(manifest.get("spec", {}).get("sha256", ""))
            if manifest_type == "provider_snapshot"
            else None
        ),
        "pool_sha256": (
            str(manifest.get("spec", {}).get("pool_sha256", ""))
            if manifest_type == "provider_snapshot"
            else None
        ),
        "experiment_id": (
            str(manifest.get("spec", {}).get("experiment_id", ""))
            if manifest_type == "provider_snapshot"
            else None
        ),
        "validated": True,
        "prices_csv_sha256": prices_sha256,
    }


def _recompute_manifest_identity(manifest: dict[str, Any]) -> str:
    """Recompute the canonical identity hash of a manifest, excluding the
    identity key itself (mirrors ``src.data.market_provider._identity_sha256``)."""
    import hashlib as _hashlib

    identity = {k: v for k, v in manifest.items() if k != "provider_identity_sha256"}
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def run_us_hierarchical_rotation_validation(
    *,
    spec_path: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
    provider_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Produce authoritative validation evidence for the frozen US v2 spec.

    Parameters
    ----------
    provider_manifest_path : Path, optional
        Path to a provider_manifest.json or provider directory.  When provided,
        the manifest is rigorously validated (identity hash, market, symbol set,
        prices_csv binding, calendar coverage).  When omitted, the run is
        explicitly **non-authoritative** — it can NEVER emit
        ``us_hierarchical_rotation_independent_validation_required``.
    """
    spec_path = Path(spec_path).resolve()
    prices_csv = Path(prices_csv).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1.  Load and validate contract
    spec, pool, resolved_spec, pool_path = load_hierarchical_contract(spec_path)

    if not bool(spec.get("authoritative_validation_allowed")):
        raise ValueError("spec is not authorised for authoritative validation")
    if not bool(pool.get("authoritative_for_performance", True)):
        raise ValueError("pool is not authoritative for performance evaluation")

    # ---- resolve required provider symbols --------------------------------
    candidates = _candidate_symbols(pool)
    ref_provider_symbols: set[str] = set()
    for _display, meta in pool.get("references", {}).items():
        ref_provider_symbols.add(str(meta.get("provider_symbol", _display)))
    alias_providers: set[str] = set()
    for _display, meta in pool.get("symbol_metadata", {}).items():
        p_sym = str(meta.get("provider_symbol", _display))
        if p_sym != str(_display):
            alias_providers.add(p_sym)
    required_provider_symbols = set(candidates) | ref_provider_symbols | alias_providers
    required_count = len(required_provider_symbols)

    # ---- validate provider manifest (or mark non-authoritative) ------------
    manifest_validation: dict[str, Any] | None = None
    manifest_failed_gate: dict[str, Any] | None = None
    provider_manifest_validated = False

    if provider_manifest_path is not None:
        manifest_path = Path(provider_manifest_path).resolve()
        if manifest_path.is_dir():
            manifest_path = manifest_path / "provider_manifest.json"
        try:
            manifest_validation = _validate_provider_manifest(
                manifest_path,
                prices_csv,
                required_symbols=required_provider_symbols,
                required_count=required_count,
                expected_spec_sha256=sha256_file(spec_path),
                expected_pool_sha256=sha256_file(pool_path),
                expected_experiment_id=str(spec["experiment_id"]),
            )
            provider_manifest_validated = True
            write_json(
                output_dir / "provider_manifest_validation.json",
                manifest_validation,
            )
        except (ValueError, FileNotFoundError, KeyError) as exc:
            # Fail closed: write explicit artifacts, then re-raise
            _write_manifest_fail_artifacts(output_dir, spec, str(exc), manifest_path)
            raise
    else:
        # Non-authoritative: no manifest provided
        manifest_failed_gate = {
            "gate": "provider_manifest_required",
            "threshold": "manifest_required",
            "observed": "none",
            "passed": False,
            "reason": (
                "No provider_manifest_path was supplied.  This run is "
                "NON-AUTHORITATIVE and cannot emit "
                "us_hierarchical_rotation_independent_validation_required."
            ),
        }
        provider_manifest_validated = False

    # 2.  Pre-filter: compute raw source identity and exclude reserved rows
    #     as the FIRST data-boundary operation — before alias mapping,
    #     duplicate checks, readiness, indicators, ranks, returns, or metrics.
    reserved_start = pd.Timestamp(spec["evidence"]["independent_reserved"]["start"])
    raw_source_sha256 = sha256_file(prices_csv)
    observed_slab, slice_identity = _load_observed_slice(prices_csv, reserved_start)

    # Write observed-only temp CSV so downstream loaders never see reserved rows
    import os as _os
    import tempfile as _tempfile

    _tmp_fd, _observed_csv_path = _tempfile.mkstemp(suffix=".csv", prefix="observed_slice_")
    try:
        observed_slab.to_csv(_observed_csv_path, index=False)
        _os.close(_tmp_fd)
        del observed_slab

        # 3.  Provider readiness on observed slice only (fail-closed)
        provider = _verify_provider_readiness(_observed_csv_path, spec, pool)
        # Bind raw source identity (not the temp-file hash)
        provider["provider_identity_sha256"] = raw_source_sha256
        write_json(output_dir / "provider_readiness.json", provider)

        if not provider["provider_ready"]:
            decision = _fail_decision(
                spec,
                "us_hierarchical_rotation_not_supported_on_observed_evidence",
                "provider readiness failed",
                provider,
                provider_manifest_validated=provider_manifest_validated,
            )
            write_json(output_dir / "decision.json", decision)
            _write_fail_closed_artifacts(output_dir, spec, provider)
            _write_evidence_manifest(
                spec,
                spec_path,
                prices_csv,
                pool_path,
                output_dir,
                provider_manifest_validation=manifest_validation,
            )
            return decision

        # 4.  Load prices through the generic loader (observed-only temp CSV)
        root = _repository_root(resolved_spec)
        timing_spec, formula_path = build_runtime_timing_spec(spec, pool, repository_root=root)
        observed_prices = load_long_ohlcv_csv(_observed_csv_path, timing_spec)
    finally:
        Path(_observed_csv_path).unlink(missing_ok=True)

    # Double-gate: filter again for safety (already pre-filtered)
    observed_prices = observed_prices[observed_prices["date"] < reserved_start].copy()
    observed_row_count = int(observed_prices.shape[0])

    # Record boundary: raw source SHA + row counts
    observed_slice_identity = {
        **slice_identity,
        "raw_source_sha256": raw_source_sha256,
        "observed_row_count": observed_row_count,
        "observed_date_min": observed_prices["date"].min().date().isoformat(),
        "observed_date_max": observed_prices["date"].max().date().isoformat(),
    }

    # 5.  Compute indicators, signals, rotations, portfolio
    indicators = compute_hierarchical_indicators(observed_prices, timing_spec)
    signal_history, reference_history = generate_signal_history(indicators, timing_spec)
    candidates = _candidate_symbols(pool)
    benchmark = str(spec["market_regime"]["reference"])

    basket_scores, security_scores, rotations = build_hierarchical_rotation_history(
        indicators, signal_history, spec, pool
    )
    portfolio_history = build_hierarchical_portfolio_history(
        indicators, signal_history, rotations, spec
    )

    # Internal counterfactual for attribution: no market regime
    counterfactual_no_mr = _counterfactual_no_market_regime(indicators, timing_spec, spec, pool)

    # 5.  Build return frames per window
    cost_bps = float(
        spec.get("validation", {}).get("execution", {}).get("cost_bps_per_unit_exposure_change", 10)
    )
    state_multipliers = {
        str(k): float(v) for k, v in spec["security_selection"]["absolute_state_filter"].items()
    }

    evidence = spec["evidence"]
    windows: list[tuple[str, str, str]] = [
        (
            "development_observed",
            evidence["development_observed"]["start"],
            evidence["development_observed"]["end"],
        ),
        (
            "falsification_only",
            evidence["falsification_only"]["start"],
            evidence["falsification_only"]["end"],
        ),
        (
            "full_observed",
            evidence["development_observed"]["start"],
            evidence["falsification_only"]["end"],
        ),
    ]

    all_baseline_metrics: dict[str, dict[str, Any]] = {}
    baseline_labels = [
        "equal_weight_pool_buy_and_hold",
        "time_series_state_only",
        "hierarchical_cross_section_only",
        "hierarchical_cross_section_plus_state",
    ]

    for window_name, w_start, w_end in windows:
        perf_frame, drift_frame = _build_return_frames(
            observed_prices, candidates, benchmark, w_start, w_end
        )
        perf_frame, drift_frame = _trim_return_frame_to_observable(
            perf_frame, drift_frame, benchmark
        )

        # (a) EW B&H — genuine buy-and-hold, initial entry cost only
        ew_rets, ew_diag = _ew_buy_hold_returns(perf_frame, candidates, cost_bps)
        qqq_rets = perf_frame[benchmark]
        ew_metrics = _baseline_metrics(
            ew_rets, qqq_rets, baseline_labels[0], window_name, candidates
        )
        ew_metrics["ew_entry_diagnostics"] = ew_diag

        # (b) State only — correct drift
        state_rets = _state_only_returns(
            perf_frame,
            drift_frame,
            signal_history,
            candidates,
            state_multipliers,
            cost_bps,
        )
        state_metrics = _baseline_metrics(
            state_rets, qqq_rets, baseline_labels[1], window_name, candidates
        )

        # (c) Cross-section only — independent of state filter
        cs_rets = _cross_section_only_returns(
            perf_frame,
            drift_frame,
            rotations,
            indicators,
            spec,
            pool,
            candidates,
            cost_bps,
        )
        cs_metrics = _baseline_metrics(
            cs_rets, qqq_rets, baseline_labels[2], window_name, candidates
        )

        # (d) Full — correct drift
        full_rets = _hierarchical_plus_state_returns(
            perf_frame,
            drift_frame,
            portfolio_history,
            candidates,
            cost_bps,
        )
        full_metrics = _baseline_metrics(
            full_rets, qqq_rets, baseline_labels[3], window_name, candidates
        )

        # EW-relative returns and drawdown improvements
        ew_total = ew_metrics["total_return_after_costs"]
        ew_dd = ew_metrics["maximum_drawdown"]
        for m in [state_metrics, cs_metrics, full_metrics]:
            m["ew_relative_return"] = float(m["total_return_after_costs"] - ew_total)
            m["drawdown_improvement_vs_ew"] = float(m["maximum_drawdown"] - ew_dd)

        for label, metrics in zip(
            baseline_labels, [ew_metrics, state_metrics, cs_metrics, full_metrics]
        ):
            if label not in all_baseline_metrics:
                all_baseline_metrics[label] = {}
            all_baseline_metrics[label][window_name] = metrics

    # Flatten for baseline_metrics.json
    baseline_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "baselines": {},
    }
    for label in baseline_labels:
        baseline_payload["baselines"][label] = all_baseline_metrics[label]

    write_json(output_dir / "baseline_metrics.json", baseline_payload)

    # 6.  Attribution with internal counterfactuals
    dev_ew = all_baseline_metrics["equal_weight_pool_buy_and_hold"]["development_observed"]
    dev_state = all_baseline_metrics["time_series_state_only"]["development_observed"]
    dev_cs = all_baseline_metrics["hierarchical_cross_section_only"]["development_observed"]
    dev_full = all_baseline_metrics["hierarchical_cross_section_plus_state"]["development_observed"]

    # Compute no-market-regime counterfactual returns
    dev_w_start = evidence["development_observed"]["start"]
    dev_w_end = evidence["development_observed"]["end"]
    dev_perf_frame, dev_drift_frame = _build_return_frames(
        observed_prices, candidates, benchmark, dev_w_start, dev_w_end
    )
    dev_perf_frame, dev_drift_frame = _trim_return_frame_to_observable(
        dev_perf_frame, dev_drift_frame, benchmark
    )
    no_mr_rets = _hierarchical_plus_state_returns(
        dev_perf_frame,
        dev_drift_frame,
        counterfactual_no_mr,
        candidates,
        cost_bps,
    )
    no_mr_metrics = _baseline_metrics(
        no_mr_rets,
        dev_perf_frame[benchmark],
        "internal_counterfactual_no_market_regime",
        "development_observed",
        candidates,
    )

    # Compute basket-rank counterfactual (cs with equal-weight baskets)
    cs_ew_baskets_rets = _cs_equal_weight_baskets_returns(
        dev_perf_frame,
        dev_drift_frame,
        rotations,
        indicators,
        spec,
        pool,
        candidates,
        cost_bps,
    )
    cs_ew_baskets_metrics = _baseline_metrics(
        cs_ew_baskets_rets,
        dev_perf_frame[benchmark],
        "internal_counterfactual_cs_equal_weight_baskets",
        "development_observed",
        candidates,
    )

    # Compute security-rank counterfactual (cs with equal-weight securities)
    cs_ew_securities_rets = _cs_equal_weight_securities_returns(
        dev_perf_frame,
        dev_drift_frame,
        rotations,
        indicators,
        spec,
        pool,
        candidates,
        cost_bps,
    )
    cs_ew_securities_metrics = _baseline_metrics(
        cs_ew_securities_rets,
        dev_perf_frame[benchmark],
        "internal_counterfactual_cs_equal_weight_securities",
        "development_observed",
        candidates,
    )

    attribution = _incremental_attribution(
        dev_ew,
        dev_state,
        dev_cs,
        dev_full,
        no_market_regime_metrics=no_mr_metrics,
        cs_ew_baskets_metrics=cs_ew_baskets_metrics,
        cs_ew_securities_metrics=cs_ew_securities_metrics,
    )
    write_json(output_dir / "attribution.json", attribution)

    # 7.  Concentration (with contribution analysis for the development window)
    dev_perf_for_contrib, dev_drift_for_contrib = _build_return_frames(
        observed_prices,
        candidates,
        benchmark,
        evidence["development_observed"]["start"],
        evidence["development_observed"]["end"],
    )
    dev_perf_for_contrib, dev_drift_for_contrib = _trim_return_frame_to_observable(
        dev_perf_for_contrib, dev_drift_for_contrib, benchmark
    )
    concentration = _concentration_analysis(
        portfolio_history,
        basket_scores,
        perf_frame=dev_perf_for_contrib,
        drift_frame=dev_drift_for_contrib,
        candidates=candidates,
        cost_bps=cost_bps,
    )
    concentration["max_single_symbol_concentration"] = concentration.get(
        "max_single_symbol_concentration", 0.0
    )
    write_json(output_dir / "concentration.json", concentration)

    # Back-populate positive_basket_contribution_ratio into full metrics
    pbcr = concentration.get("positive_basket_contribution_ratio")
    for window_name, _, _ in windows:
        full_m = all_baseline_metrics["hierarchical_cross_section_plus_state"].get(window_name, {})
        if full_m:
            full_m["positive_basket_contribution_ratio"] = pbcr

    # Re-write baseline_metrics.json with the populated contribution ratio
    baseline_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "baselines": {},
    }
    for label in baseline_labels:
        baseline_payload["baselines"][label] = all_baseline_metrics[label]
    write_json(output_dir / "baseline_metrics.json", baseline_payload)

    # 8.  Selection stability
    stability = _selection_stability(rotations)
    write_json(output_dir / "selection_stability.json", stability)

    # 9.  Gate checking
    gates_spec = spec.get("validation", {}).get("gates", {})
    full_metrics_by_window: dict[str, dict[str, Any]] = {}
    for window_name, _, _ in windows:
        full_metrics_by_window[window_name] = all_baseline_metrics[
            "hierarchical_cross_section_plus_state"
        ][window_name]

    gate_result = _check_gates(
        full_metrics_by_window,
        gates_spec,
        concentration,
        stability,
        all_baseline_metrics,
    )

    # 10. Decision
    all_passed = provider["provider_ready"] and gate_result["all_passed"]

    # Non-authoritative runs can NEVER emit independent_validation_required
    if not provider_manifest_validated:
        all_passed = False

    decision_value = (
        "us_hierarchical_rotation_independent_validation_required"
        if all_passed
        else "us_hierarchical_rotation_not_supported_on_observed_evidence"
    )
    reason = ""
    if not all_passed:
        failed = [k for k, v in gate_result.get("comparisons", {}).items() if not v]
        if not provider_manifest_validated:
            reason = "provider manifest not validated: " + (
                manifest_failed_gate["reason"]
                if manifest_failed_gate
                else "manifest not provided or validation failed"
            )
        elif not provider["provider_ready"]:
            reason = (
                f"provider not ready: missing={provider.get('missing_provider_symbols', [])}, "
                f"stale={provider.get('stale_provider_symbols', [])}"
            )
        else:
            reason = f"gates failed: {failed}"

    decision = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "market": str(spec["market"]),
        "decision": decision_value,
        "research_only": True,
        "trade_ready": False,
        "reserved_performance_opened": False,
        "observed_evidence_end": spec["evidence"]["falsification_only"]["end"],
        "reserved_start": spec["evidence"]["independent_reserved"]["start"],
        "provider_ready": provider["provider_ready"],
        "provider_manifest_validated": provider_manifest_validated,
        "gate_result": gate_result,
        "reason": reason,
        "observed_slice": observed_slice_identity,
    }

    # Inject manifest failed gate into gate_result for visibility
    if manifest_failed_gate is not None:
        decision["gate_result"]["comparisons"]["provider_manifest_required"] = False
        decision["gate_result"]["details"]["provider_manifest_required"] = manifest_failed_gate
        decision["gate_result"]["all_passed"] = False
    write_json(output_dir / "decision.json", decision)

    # 11. Report — write every hashed output before sealing the manifest.
    _write_report(
        output_dir,
        spec,
        provider,
        all_baseline_metrics,
        attribution,
        concentration,
        stability,
        gate_result,
        decision,
    )

    # 12. Evidence manifest
    _write_evidence_manifest(
        spec,
        spec_path,
        prices_csv,
        pool_path,
        output_dir,
        observed_slice=observed_slice_identity,
        provider_manifest_validation=manifest_validation,
    )

    return decision


# ---------------------------------------------------------------------------
# fail-closed helpers
# ---------------------------------------------------------------------------


def _fail_decision(
    spec: Mapping[str, Any],
    decision_value: str,
    reason: str,
    provider: dict[str, Any],
    *,
    provider_manifest_validated: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "market": str(spec["market"]),
        "decision": decision_value,
        "research_only": True,
        "trade_ready": False,
        "reserved_performance_opened": False,
        "observed_evidence_end": spec["evidence"]["falsification_only"]["end"],
        "reserved_start": spec["evidence"]["independent_reserved"]["start"],
        "provider_ready": provider.get("provider_ready", False),
        "provider_manifest_validated": provider_manifest_validated,
        "gate_result": {"all_passed": False, "comparisons": {}, "details": {}},
        "reason": reason,
    }


def _write_fail_closed_artifacts(
    output_dir: Path,
    spec: Mapping[str, Any],
    provider: dict[str, Any],
) -> None:
    """Write stub/status artifacts when provider readiness fails.

    Ensures evidence_manifest can reference every expected file.
    Performance is never implied when it was not evaluated.
    """
    stub_baselines = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "status": "provider_not_ready",
        "performance_evaluated": False,
        "reason": (
            f"provider not ready: missing={provider.get('missing_provider_symbols', [])}, "
            f"stale={provider.get('stale_provider_symbols', [])}"
        ),
        "baselines": {},
    }
    write_json(output_dir / "baseline_metrics.json", stub_baselines)

    stub_attribution = {
        "schema_version": "1.0",
        "status": "provider_not_ready",
        "performance_evaluated": False,
    }
    write_json(output_dir / "attribution.json", stub_attribution)

    stub_concentration = {
        "schema_version": "1.0",
        "status": "provider_not_ready",
        "performance_evaluated": False,
    }
    write_json(output_dir / "concentration.json", stub_concentration)

    stub_stability = {
        "schema_version": "1.0",
        "status": "provider_not_ready",
        "performance_evaluated": False,
    }
    write_json(output_dir / "selection_stability.json", stub_stability)

    # Write a report.md with the failure status
    lines = [
        "# US Hierarchical Cross-Sectional Rotation v2 — Validation Report",
        "",
        "## Status: PROVIDER NOT READY",
        "",
        f"- **Experiment**: `{spec['experiment_id']}`",
        f"- **Market**: {spec['market']}",
        "- **Performance evaluated**: False",
        "- **Trade ready**: False",
        "",
        "## Provider Readiness Failure",
        "",
        f"- Missing symbols: {provider.get('missing_provider_symbols', [])}",
        f"- Stale symbols: {provider.get('stale_provider_symbols', [])}",
        f"- Low coverage symbols: {provider.get('low_coverage_symbols', [])}",
        f"- Missing reference symbols: {provider.get('missing_reference_symbols', [])}",
        f"- Internal gap failures: {provider.get('internal_gap_failures', [])}",
        "",
        "Performance was not evaluated because the provider did not pass readiness checks.",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_manifest_fail_artifacts(
    output_dir: Path,
    spec: Mapping[str, Any],
    error_message: str,
    manifest_path: Path,
) -> None:
    """Write explicit fail-closed artifacts when manifest validation fails.

    Ensures the failure is visible and no performance claims are implied.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    fail_payload = {
        "schema_version": "1.0",
        "status": "manifest_validation_failed",
        "manifest_path": str(manifest_path),
        "error": error_message,
        "performance_evaluated": False,
    }
    write_json(output_dir / "provider_manifest_validation.json", fail_payload)

    decision = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "market": str(spec["market"]),
        "decision": ("us_hierarchical_rotation_not_supported_on_observed_evidence"),
        "research_only": True,
        "trade_ready": False,
        "reserved_performance_opened": False,
        "observed_evidence_end": spec["evidence"]["falsification_only"]["end"],
        "reserved_start": spec["evidence"]["independent_reserved"]["start"],
        "provider_ready": False,
        "provider_manifest_validated": False,
        "gate_result": {
            "all_passed": False,
            "comparisons": {"provider_manifest_validation": False},
            "details": {
                "provider_manifest_validation": {
                    "threshold": "manifest_must_be_valid",
                    "observed": error_message,
                    "passed": False,
                }
            },
        },
        "reason": f"provider manifest validation failed: {error_message}",
    }
    write_json(output_dir / "decision.json", decision)

    lines = [
        "# US Hierarchical Cross-Sectional Rotation v2 — Validation Report",
        "",
        "## Status: MANIFEST VALIDATION FAILED",
        "",
        f"- **Experiment**: `{spec['experiment_id']}`",
        f"- **Market**: {spec['market']}",
        "- **Performance evaluated**: False",
        "- **Trade ready**: False",
        "",
        "## Manifest Validation Error",
        "",
        "```",
        error_message,
        "```",
        "",
        f"Manifest path: `{manifest_path}`",
    ]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# evidence manifest
# ---------------------------------------------------------------------------


def _write_evidence_manifest(
    spec: Mapping[str, Any],
    spec_path: Path,
    prices_csv: Path,
    pool_path: Path,
    output_dir: Path,
    observed_slice: dict[str, Any] | None = None,
    provider_manifest_validation: dict[str, Any] | None = None,
) -> None:
    """Deterministic manifest binding all identities and output hashes."""
    output_files = [
        "provider_readiness.json",
        "provider_manifest_validation.json",
        "baseline_metrics.json",
        "attribution.json",
        "concentration.json",
        "selection_stability.json",
        "decision.json",
        "report.md",
    ]
    existing = [f for f in output_files if (output_dir / f).is_file()]
    output_hashes = {f: sha256_file(output_dir / f) for f in existing}

    base: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "market": str(spec["market"]),
        "provider_identity_sha256": sha256_file(prices_csv),
        "spec_identity_sha256": sha256_file(spec_path),
        "pool_identity_sha256": sha256_file(pool_path),
        "validation_implementation_sha256": sha256_file(Path(__file__)),
        "hierarchical_engine_implementation_sha256": sha256_file(
            Path(__file__).with_name("hierarchical_pool_rotation.py")
        ),
        "outputs": output_hashes,
    }
    formula_ref = (
        spec.get("architecture", {}).get("security_timing_component", {}).get("formula_source")
    )
    if formula_ref:
        formula_path = spec_path.parents[2] / str(formula_ref)
        if formula_path.is_file():
            base["timing_formula_identity_sha256"] = sha256_file(formula_path)

    if observed_slice is not None:
        base["observed_slice_identity"] = observed_slice
        base["observed_slice_identity_sha256"] = canonical_sha256(observed_slice)

    if provider_manifest_validation is not None:
        base["provider_manifest_sha256"] = provider_manifest_validation.get(
            "manifest_identity_sha256"
        )
        base["provider_manifest_content_sha256"] = provider_manifest_validation.get(
            "manifest_content_sha256"
        )
        base["provider_manifest_validated"] = provider_manifest_validation.get("validated", False)
        base["provider_manifest_type"] = provider_manifest_validation.get("manifest_type")
        base["source_hashes_verified"] = provider_manifest_validation.get("source_hashes_verified")
        base["source_attestation"] = provider_manifest_validation.get("source_attestation")
    else:
        base["provider_manifest_validated"] = False
        base["provider_manifest_sha256"] = None
        base["provider_manifest_content_sha256"] = None

    manifest = {
        **base,
        "manifest_identity_sha256": canonical_sha256(base),
    }
    write_json(output_dir / "evidence_manifest.json", manifest)


# ---------------------------------------------------------------------------
# report.md
# ---------------------------------------------------------------------------


def _fmt(val: Any) -> str:
    """Format an optional metric value for the report table."""
    if val is None:
        return "n/a"
    if isinstance(val, (int, float, np.integer, np.floating)):
        return f"{float(val):.4f}"
    return str(val)


def _write_report(
    output_dir: Path,
    spec: Mapping[str, Any],
    provider: dict[str, Any],
    baseline_metrics: dict[str, Any],
    attribution: dict[str, Any],
    concentration: dict[str, Any],
    stability: dict[str, Any],
    gate_result: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    """Write a concise methodology/results template consistent with research-only scope."""
    lines: list[str] = []

    lines.append("# US Hierarchical Cross-Sectional Rotation v2 — Validation Report")
    lines.append("")
    lines.append("## Status")
    lines.append("")
    lines.append(f"- **Experiment**: `{spec['experiment_id']}`")
    lines.append(f"- **Market**: {spec['market']}")
    lines.append(f"- **Benchmark**: {spec['benchmark']}")
    lines.append(f"- **Decision**: `{decision['decision']}`")
    lines.append(f"- **Research only**: {decision['research_only']}")
    lines.append(f"- **Trade ready**: {decision['trade_ready']}")
    lines.append(f"- **Reserved performance opened**: {decision['reserved_performance_opened']}")
    lines.append(f"- **Observed evidence end**: {decision['observed_evidence_end']}")
    lines.append(f"- **Provider ready**: {provider['provider_ready']}")
    if decision.get("observed_slice"):
        sl = decision["observed_slice"]
        lines.append(
            f"- **Reserved rows excluded**: {sl.get('reserved_rows_excluded', 0)} "
            f"(raw: {sl.get('raw_row_count', 0)}, observed: {sl.get('observed_row_count', 0)})"
        )
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("### Execution")
    lines.append(
        "- **Lag**: next-session open-to-open (signal at close(t) → execute at "
        "open(t+1) → return open(t+1)→open(t+2))"
    )
    lines.append(
        f"- **Cost**: {spec.get('portfolio', {}).get('transaction_cost_bps_per_unit_exposure_change', 10)} "
        "bps per unit exposure change"
    )
    lines.append(
        f"- **Reserved**: all rows >= {spec['evidence']['independent_reserved']['start']} "
        "excluded before any computation"
    )
    lines.append("")
    lines.append("### Baselines (all after costs)")
    lines.append("1. Equal-weight pool buy-and-hold (genuine: buy once, let drift)")
    lines.append(
        "2. Time-series state machine only (daily rebalance, equal weight positive-state symbols)"
    )
    lines.append(
        "3. Hierarchical cross-sectional rotation only (state-free: basket + "
        "security selection from indicators only; no market-regime gate, "
        "no absolute-state filter)"
    )
    lines.append("4. Hierarchical rotation + state (full strategy)")
    lines.append("")
    lines.append("### Windows")
    lines.append(
        f"- **Development**: {spec['evidence']['development_observed']['start']} → "
        f"{spec['evidence']['development_observed']['end']}"
    )
    lines.append(
        f"- **Falsification**: {spec['evidence']['falsification_only']['start']} → "
        f"{spec['evidence']['falsification_only']['end']}"
    )
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("### Provider Readiness")
    lines.append(f"- Required symbols: {provider['required_provider_count']}")
    lines.append(f"- Found: {provider['found_provider_count']}")
    lines.append(f"- Missing: {provider.get('missing_provider_symbols', [])}")
    lines.append(f"- Stale: {provider.get('stale_provider_symbols', [])}")
    short_history = provider.get("short_history_diagnostics", {})
    lines.append(f"- Short-history diagnostics: {len(short_history)} symbol(s)")
    if short_history:
        lines.append(f"- Short-history symbols: {sorted(short_history)}")
        lines.append(
            "- Treatment: candidate coverage is measured from its actual first "
            "available date; the buy-and-hold baseline excludes names unavailable "
            "at window entry, while ranked strategies may use them only after "
            "their indicators and executable returns are complete."
        )
    lines.append("")
    lines.append("### Baseline Metrics (Development Window)")
    lines.append("")
    lines.append(
        "| Baseline | Total Return | Ann. Return | Max DD | QQQ Rel. | "
        "EW Rel. | Upside Cap. | Downside Cap. | Avg Cash | "
        "Turnover/yr | Avg Hold |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for label in [
        "equal_weight_pool_buy_and_hold",
        "time_series_state_only",
        "hierarchical_cross_section_only",
        "hierarchical_cross_section_plus_state",
    ]:
        m = baseline_metrics.get(label, {}).get("development_observed", {})
        if m and m.get("status") == "observed":
            lines.append(
                f"| {label} | {m.get('total_return_after_costs', 0):.4f} | "
                f"{m.get('annualized_return_after_costs', 0):.4f} | "
                f"{m.get('maximum_drawdown', 0):.4f} | "
                f"{m.get('qqq_relative_return', 0):.4f} | "
                f"{_fmt(m.get('ew_relative_return'))} | "
                f"{_fmt(m.get('upside_capture_vs_qqq'))} | "
                f"{_fmt(m.get('downside_capture_vs_qqq'))} | "
                f"{_fmt(m.get('average_cash_weight'))} | "
                f"{_fmt(m.get('annual_turnover'))} | "
                f"{_fmt(m.get('average_holding_sessions'))} |"
            )

    lines.append("")
    lines.append("### Gate Results")
    lines.append("")
    lines.append("| Gate | Threshold | Observed | Passed |")
    lines.append("|---|---|---|---|")
    for gate_key, detail in gate_result.get("details", {}).items():
        lines.append(
            f"| {gate_key} | {_fmt(detail.get('threshold'))} | "
            f"{_fmt(detail.get('observed'))} | "
            f"{detail['passed']} |"
        )
    lines.append("")
    lines.append(f"**All gates passed**: {gate_result.get('all_passed', False)}")
    lines.append("")
    lines.append("### Attribution")
    lines.append("")
    lines.append("Each effect isolates one component by varying it while holding")
    lines.append("the others as constant as the architecture permits. Effects are")
    lines.append("**non-additive** — the residual captures the non-additive component.")
    lines.append("")

    mr_eff = attribution.get("market_regime_effect")
    lines.append(f"- Market regime effect (full minus no-market-regime): {_fmt(mr_eff)}")
    lines.append(f"  - Definition: {attribution.get('market_regime_effect_definition', 'n/a')}")

    br_eff = attribution.get("basket_rank_effect")
    lines.append(f"- Basket rank effect (cs_only minus cs_ew_baskets): {_fmt(br_eff)}")
    lines.append(f"  - Definition: {attribution.get('basket_rank_effect_definition', 'n/a')}")

    sr_eff = attribution.get("security_rank_effect")
    lines.append(f"- Security rank effect (cs_only minus cs_ew_securities): {_fmt(sr_eff)}")
    lines.append(f"  - Definition: {attribution.get('security_rank_effect_definition', 'n/a')}")

    so_eff = attribution.get("state_overlay_effect")
    lines.append(f"- State overlay effect (no-market-regime minus cs_only): {_fmt(so_eff)}")
    lines.append(f"  - Definition: {attribution.get('state_overlay_effect_definition', 'n/a')}")

    lines.append("")
    lines.append("#### Counterfactual totals")
    lines.append(
        f"- No-market-regime full: {_fmt(attribution.get('counterfactual_no_market_regime_total'))}"
    )
    lines.append(
        f"- Equal-weight gate-passing baskets: "
        f"{_fmt(attribution.get('counterfactual_equal_weight_baskets_total'))}"
    )
    lines.append(
        f"- Equal-weight gate-passing securities: "
        f"{_fmt(attribution.get('counterfactual_equal_weight_securities_total'))}"
    )
    lines.append("")
    lines.append(f"- Sum of named effects: {_fmt(attribution.get('sum_of_named_effects'))}")
    lines.append(f"- Total excess vs EW: {_fmt(attribution.get('total_excess_vs_ew'))}")
    lines.append(f"- Residual (non-additive): {_fmt(attribution.get('residual'))}")
    lines.append(f"- Effects are non-additive: {attribution.get('effects_are_non_additive', True)}")
    lines.append("")
    lines.append("### Concentration")
    lines.append(
        f"- Max single-symbol concentration: "
        f"{_fmt(concentration.get('max_single_symbol_concentration'))}"
    )
    lines.append(
        f"- Average portfolio breadth: {_fmt(concentration.get('average_portfolio_breadth'))}"
    )
    lines.append(
        f"- Positive basket contribution ratio: "
        f"{_fmt(concentration.get('positive_basket_contribution_ratio'))}"
    )
    lines.append("")
    lines.append("#### Basket breadth and gross contribution")
    lines.append("")
    lines.append("| Basket | Selection frequency | Gross contribution |")
    lines.append("|---|---|---|")
    basket_frequencies = concentration.get("basket_selection_frequency", {})
    basket_contributions = concentration.get("basket_contributions", {})
    for basket in sorted(set(basket_frequencies) | set(basket_contributions)):
        lines.append(
            f"| {basket} | {_fmt(basket_frequencies.get(basket))} | "
            f"{_fmt(basket_contributions.get(basket))} |"
        )
    lines.append("")
    lines.append("### Selection Stability")
    lines.append(f"- Basket stability: {_fmt(stability.get('basket_stability'))}")
    lines.append(f"- Symbol stability: {_fmt(stability.get('symbol_stability'))}")
    lines.append(f"- Rapid replacement rate: {_fmt(stability.get('rapid_replacement_rate'))}")
    lines.append("")

    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
