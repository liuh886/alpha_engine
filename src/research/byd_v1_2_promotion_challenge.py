"""Governed BYD v1.2 promotion challenge.

The historical sample is fully consumed. This module performs diagnostic
candidate selection only and cannot authorize formal promotion.

All challengers preserve the original frozen trend-state entry and exit rules
from ``byd_v1_2_trend_expansion``. They differ only in how the 12.5% financed
increment is budgeted after that state becomes active.
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
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    build_expansion_state,
    run_financed_allocation,
)

BASELINE = "byd_v1_1"
ORIGINAL = "byd_v1_2_original_1125"
EPISODE_BUDGET = "byd_v1_2_episode_budget_20"
VOLATILITY_BUDGET = "byd_v1_2_volatility_budget_30"
RELATIVE_STRENGTH = "byd_v1_2_relative_strength_60"
CHALLENGERS = (EPISODE_BUDGET, VOLATILITY_BUDGET, RELATIVE_STRENGTH)

MAX_INCREMENT = 0.125
EPISODE_SESSION_BUDGET = 20
ANNUALIZED_VOLATILITY_BUDGET = 0.30
RELATIVE_STRENGTH_LOOKBACK = 60
FINANCING_DAY_COUNT = 252.0


@dataclass(frozen=True)
class ChallengeDecision:
    decision: str
    selected_candidate: str | None
    eligible_candidates: tuple[str, ...]
    gates: dict[str, dict[str, bool]]
    diagnostics: dict[str, dict[str, float]]
    promotion_authorized: bool = False


def _episode_age(active: pd.Series) -> pd.Series:
    starts = active & ~active.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(active)
    return active.groupby(episode_id).cumsum().where(active, 0).astype(int)


def _weights(base: pd.Series, increment: pd.Series) -> pd.DataFrame:
    increment = increment.reindex(base.index).fillna(0.0).astype(float)
    if (increment < -1e-12).any() or (increment > MAX_INCREMENT + 1e-12).any():
        raise AssertionError("financed increment outside frozen range")
    if (increment.gt(0.0) & ~base.eq(1.0)).any():
        raise AssertionError("financing is allowed only in BYD v1.1 risk-on state")

    byd = base + increment
    etf = (1.0 - base).where(increment.eq(0.0), 0.0)
    cash = 1.0 - byd - etf
    frame = pd.DataFrame(
        {"byd_weight": byd, "etf_weight": etf, "cash_weight": cash},
        index=base.index,
    )
    if (frame["byd_weight"] < 0.0).any() or (frame["etf_weight"] < 0.0).any():
        raise AssertionError("negative risky-asset weight")
    if not np.allclose(frame.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("portfolio weights do not sum to one")
    return frame


def build_candidate_decisions(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Build the baseline, diagnostic comparator and three frozen challengers."""
    state = build_expansion_state(common, signals)
    base = state["base_byd_weight"].astype(float)
    active = state["trend_expansion_active"].astype(bool)
    age = _episode_age(active)

    zero = pd.Series(0.0, index=common.index, dtype=float)
    original_increment = pd.Series(
        np.where(active, MAX_INCREMENT, 0.0), index=common.index, dtype=float
    )
    episode_increment = pd.Series(
        np.where(active & age.le(EPISODE_SESSION_BUDGET), MAX_INCREMENT, 0.0),
        index=common.index,
        dtype=float,
    )

    annualized_volatility = (
        common["byd_open_return"]
        .rolling(20, min_periods=20)
        .std(ddof=0)
        .mul(np.sqrt(FINANCING_DAY_COUNT))
    )
    volatility_scale = (
        (ANNUALIZED_VOLATILITY_BUDGET / annualized_volatility.replace(0.0, np.nan))
        .clip(lower=0.0, upper=1.0)
        .fillna(0.0)
    )
    volatility_increment = (active.astype(float) * MAX_INCREMENT * volatility_scale).astype(float)

    byd_momentum = (
        (1.0 + common["byd_open_return"])
        .rolling(RELATIVE_STRENGTH_LOOKBACK, min_periods=RELATIVE_STRENGTH_LOOKBACK)
        .apply(np.prod, raw=True)
        .sub(1.0)
    )
    etf_momentum = (
        (1.0 + common["etf_open_return"])
        .rolling(RELATIVE_STRENGTH_LOOKBACK, min_periods=RELATIVE_STRENGTH_LOOKBACK)
        .apply(np.prod, raw=True)
        .sub(1.0)
    )
    relative_strength_ok = active & byd_momentum.gt(0.0) & byd_momentum.gt(etf_momentum)
    relative_strength_increment = pd.Series(
        np.where(relative_strength_ok, MAX_INCREMENT, 0.0),
        index=common.index,
        dtype=float,
    )

    decisions = {
        BASELINE: _weights(base, zero),
        ORIGINAL: _weights(base, original_increment),
        EPISODE_BUDGET: _weights(base, episode_increment),
        VOLATILITY_BUDGET: _weights(base, volatility_increment),
        RELATIVE_STRENGTH: _weights(base, relative_strength_increment),
    }
    diagnostics = state.copy()
    diagnostics["episode_age"] = age
    diagnostics["annualized_volatility_20"] = annualized_volatility
    diagnostics["byd_momentum_60"] = byd_momentum
    diagnostics["etf_momentum_60"] = etf_momentum
    diagnostics["relative_strength_ok"] = relative_strength_ok
    for name, decision in decisions.items():
        diagnostics[f"{name}_increment"] = (-decision["cash_weight"]).clip(lower=0.0)
    return decisions, diagnostics


