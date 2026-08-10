"""Frozen volatility-term-structure overlays for the QQQ v4.2 family.

Two structural 1:1 relationships are tested without threshold search:

* VIX9D < VIX confirms that the acute shock has normalized before a v4.27
  panic-repair boost activates.
* VIX > VIX3M marks backwardation and caps formal state-2 TQQQ at 50%.

The formal v4.2 state trace is never changed.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.v4_2_panic_repair_boost import (
    build_panic_repair_trace,
    panic_repair_weights,
    run_panic_repair_comparison,
)

BASELINE = "current_v4_2"
PANIC = "v4_27_panic_repair_boost"
TIMING = "v4_28_panic_repair_vix9d_confirmed"
GUARD = "v4_28_backwardation_guard"
JOINT = "v4_28_term_structure_joint"
TRANSACTION_COST_BPS_PER_TURNOVER_UNIT = 10.0
STATE2_GUARDED_TQQQ_WEIGHT = 0.50
PRIMARY_TERM_STRUCTURE_START = pd.Timestamp("2014-01-01")


def _normalise_close(frame: pd.DataFrame, symbol: str) -> pd.Series:
    if "close" not in frame.columns:
        raise ValueError(f"{symbol} history missing close")
    out = frame.copy()
    out.index = pd.to_datetime(out.index, errors="raise").tz_localize(None).normalize()
    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
    if out.index.has_duplicates:
        raise ValueError(f"{symbol} history contains duplicate dates")
    close = pd.to_numeric(out["close"], errors="coerce")
    if bool(close.dropna().le(0.0).any()):
        raise ValueError(f"{symbol} contains non-positive close values")
    return close.rename(f"{symbol.lower()}_close")


def build_term_structure_trace(
    daily: pd.DataFrame,
    vix9d: pd.DataFrame,
    vix3m: pd.DataFrame,
) -> pd.DataFrame:
    """Build close-time VIX9D/VIX/VIX3M relationships with no filling."""
    if "vix_close" not in daily.columns:
        raise ValueError("daily trace missing vix_close")
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")

    vix = pd.to_numeric(daily["vix_close"], errors="coerce")
    short = _normalise_close(vix9d, "VIX9D").reindex(daily.index)
    medium = _normalise_close(vix3m, "VIX3M").reindex(daily.index)
    complete = vix.notna() & short.notna() & medium.notna()
    acute_normalized = short.lt(vix) & complete
    backwardation = vix.gt(medium) & complete

    trace = pd.DataFrame(
        {
            "vix9d_close": short,
            "vix3m_close": medium,
            "term_structure_complete_at_close": complete.astype(bool),
            "acute_normalized_at_close": acute_normalized.astype(bool),
            "curve_backwardation_at_close": backwardation.astype(bool),
        },
        index=daily.index,
    )
    trace["acute_normalized_at_open"] = trace["acute_normalized_at_close"].shift(
        1, fill_value=False
    )
    trace["curve_backwardation_at_open"] = trace["curve_backwardation_at_close"].shift(
        1, fill_value=False
    )
    return trace


def build_term_confirmed_panic_trace(
    daily: pd.DataFrame,
    fear_greed: pd.DataFrame,
    term_trace: pd.DataFrame,
) -> pd.DataFrame:
    """Reuse v4.27 panic arming but require VIX9D<VIX for repair activation."""
    base = build_panic_repair_trace(daily, fear_greed)
    term = term_trace.reindex(daily.index)
    required = {"acute_normalized_at_close"}
    missing = sorted(required - set(term.columns))
    if missing:
        raise ValueError(f"term trace missing columns: {missing}")

    activation_ready = base["repair_ready_at_close"].astype(bool) & term[
        "acute_normalized_at_close"
    ].fillna(False).astype(bool)
    armed = False
    active = False
    current_event: int | None = None
    armed_rows: list[bool] = []
    active_rows: list[bool] = []
    event_rows: list[int | None] = []
    reasons: list[str] = []

    for panic_start, ready, failure, state, event_id in zip(
        base["panic_start_at_close"].astype(bool),
        activation_ready.astype(bool),
        daily["stress_price_failure"].fillna(True).astype(bool),
        daily["decision_state"].astype(int),
        base["panic_repair_event_id"],
        strict=True,
    ):
        reason = "hold_active" if active else ("hold_armed" if armed else "hold_idle")
        if bool(panic_start):
            armed = True
            active = False
            current_event = int(event_id) if pd.notna(event_id) else None
            reason = "panic_arms"
        elif int(state) == 2:
            if active:
                reason = "formal_state2_replaces_boost"
            elif armed:
                reason = "formal_state2_cancels_arm"
            active = False
            armed = False
            current_event = None
        elif active and bool(failure):
            active = False
            current_event = None
            reason = "repair_failure_exits_boost"
        elif armed and bool(ready) and int(state) in (0, 1):
            armed = False
            active = True
            reason = "term_confirmed_repair_activates_boost"

        armed_rows.append(bool(armed))
        active_rows.append(bool(active))
        event_rows.append(current_event)
        reasons.append(reason)

    trace = base.copy()
    trace["acute_normalized_at_close"] = term["acute_normalized_at_close"].fillna(False)
    trace["term_confirmed_repair_ready_at_close"] = activation_ready.astype(bool)
    trace["panic_repair_armed_at_close"] = pd.Series(armed_rows, index=daily.index, dtype=bool)
    trace["panic_repair_active_at_close"] = pd.Series(active_rows, index=daily.index, dtype=bool)
    trace["panic_repair_event_id"] = pd.Series(event_rows, index=daily.index, dtype="Int64")
    trace["panic_repair_reason_at_close"] = reasons
    trace["panic_repair_active_at_open"] = trace["panic_repair_active_at_close"].shift(
        1, fill_value=False
    )
    trace["panic_repair_reason_at_open"] = (
        trace["panic_repair_reason_at_close"].shift(1).fillna("initial_entry")
    )
    return trace


def _source_weights(source: StrategyResult) -> pd.DataFrame:
    columns = ["weight_QQQI", "weight_QQQ", "weight_TQQQ"]
    missing = sorted(set(columns) - set(source.daily.columns))
    if missing:
        raise ValueError(f"source missing weight columns: {missing}")
    return (
        source.daily[columns]
        .rename(
            columns={
                "weight_QQQI": "QQQI",
                "weight_QQQ": "QQQ",
                "weight_TQQQ": "TQQQ",
            }
        )
        .astype(float)
        .copy()
    )


def apply_backwardation_guard(
    daily: pd.DataFrame,
    weights: pd.DataFrame,
    term_trace: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series]:
    """Cap TQQQ at 50% only in executed state 2 after a backwardated close."""
    out = weights.copy()
    backwardation_at_open = (
        term_trace["curve_backwardation_at_open"].reindex(out.index).fillna(False).astype(bool)
    )
    eligible = daily["position_state"].astype(int).eq(2) & backwardation_at_open
    out.loc[eligible, "QQQI"] = 0.0
    out.loc[eligible, "QQQ"] = 1.0 - STATE2_GUARDED_TQQQ_WEIGHT
    out.loc[eligible, "TQQQ"] = STATE2_GUARDED_TQQQ_WEIGHT

    if not np.allclose(out.sum(axis=1), 1.0):
        raise AssertionError("term-structure weights must sum to one")
    if bool((out < -1e-12).any().any()):
        raise AssertionError("term-structure weights cannot be negative")
    outside = daily["position_state"].astype(int).ne(2) | ~backwardation_at_open
    if not np.allclose(out.loc[outside], weights.loc[outside]):
        raise AssertionError("backwardation guard changed an ineligible session")
    return out, eligible.astype(bool)


def _run_weights(
    source: StrategyResult,
    weights: pd.DataFrame,
    *,
    name: str,
    extra_daily: pd.DataFrame | None = None,
) -> StrategyResult:
    daily = source.daily.copy()
    if extra_daily is not None:
        overlap = [column for column in extra_daily.columns if column in daily.columns]
        if overlap:
            daily = daily.drop(columns=overlap)
        daily = daily.join(extra_daily.reindex(daily.index))
    weights = weights.reindex(daily.index)
    for asset in ("QQQI", "QQQ", "TQQQ"):
        daily[f"weight_{asset}"] = weights[asset]
    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in ("QQQI", "QQQ", "TQQQ")
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * TRANSACTION_COST_BPS_PER_TURNOVER_UNIT / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    changes = weights.loc[daily.index].ne(weights.loc[daily.index].shift()).any(axis=1)
    metrics.update(
        {
            "strategy": name,
            "switch_count": int(max(int(changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
        }
    )
    trades = daily.loc[changes].reset_index(names="date")
    return StrategyResult(name, daily, trades, metrics)


def _coverage(trace: pd.DataFrame) -> dict[str, Any]:
    eligible = trace.loc[trace.index >= PRIMARY_TERM_STRUCTURE_START]
    complete = eligible["term_structure_complete_at_close"].astype(bool)
    return {
        "start": eligible.index.min().date().isoformat() if len(eligible) else None,
        "end": eligible.index.max().date().isoformat() if len(eligible) else None,
        "sessions": int(len(eligible)),
        "complete_sessions": int(complete.sum()),
        "coverage": float(complete.mean()) if len(complete) else 0.0,
        "missing_sessions": int((~complete).sum()),
    }


def run_term_structure_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    fear_greed: pd.DataFrame,
    vix9d: pd.DataFrame,
    vix3m: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, StrategyResult], dict[str, Any]]:
    """Run the five frozen v4.28 comparators on identical sessions and costs."""
    _, base_results = run_panic_repair_comparison(bars, bridge_contract, fear_greed)
    baseline = base_results[BASELINE]
    panic = base_results[PANIC]
    daily = baseline.daily.copy()
    term = build_term_structure_trace(daily, vix9d, vix3m)

    timing_trace = build_term_confirmed_panic_trace(daily, fear_greed, term)
    timing_weights = panic_repair_weights(daily, timing_trace)
    timing = _run_weights(
        baseline,
        timing_weights,
        name=TIMING,
        extra_daily=term.join(
            timing_trace[
                [
                    "term_confirmed_repair_ready_at_close",
                    "panic_repair_active_at_open",
                    "panic_repair_reason_at_open",
                ]
            ]
        ),
    )

    baseline_weights = _source_weights(baseline)
    guarded_weights, guarded = apply_backwardation_guard(daily, baseline_weights, term)
    guard_extra = term.copy()
    guard_extra["backwardation_guard_active"] = guarded
    guard = _run_weights(
        baseline,
        guarded_weights,
        name=GUARD,
        extra_daily=guard_extra,
    )

    joint_weights, joint_guarded = apply_backwardation_guard(daily, timing_weights, term)
    joint_extra = term.join(
        timing_trace[
            [
                "term_confirmed_repair_ready_at_close",
                "panic_repair_active_at_open",
                "panic_repair_reason_at_open",
            ]
        ]
    )
    joint_extra["backwardation_guard_active"] = joint_guarded
    joint = _run_weights(
        baseline,
        joint_weights,
        name=JOINT,
        extra_daily=joint_extra,
    )

    results = {
        BASELINE: baseline,
        PANIC: panic,
        TIMING: timing,
        GUARD: guard,
        JOINT: joint,
    }
    headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    diagnostics = {
        "term_structure_coverage": _coverage(term),
        "acute_normalized_sessions": int(term["acute_normalized_at_close"].sum()),
        "backwardation_sessions": int(term["curve_backwardation_at_close"].sum()),
        "timing_boost_sessions": int(
            timing.daily.get(
                "panic_repair_active_at_open", pd.Series(False, index=timing.daily.index)
            )
            .fillna(False)
            .sum()
        ),
        "guarded_state2_sessions": int(
            guard.daily.get("backwardation_guard_active", pd.Series(False, index=guard.daily.index))
            .fillna(False)
            .sum()
        ),
        "joint_guarded_state2_sessions": int(
            joint.daily.get("backwardation_guard_active", pd.Series(False, index=joint.daily.index))
            .fillna(False)
            .sum()
        ),
        "same_formal_state_trace": all(
            result.daily["position_state"].equals(baseline.daily["position_state"])
            for result in results.values()
        ),
    }
    if not diagnostics["same_formal_state_trace"]:
        raise AssertionError("v4.28 changed the formal v4.2 state trace")
    return headline, results, diagnostics
