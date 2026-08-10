"""Frozen BYD v1.3 challenger built strictly as a delta on formal v1.2.

The challenger may change only three things relative to the maintained v1.2
implementation:

1. a 20-session minimum hold on the existing base risk-state target changes;
2. a 55% BYD / 45% 515180 allocation while the held base target is defensive
   and the governed market state is ``bear``;
3. a 15% maximum financed expansion with convex power 2.0.

Everything else -- canonical inputs, v1.2 baseline, market/volatility states,
execution, costs, financing and metrics -- is reused from maintained modules.
There is intentionally no duplicate v1.2 reconstruction here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.research.byd_515180_allocation import (
    AllocationResult,
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    metrics,
)
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    build_decisions as build_v12_decisions,
    momentum_scale,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    build_expansion_state,
    run_financed_allocation,
)

MODEL_ID = "byd_v1_3_min_hold_bear_defense"
MIN_HOLD_SESSIONS = 20
BEAR_DEFENSE_BYD = 0.55
BEAR_DEFENSE_ETF = 0.45
MAX_FINANCED_INCREMENT = 0.15
FULL_INCREMENT_MOMENTUM = 0.15
CONVEX_POWER = 2.0


@dataclass(frozen=True)
class ChallengeResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]
    comparison: pd.DataFrame
    period_attribution: pd.DataFrame


def _minimum_hold_targets(
    desired: pd.Series,
    *,
    min_hold_sessions: int = MIN_HOLD_SESSIONS,
) -> pd.Series:
    """Delay formal base-target changes until the current state is mature.

    The first overlap state is treated as already mature because it is inherited
    from the canonical pre-overlap v1.2 history rather than created on the ETF
    overlap start date. No market indicator is recomputed inside this function.
    """
    if min_hold_sessions < 1:
        raise ValueError("min_hold_sessions must be positive")
    if desired.empty:
        return desired.astype(float).copy()
    if desired.isna().any():
        raise ValueError("base target contains missing values")

    current = float(desired.iloc[0])
    held = min_hold_sessions
    values = [current]
    for raw_target in desired.iloc[1:]:
        target = float(raw_target)
        if not np.isclose(target, current, atol=1e-12) and held >= min_hold_sessions:
            current = target
            held = 1
        else:
            held += 1
        values.append(current)
    return pd.Series(values, index=desired.index, dtype=float, name="base_byd_weight")


def build_v13_decision(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return exact v1.2 baseline decision, v1.3 decision and diagnostics."""
    v12_decisions, v12_diagnostics = build_v12_decisions(common, signals)
    v12_decision = v12_decisions[V12_MODEL_ID]
    formal_base = v12_diagnostics["base_byd_weight"].astype(float)

    held_base = _minimum_hold_targets(formal_base)
    is_bear = common["market_state"].eq("bear")
    v13_base = held_base.copy()
    bear_defense = v13_base.lt(1.0) & is_bear
    v13_base.loc[bear_defense] = BEAR_DEFENSE_BYD

    v13_signals = signals.copy()
    v13_signals["base_byd_weight"] = v13_base
    v13_state = build_expansion_state(common, v13_signals)
    active = v13_state["trend_expansion_active"].astype(bool)
    scale = momentum_scale(
        common["mom_20"],
        full_increment_momentum=FULL_INCREMENT_MOMENTUM,
        convex_power=CONVEX_POWER,
    )
    increment = active.astype(float) * MAX_FINANCED_INCREMENT * scale

    byd_weight = v13_base + increment
    etf_weight = (1.0 - v13_base).where(increment.eq(0.0), 0.0)
    cash_weight = 1.0 - byd_weight - etf_weight
    v13_decision = pd.DataFrame(
        {
            "byd_weight": byd_weight,
            "etf_weight": etf_weight,
            "cash_weight": cash_weight,
        },
        index=common.index,
    )

    if not np.allclose(v13_decision.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("v1.3 weights do not sum to one")
    if v13_decision["byd_weight"].lt(0.0).any() or v13_decision["etf_weight"].lt(0.0).any():
        raise AssertionError("v1.3 contains a negative risky-asset weight")
    if v13_decision["byd_weight"].gt(1.15 + 1e-12).any():
        raise AssertionError("v1.3 exceeds the frozen 115% BYD cap")
    if (increment.gt(0.0) & ~active).any():
        raise AssertionError("v1.3 financing exists outside the inherited expansion state")

    diagnostics = v13_state.copy()
    diagnostics["formal_base_byd_weight"] = formal_base
    diagnostics["held_base_byd_weight"] = held_base
    diagnostics["bear_defense_active"] = bear_defense
    diagnostics["momentum_scale"] = scale
    diagnostics["financed_increment"] = increment
    diagnostics["candidate_byd_weight"] = byd_weight
    return v12_decision, v13_decision, diagnostics


def run_challenger(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> dict[str, AllocationResult]:
    """Run exact maintained v1.2 and the frozen v1.3 challenger."""
    v12_results, _ = run_v12_candidates(
        common,
        signals,
        cost_bps=cost_bps,
        annual_financing_rate=annual_financing_rate,
    )
    _, v13_decision, _ = build_v13_decision(common, signals)
    v13_result = run_financed_allocation(
        MODEL_ID,
        common,
        v13_decision,
        cost_bps=cost_bps,
        annual_financing_rate=annual_financing_rate,
    )
    return {V12_MODEL_ID: v12_results[V12_MODEL_ID], MODEL_ID: v13_result}


def run_primary_and_stress(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[dict[str, AllocationResult], dict[str, AllocationResult]]:
    primary = run_challenger(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    stress = run_challenger(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    return primary, stress


def _window_metrics(result: AllocationResult, window: str) -> dict[str, float]:
    start, end = WINDOWS[window]
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty evaluation window: {window}")
    return metrics(block)


def comparison_table(
    primary: dict[str, AllocationResult],
    stress: dict[str, AllocationResult],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario, results in (("primary", primary), ("stress", stress)):
        for model_id in (V12_MODEL_ID, MODEL_ID):
            for window in WINDOWS:
                rows.append(
                    {
                        "scenario": scenario,
                        "model": model_id,
                        "window": window,
                        **_window_metrics(results[model_id], window),
                    }
                )
    return pd.DataFrame(rows)


def period_attribution(primary: dict[str, AllocationResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    positive: dict[str, float] = {}
    for window in ("development", "fixed_validation", "retrospective_2025_plus"):
        start, end = WINDOWS[window]
        baseline = primary[V12_MODEL_ID].daily.loc[start:end, "net_return"].dropna()
        candidate = primary[MODEL_ID].daily.loc[start:end, "net_return"].dropna()
        baseline_wealth = float((1.0 + baseline).prod())
        candidate_wealth = float((1.0 + candidate).prod())
        relative = candidate_wealth / baseline_wealth - 1.0
        positive[window] = max(relative, 0.0)
        rows.append({"window": window, "relative_terminal_wealth": relative})
    positive_total = sum(positive.values())
    for row in rows:
        contribution = positive[row["window"]]
        row["positive_contribution_share"] = (
            contribution / positive_total if positive_total > 0.0 else 0.0
        )
    return pd.DataFrame(rows)


def evaluate_challenge(
    primary: dict[str, AllocationResult],
    stress: dict[str, AllocationResult],
    *,
    maximum_cagr_shortfall_pp: float = 0.50,
    minimum_drawdown_improvement_pp: float = 2.0,
    maximum_round_trips_per_year: float = 4.0,
    maximum_positive_period_share: float = 0.60,
) -> ChallengeResult:
    comparison = comparison_table(primary, stress)
    attribution = period_attribution(primary)

    def row(scenario: str, model: str, window: str) -> pd.Series:
        selected = comparison[
            (comparison["scenario"] == scenario)
            & (comparison["model"] == model)
            & (comparison["window"] == window)
        ]
        if len(selected) != 1:
            raise AssertionError(f"missing comparison row: {scenario}/{model}/{window}")
        return selected.iloc[0]

    p_base = row("primary", V12_MODEL_ID, "full_overlap")
    p_cand = row("primary", MODEL_ID, "full_overlap")
    s_base = row("stress", V12_MODEL_ID, "full_overlap")
    s_cand = row("stress", MODEL_ID, "full_overlap")
    val_base = row("primary", V12_MODEL_ID, "fixed_validation")
    val_cand = row("primary", MODEL_ID, "fixed_validation")
    recent_base = row("primary", V12_MODEL_ID, "retrospective_2025_plus")
    recent_cand = row("primary", MODEL_ID, "retrospective_2025_plus")

    cagr_tolerance = maximum_cagr_shortfall_pp / 100.0
    drawdown_improvement = minimum_drawdown_improvement_pp / 100.0
    largest_period_share = float(attribution["positive_contribution_share"].max())

    gates = {
        "primary_full_cagr": float(p_cand["cagr"]) >= float(p_base["cagr"]) - cagr_tolerance,
        "primary_full_sharpe": float(p_cand["sharpe"]) >= float(p_base["sharpe"]),
        "primary_full_calmar": float(p_cand["calmar"]) >= float(p_base["calmar"]),
        "primary_full_drawdown": float(p_cand["max_drawdown"]) >= float(p_base["max_drawdown"]) + drawdown_improvement,
        "fixed_validation_cagr": float(val_cand["cagr"]) >= float(val_base["cagr"]),
        "retrospective_2025_plus_cagr": float(recent_cand["cagr"]) >= float(recent_base["cagr"]),
        "turnover_cap": float(p_cand["round_trips_per_year"]) <= maximum_round_trips_per_year,
        "stress_full_cagr": float(s_cand["cagr"]) >= float(s_base["cagr"]) - cagr_tolerance,
        "stress_full_calmar": float(s_cand["calmar"]) >= float(s_base["calmar"]),
        "stress_full_drawdown": float(s_cand["max_drawdown"]) >= float(s_base["max_drawdown"]) + drawdown_improvement,
        "positive_period_concentration": largest_period_share <= maximum_positive_period_share,
    }
    supported = all(gates.values())
    diagnostics = {
        "largest_positive_period_share": largest_period_share,
        "primary_cagr_delta": float(p_cand["cagr"] - p_base["cagr"]),
        "primary_sharpe_delta": float(p_cand["sharpe"] - p_base["sharpe"]),
        "primary_calmar_delta": float(p_cand["calmar"] - p_base["calmar"]),
        "primary_drawdown_improvement": float(p_cand["max_drawdown"] - p_base["max_drawdown"]),
        "stress_cagr_delta": float(s_cand["cagr"] - s_base["cagr"]),
        "stress_calmar_delta": float(s_cand["calmar"] - s_base["calmar"]),
        "stress_drawdown_improvement": float(s_cand["max_drawdown"] - s_base["max_drawdown"]),
    }
    return ChallengeResult(
        decision="byd_v1_3_supported" if supported else "byd_v1_3_not_supported",
        gates=gates,
        diagnostics=diagnostics,
        comparison=comparison,
        period_attribution=attribution,
    )