def run_candidates(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> tuple[dict[str, AllocationResult], pd.DataFrame]:
    decisions, diagnostics = build_candidate_decisions(common, signals)
    results = {
        name: run_financed_allocation(
            name,
            common,
            decision,
            cost_bps=cost_bps,
            annual_financing_rate=annual_financing_rate,
        )
        for name, decision in decisions.items()
    }
    return results, diagnostics


def _window_metrics(result: AllocationResult, start: str, end: str) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty window {start} to {end}")
    output = metrics(block)
    returns = block["net_return"].dropna()
    output.update(
        {
            "transaction_cost_paid": float(block.loc[returns.index, "cost"].sum()),
            "financing_cost_paid": float(block.loc[returns.index, "financing_cost"].sum()),
            "mean_borrowed_weight": float(block.loc[returns.index, "borrowed_weight"].mean()),
            "financed_sessions": float(block.loc[returns.index, "borrowed_weight"].gt(0.0).sum()),
        }
    )
    return output


def build_evaluation(
    primary_results: dict[str, AllocationResult],
    stress_results: dict[str, AllocationResult],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scenario, cost_bps, financing_rate, results in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE, primary_results),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, stress_results),
    ):
        for name, result in results.items():
            for window, (start, end) in WINDOWS.items():
                rows.append(
                    {
                        "scenario": scenario,
                        "model": name,
                        "cost_bps": cost_bps,
                        "annual_financing_rate": financing_rate,
                        "window": window,
                        **_window_metrics(result, start, end),
                    }
                )
    return pd.DataFrame(rows)


def _terminal_wealth(result: AllocationResult, start: str, end: str) -> float:
    returns = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"].dropna()
    if returns.empty:
        raise ValueError(f"empty return window {start} to {end}")
    return float((1.0 + returns).prod())


def period_attribution(results: dict[str, AllocationResult]) -> pd.DataFrame:
    periods = {name: bounds for name, bounds in WINDOWS.items() if name != "full_overlap"}
    rows: list[dict[str, Any]] = []
    for candidate in (ORIGINAL, *CHALLENGERS):
        relative: dict[str, float] = {}
        for period, (start, end) in periods.items():
            relative[period] = (
                _terminal_wealth(results[candidate], start, end)
                / _terminal_wealth(results[BASELINE], start, end)
                - 1.0
            )
        positive_total = sum(max(value, 0.0) for value in relative.values())
        for period, value in relative.items():
            rows.append(
                {
                    "model": candidate,
                    "period": period,
                    "relative_terminal_wealth": value,
                    "positive_contribution_share": (
                        max(value, 0.0) / positive_total if positive_total > 0.0 else 0.0
                    ),
                }
            )
    return pd.DataFrame(rows)


