"""Governed BYD v1.2 asymmetric extreme-defense research.

The accepted BYD v1.1 defensive sleeve remains the baseline. This module tests
one new mechanism only: a rare, stateful reduction of BYD exposure during deep
bear/high-volatility deterioration. It never changes the 515180 asset choice,
reopens recovery overlays, or treats observed history as a fresh holdout.
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
    evaluation_table,
)
from src.research.byd_515180_execution import run_allocation

BASELINE = "byd_v1_1"
PRIMARY = "byd_v1_2_extreme_defense_50"
ROBUSTNESS = "byd_v1_2_extreme_defense_625"
CASH_DIAGNOSTIC = "byd_v1_2_extreme_defense_cash"
CANDIDATES = (BASELINE, PRIMARY, ROBUSTNESS, CASH_DIAGNOSTIC)

RULES = {
    "entry_base_byd_weight": 0.75,
    "entry_market_state": "bear",
    "entry_vol_state": "high",
    "entry_drawdown_252_ceiling": -0.20,
    "entry_mom_20_ceiling": 0.0,
    "entry_mom_60_ceiling": 0.0,
    "exit_base_byd_weight": 1.0,
    "exit_mom_20_floor": 0.0,
    "exit_vol_state": "low",
    "primary_byd_weight": 0.50,
    "robustness_byd_weight": 0.625,
    "cash_diagnostic_etf_weight": 0.25,
}


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def _stateful_extreme(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    if not entry.index.equals(exit_.index):
        raise ValueError("entry and exit indices must match")
    active = False
    values: list[bool] = []
    for enter_now, exit_now in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        values.append(active)
    return pd.Series(values, index=entry.index, name="extreme_defense_active")


def build_extreme_state(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    required_common = {
        "market_state",
        "vol_state",
        "drawdown_252",
        "mom_20",
        "mom_60",
    }
    missing = sorted(required_common - set(common.columns))
    if missing:
        raise ValueError(f"common dataset missing extreme-defense fields: {missing}")
    if "base_byd_weight" not in signals:
        raise ValueError("signals missing base_byd_weight")
    if not common.index.equals(signals.index):
        raise ValueError("common and signal indices must match")

    base = signals["base_byd_weight"].astype(float)
    entry = (
        base.eq(RULES["entry_base_byd_weight"])
        & common["market_state"].eq(RULES["entry_market_state"])
        & common["vol_state"].eq(RULES["entry_vol_state"])
        & common["drawdown_252"].le(RULES["entry_drawdown_252_ceiling"])
        & common["mom_20"].lt(RULES["entry_mom_20_ceiling"])
        & common["mom_60"].lt(RULES["entry_mom_60_ceiling"])
    )
    exit_ = (
        base.eq(RULES["exit_base_byd_weight"])
        | common["mom_20"].gt(RULES["exit_mom_20_floor"])
        | common["vol_state"].eq(RULES["exit_vol_state"])
    )
    active = _stateful_extreme(entry, exit_)
    return pd.DataFrame(
        {
            "base_byd_weight": base,
            "entry": entry.astype(bool),
            "exit": exit_.astype(bool),
            "extreme_defense_active": active.astype(bool),
            "market_state": common["market_state"].astype(str),
            "vol_state": common["vol_state"].astype(str),
            "drawdown_252": common["drawdown_252"].astype(float),
            "mom_20": common["mom_20"].astype(float),
            "mom_60": common["mom_60"].astype(float),
        },
        index=common.index,
    )


def _decision(
    base: pd.Series,
    active: pd.Series,
    *,
    extreme_byd_weight: float,
    extreme_etf_weight: float | None = None,
) -> pd.DataFrame:
    byd = base.where(~active, extreme_byd_weight).astype(float)
    if extreme_etf_weight is None:
        etf = (1.0 - base).where(~active, 1.0 - extreme_byd_weight).astype(float)
    else:
        etf = (1.0 - base).where(~active, extreme_etf_weight).astype(float)
    cash = 1.0 - byd - etf
    frame = pd.DataFrame(
        {"byd_weight": byd, "etf_weight": etf, "cash_weight": cash},
        index=base.index,
    )
    if (frame < -1e-12).any().any():
        raise AssertionError("extreme-defense decision produced negative weight")
    if not np.allclose(frame.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("extreme-defense weights do not sum to one")
    return frame


def build_decisions(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    state = build_extreme_state(common, signals)
    base = state["base_byd_weight"].astype(float)
    active = state["extreme_defense_active"].astype(bool)
    baseline = _decision(base, pd.Series(False, index=base.index), extreme_byd_weight=0.75)
    decisions = {
        BASELINE: baseline,
        PRIMARY: _decision(
            base,
            active,
            extreme_byd_weight=RULES["primary_byd_weight"],
        ),
        ROBUSTNESS: _decision(
            base,
            active,
            extreme_byd_weight=RULES["robustness_byd_weight"],
        ),
        CASH_DIAGNOSTIC: _decision(
            base,
            active,
            extreme_byd_weight=RULES["primary_byd_weight"],
            extreme_etf_weight=RULES["cash_diagnostic_etf_weight"],
        ),
    }
    return decisions, state


def run_candidates(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
) -> tuple[dict[str, AllocationResult], pd.DataFrame]:
    decisions, state = build_decisions(common, signals)
    results = {
        name: run_allocation(name, common, decision, cost_bps=cost_bps)
        for name, decision in decisions.items()
    }
    return results, state


def _terminal_wealth(daily: pd.DataFrame, start: str, end: str) -> float:
    returns = daily.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"].dropna()
    if returns.empty:
        raise ValueError(f"empty return block: {start} to {end}")
    return float((1.0 + returns).prod())


def period_contribution(
    results: dict[str, AllocationResult],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    periods = {key: value for key, value in WINDOWS.items() if key != "full_overlap"}
    for name in (PRIMARY, ROBUSTNESS, CASH_DIAGNOSTIC):
        relatives: dict[str, float] = {}
        for period, (start, end) in periods.items():
            candidate_wealth = _terminal_wealth(results[name].daily, start, end)
            baseline_wealth = _terminal_wealth(results[BASELINE].daily, start, end)
            relative = candidate_wealth / baseline_wealth - 1.0
            relatives[period] = relative
        positive_total = sum(max(value, 0.0) for value in relatives.values())
        for period, relative in relatives.items():
            share = max(relative, 0.0) / positive_total if positive_total > 0.0 else 0.0
            rows.append(
                {
                    "model": name,
                    "period": period,
                    "relative_terminal_wealth": relative,
                    "positive_contribution_share": share,
                }
            )
    return pd.DataFrame(rows)


def episode_attribution(
    primary: AllocationResult,
    baseline: AllocationResult,
    state: pd.DataFrame,
) -> pd.DataFrame:
    daily = primary.daily.copy()
    benchmark = baseline.daily.reindex(daily.index)
    active = daily["position_byd_weight"].lt(benchmark["position_byd_weight"] - 1e-12)
    starts = active & ~active.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in daily.groupby(episode_id):
        if pd.isna(raw_id):
            continue
        base_block = benchmark.loc[block.index]
        candidate_wealth = float((1.0 + block["net_return"]).prod())
        baseline_wealth = float((1.0 + base_block["net_return"]).prod())
        state_block = state.reindex(block.index)
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
                "candidate_return": candidate_wealth - 1.0,
                "baseline_return": baseline_wealth - 1.0,
                "relative_terminal_wealth": candidate_wealth / baseline_wealth - 1.0,
                "minimum_drawdown_252": float(state_block["drawdown_252"].min()),
                "mean_mom_20": float(state_block["mom_20"].mean()),
                "mean_mom_60": float(state_block["mom_60"].mean()),
            }
        )
    return pd.DataFrame(rows)


def governed_result(
    evaluation: pd.DataFrame,
    contributions: pd.DataFrame,
) -> GovernedResult:
    def row(model: str, cost: float) -> pd.Series:
        selected = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["cost_bps"] == cost)
            & (evaluation["window"] == "full_overlap")
        ]
        if len(selected) != 1:
            raise ValueError(f"missing full-overlap row for {model}/{cost}")
        return selected.iloc[0]

    baseline20 = row(BASELINE, PRIMARY_COST_BPS)
    primary20 = row(PRIMARY, PRIMARY_COST_BPS)
    robust20 = row(ROBUSTNESS, PRIMARY_COST_BPS)
    baseline40 = row(BASELINE, STRESS_COST_BPS)
    primary40 = row(PRIMARY, STRESS_COST_BPS)

    cagr_delta = float(primary20["cagr"] - baseline20["cagr"])
    calmar_delta = float(primary20["calmar"] - baseline20["calmar"])
    drawdown_improvement = float(primary20["max_drawdown"] - baseline20["max_drawdown"])
    primary_contrib = contributions.loc[contributions["model"] == PRIMARY]
    negative_periods = int((primary_contrib["relative_terminal_wealth"] < 0.0).sum())
    max_positive_share = float(primary_contrib["positive_contribution_share"].max())

    gates = {
        "cagr_or_calmar_improvement": bool(
            cagr_delta >= 0.005 or (calmar_delta >= 0.05 and cagr_delta >= -0.0025)
        ),
        "max_drawdown_improves_3pp": bool(drawdown_improvement >= 0.03),
        "stress_40bps_not_below_baseline": bool(
            float(primary40["total_return"]) >= float(baseline40["total_return"])
        ),
        "no_more_than_one_negative_period": negative_periods <= 1,
        "positive_contribution_not_concentrated": bool(
            max_positive_share <= 0.60 and primary_contrib["relative_terminal_wealth"].gt(0.0).any()
        ),
        "round_trips_per_year_le_2": bool(float(primary20["round_trips_per_year"]) <= 2.0),
        "robustness_same_direction": bool(
            float(robust20["max_drawdown"]) > float(baseline20["max_drawdown"])
            and float(robust20["calmar"]) > float(baseline20["calmar"])
        ),
    }
    decision = "promote_byd_v1_2_candidate" if all(gates.values()) else "retain_byd_v1_1"
    diagnostics = {
        "cagr_delta": cagr_delta,
        "calmar_delta": calmar_delta,
        "max_drawdown_improvement": drawdown_improvement,
        "negative_periods": negative_periods,
        "max_positive_contribution_share": max_positive_share,
        "primary_20bps_total_return": float(primary20["total_return"]),
        "baseline_20bps_total_return": float(baseline20["total_return"]),
        "primary_40bps_total_return": float(primary40["total_return"]),
        "baseline_40bps_total_return": float(baseline40["total_return"]),
    }
    return GovernedResult(decision=decision, gates=gates, diagnostics=diagnostics)


def build_evaluation(
    results_20: dict[str, AllocationResult],
    results_40: dict[str, AllocationResult],
) -> pd.DataFrame:
    return pd.concat(
        [
            evaluation_table(results_20, PRIMARY_COST_BPS),
            evaluation_table(results_40, STRESS_COST_BPS),
        ],
        ignore_index=True,
    )