def episode_attribution(results: dict[str, AllocationResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate in (ORIGINAL, *CHALLENGERS):
        result = results[candidate]
        baseline = results[BASELINE].daily.reindex(result.daily.index)
        active = result.daily["borrowed_weight"].gt(0.0)
        starts = active & ~active.shift(1, fill_value=False)
        episode_id = starts.cumsum().where(active)
        candidate_rows: list[dict[str, Any]] = []
        for raw_id, block in result.daily.groupby(episode_id):
            if pd.isna(raw_id):
                continue
            base_block = baseline.loc[block.index]
            candidate_wealth = float((1.0 + block["net_return"]).prod())
            baseline_wealth = float((1.0 + base_block["net_return"]).prod())
            candidate_rows.append(
                {
                    "model": candidate,
                    "episode_id": int(raw_id),
                    "start": block.index.min(),
                    "end": block.index.max(),
                    "sessions": int(len(block)),
                    "relative_terminal_wealth": candidate_wealth / baseline_wealth - 1.0,
                    "financing_cost_paid": float(block["financing_cost"].sum()),
                    "mean_increment": float(block["borrowed_weight"].mean()),
                }
            )
        positive_total = sum(max(row["relative_terminal_wealth"], 0.0) for row in candidate_rows)
        for row in candidate_rows:
            row["positive_contribution_share"] = (
                max(row["relative_terminal_wealth"], 0.0) / positive_total
                if positive_total > 0.0
                else 0.0
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _full_row(evaluation: pd.DataFrame, model: str, scenario: str) -> pd.Series:
    selected = evaluation.loc[
        (evaluation["model"] == model)
        & (evaluation["scenario"] == scenario)
        & (evaluation["window"] == "full_overlap")
    ]
    if len(selected) != 1:
        raise ValueError(f"missing full-overlap row for {model}/{scenario}")
    return selected.iloc[0]


def decide(
    evaluation: pd.DataFrame,
    periods: pd.DataFrame,
    episodes: pd.DataFrame,
) -> ChallengeDecision:
    baseline_primary = _full_row(evaluation, BASELINE, "primary")
    baseline_stress = _full_row(evaluation, BASELINE, "stress")
    all_gates: dict[str, dict[str, bool]] = {}
    diagnostics: dict[str, dict[str, float]] = {}
    eligible: list[str] = []

    for candidate in CHALLENGERS:
        primary = _full_row(evaluation, candidate, "primary")
        stress = _full_row(evaluation, candidate, "stress")
        candidate_periods = periods.loc[periods["model"] == candidate]
        candidate_episodes = episodes.loc[episodes["model"] == candidate]
        later = candidate_periods.set_index("period")["relative_terminal_wealth"]
        max_period_share = float(candidate_periods["positive_contribution_share"].max())
        max_episode_share = (
            float(candidate_episodes["positive_contribution_share"].max())
            if not candidate_episodes.empty
            else 1.0
        )
        completed_episodes = int(len(candidate_episodes))
        financed_sessions = int(primary["financed_sessions"])
        cagr_delta = float(primary["cagr"] - baseline_primary["cagr"])
        mdd_delta = float(primary["max_drawdown"] - baseline_primary["max_drawdown"])
        stress_relative = float(
            (1.0 + stress["total_return"]) / (1.0 + baseline_stress["total_return"]) - 1.0
        )

        gates = {
            "cagr_improvement_gte_0_50pp": cagr_delta >= 0.005,
            "mdd_worsening_lte_2pp": mdd_delta >= -0.02,
            "stress_total_return_not_below_baseline": stress_relative >= 0.0,
            "fixed_validation_relative_positive": float(later.get("fixed_validation", np.nan))
            > 0.0,
            "retrospective_2025_plus_relative_positive": float(
                later.get("retrospective_2025_plus", np.nan)
            )
            > 0.0,
            "period_concentration_lte_60pct": max_period_share <= 0.60,
            "episode_concentration_lte_40pct": max_episode_share <= 0.40,
            "minimum_10_episodes": completed_episodes >= 10,
            "minimum_126_financed_sessions": financed_sessions >= 126,
            "round_trips_per_year_lte_3": float(primary["round_trips_per_year"]) <= 3.0,
        }
        all_gates[candidate] = gates
        diagnostics[candidate] = {
            "cagr_delta": cagr_delta,
            "mdd_delta": mdd_delta,
            "stress_relative_terminal_wealth": stress_relative,
            "max_period_positive_share": max_period_share,
            "max_episode_positive_share": max_episode_share,
            "completed_episodes": float(completed_episodes),
            "financed_sessions": float(financed_sessions),
            "mean_borrowed_weight": float(primary["mean_borrowed_weight"]),
            "round_trips_per_year": float(primary["round_trips_per_year"]),
        }
        if all(gates.values()):
            eligible.append(candidate)

    selected: str | None = None
    if eligible:
        selected = sorted(
            eligible,
            key=lambda candidate: (
                diagnostics[candidate]["max_episode_positive_share"],
                -diagnostics[candidate]["stress_relative_terminal_wealth"],
                diagnostics[candidate]["mean_borrowed_weight"],
                candidate,
            ),
        )[0]

    return ChallengeDecision(
        decision=(
            "select_one_prospective_challenger" if selected is not None else "retain_byd_v1_1"
        ),
        selected_candidate=selected,
        eligible_candidates=tuple(sorted(eligible)),
        gates=all_gates,
        diagnostics=diagnostics,
        promotion_authorized=False,
    )
