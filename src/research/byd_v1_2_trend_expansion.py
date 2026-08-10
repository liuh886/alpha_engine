"""Governed BYD v1.2 capped trend-expansion research.

BYD v1.1 remains the accepted formal baseline. This module tests one distinct
mechanism: a small financed BYD allocation above 100% during a strong-trend,
low-volatility state. Financing cost is charged daily on negative cash and the
observed history is never treated as a fresh holdout.
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
from src.research.byd_515180_execution import execute_next_common_open

BASELINE = "byd_v1_1"
PRIMARY = "byd_v1_2_trend_expansion_1125"
ROBUSTNESS = "byd_v1_2_trend_expansion_1100"
DIAGNOSTIC = "byd_v1_2_trend_expansion_1250"
CANDIDATES = (BASELINE, PRIMARY, ROBUSTNESS, DIAGNOSTIC)

PRIMARY_FINANCING_RATE = 0.06
STRESS_FINANCING_RATE = 0.10
FINANCING_DAY_COUNT = 252.0

RULES = {
    "entry_base_byd_weight": 1.0,
    "entry_market_state": "bull",
    "entry_vol_state": "low",
    "entry_mom_20_floor": 0.0,
    "entry_mom_60_floor": 0.0,
    "entry_drawdown_252_floor": -0.10,
    "exit_base_byd_weight": 0.75,
    "exit_market_state_not": "bull",
    "exit_vol_state": "high",
    "exit_mom_20_ceiling": 0.0,
    "primary_byd_weight": 1.125,
    "robustness_byd_weight": 1.10,
    "diagnostic_byd_weight": 1.25,
}


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def _stateful_expansion(entry: pd.Series, exit_: pd.Series) -> pd.Series:
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
    return pd.Series(values, index=entry.index, name="trend_expansion_active")


def build_expansion_state(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "market_state",
        "vol_state",
        "drawdown_252",
        "mom_20",
        "mom_60",
    }
    missing = sorted(required - set(common.columns))
    if missing:
        raise ValueError(f"common dataset missing trend-expansion fields: {missing}")
    if "base_byd_weight" not in signals:
        raise ValueError("signals missing base_byd_weight")
    if not common.index.equals(signals.index):
        raise ValueError("common and signal indices must match")

    base = signals["base_byd_weight"].astype(float)
    entry = (
        base.eq(RULES["entry_base_byd_weight"])
        & common["market_state"].eq(RULES["entry_market_state"])
        & common["vol_state"].eq(RULES["entry_vol_state"])
        & common["mom_20"].gt(RULES["entry_mom_20_floor"])
        & common["mom_60"].gt(RULES["entry_mom_60_floor"])
        & common["drawdown_252"].gt(RULES["entry_drawdown_252_floor"])
    )
    exit_ = (
        base.eq(RULES["exit_base_byd_weight"])
        | common["market_state"].ne(RULES["exit_market_state_not"])
        | common["vol_state"].eq(RULES["exit_vol_state"])
        | common["mom_20"].le(RULES["exit_mom_20_ceiling"])
    )
    active = _stateful_expansion(entry, exit_)
    return pd.DataFrame(
        {
            "base_byd_weight": base,
            "entry": entry.astype(bool),
            "exit": exit_.astype(bool),
            "trend_expansion_active": active.astype(bool),
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
    expansion_byd_weight: float | None,
) -> pd.DataFrame:
    baseline_etf = 1.0 - base
    if expansion_byd_weight is None:
        byd = base.astype(float)
        etf = baseline_etf.astype(float)
        cash = pd.Series(0.0, index=base.index, dtype=float)
    else:
        byd = base.where(~active, expansion_byd_weight).astype(float)
        etf = baseline_etf.where(~active, 0.0).astype(float)
        cash = 1.0 - byd - etf
    frame = pd.DataFrame(
        {"byd_weight": byd, "etf_weight": etf, "cash_weight": cash},
        index=base.index,
    )
    if (frame["byd_weight"] < 0.0).any() or (frame["etf_weight"] < 0.0).any():
        raise AssertionError("trend expansion produced negative risky-asset weight")
    if not np.allclose(frame.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("trend-expansion weights do not sum to one")
    return frame


def build_decisions(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    state = build_expansion_state(common, signals)
    base = state["base_byd_weight"].astype(float)
    active = state["trend_expansion_active"].astype(bool)
    decisions = {
        BASELINE: _decision(base, active, expansion_byd_weight=None),
        PRIMARY: _decision(
            base,
            active,
            expansion_byd_weight=RULES["primary_byd_weight"],
        ),
        ROBUSTNESS: _decision(
            base,
            active,
            expansion_byd_weight=RULES["robustness_byd_weight"],
        ),
        DIAGNOSTIC: _decision(
            base,
            active,
            expansion_byd_weight=RULES["diagnostic_byd_weight"],
        ),
    }
    return decisions, state


def run_financed_allocation(
    name: str,
    common: pd.DataFrame,
    decision: pd.DataFrame,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> AllocationResult:
    if annual_financing_rate < 0.0:
        raise ValueError("annual financing rate cannot be negative")
    executed = execute_next_common_open(
        decision,
        common["common_open_eligible"],
    )
    byd_weight = executed["position_byd_weight"]
    etf_weight = executed["position_etf_weight"]
    cash_weight = executed["position_cash_weight"]
    gross_return = byd_weight * common["byd_open_return"] + etf_weight * common["etf_open_return"]
    turnover = executed.diff().abs().sum(axis=1)
    turnover.iloc[0] = 0.0
    transaction_cost = turnover * cost_bps / 10_000.0
    borrowed_weight = (-cash_weight).clip(lower=0.0)
    financing_cost = borrowed_weight * annual_financing_rate / FINANCING_DAY_COUNT

    daily = pd.concat([decision.add_prefix("decision_"), executed], axis=1)
    daily["common_open_eligible"] = common["common_open_eligible"]
    daily["byd_return"] = common["byd_open_return"]
    daily["etf_return"] = common["etf_open_return"]
    daily["gross_return"] = gross_return
    daily["turnover_units"] = turnover
    daily["cost"] = transaction_cost
    daily["financing_cost"] = financing_cost
    daily["borrowed_weight"] = borrowed_weight
    daily["gross_exposure"] = byd_weight.abs() + etf_weight.abs()
    daily["net_return"] = gross_return - transaction_cost - financing_cost
    daily = daily.iloc[:-1].copy()

    changes = executed.ne(executed.shift(1)).any(axis=1)
    trades = daily.loc[
        changes.reindex(daily.index).fillna(False),
        [
            "position_byd_weight",
            "position_etf_weight",
            "position_cash_weight",
            "turnover_units",
            "cost",
            "financing_cost",
            "borrowed_weight",
            "common_open_eligible",
        ],
    ].copy()
    trades.index.name = "date"
    return AllocationResult(name=name, daily=daily, trades=trades.reset_index())


def run_candidates(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> tuple[dict[str, AllocationResult], pd.DataFrame]:
    decisions, state = build_decisions(common, signals)
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
    return results, state


def _window_metrics(
    result: AllocationResult,
    start: str,
    end: str,
) -> dict[str, float]:
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
            "max_gross_exposure": float(block.loc[returns.index, "gross_exposure"].max()),
            "financed_sessions": float(block.loc[returns.index, "borrowed_weight"].gt(0.0).sum()),
        }
    )
    return output


def build_evaluation(
    results_20: dict[str, AllocationResult],
    results_stress: dict[str, AllocationResult],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, cost_bps, financing_rate, results in (
        (
            "primary",
            PRIMARY_COST_BPS,
            PRIMARY_FINANCING_RATE,
            results_20,
        ),
        (
            "stress",
            STRESS_COST_BPS,
            STRESS_FINANCING_RATE,
            results_stress,
        ),
    ):
        for name, result in results.items():
            for window, (start, end) in WINDOWS.items():
                rows.append(
                    {
                        "scenario": label,
                        "model": name,
                        "cost_bps": cost_bps,
                        "annual_financing_rate": financing_rate,
                        "window": window,
                        **_window_metrics(result, start, end),
                    }
                )
    return pd.DataFrame(rows)


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
    for name in (PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        relative_by_period: dict[str, float] = {}
        for period, (start, end) in periods.items():
            candidate_wealth = _terminal_wealth(results[name].daily, start, end)
            baseline_wealth = _terminal_wealth(results[BASELINE].daily, start, end)
            relative_by_period[period] = candidate_wealth / baseline_wealth - 1.0
        positive_total = sum(max(value, 0.0) for value in relative_by_period.values())
        for period, relative in relative_by_period.items():
            share = max(relative, 0.0) / positive_total if positive_total > 0 else 0.0
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
    active = daily["borrowed_weight"].gt(0.0)
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
                "financing_cost_paid": float(block["financing_cost"].sum()),
                "transaction_cost_paid": float(block["cost"].sum()),
                "minimum_drawdown_252": float(state_block["drawdown_252"].min()),
                "mean_mom_20": float(state_block["mom_20"].mean()),
                "mean_mom_60": float(state_block["mom_60"].mean()),
            }
        )
    return pd.DataFrame(rows)


def governed_result(
    evaluation: pd.DataFrame,
    contributions: pd.DataFrame,
    episodes: pd.DataFrame,
) -> GovernedResult:
    def row(model: str, scenario: str) -> pd.Series:
        selected = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["scenario"] == scenario)
            & (evaluation["window"] == "full_overlap")
        ]
        if len(selected) != 1:
            raise ValueError(f"missing full-overlap row for {model}/{scenario}")
        return selected.iloc[0]

    baseline_primary = row(BASELINE, "primary")
    primary = row(PRIMARY, "primary")
    robustness = row(ROBUSTNESS, "primary")
    baseline_stress = row(BASELINE, "stress")
    primary_stress = row(PRIMARY, "stress")
    robustness_stress = row(ROBUSTNESS, "stress")

    cagr_delta = float(primary["cagr"] - baseline_primary["cagr"])
    mdd_delta = float(primary["max_drawdown"] - baseline_primary["max_drawdown"])
    calmar_delta = float(primary["calmar"] - baseline_primary["calmar"])
    primary_contrib = contributions.loc[contributions["model"] == PRIMARY]
    negative_periods = int(primary_contrib["relative_terminal_wealth"].lt(0.0).sum())
    max_positive_share = float(primary_contrib["positive_contribution_share"].max())
    expansion_sessions = int(primary["financed_sessions"])
    completed_episodes = int(len(episodes))

    gates = {
        "cagr_improves_1pp": cagr_delta >= 0.01,
        "max_drawdown_worsening_le_3pp": mdd_delta >= -0.03,
        "calmar_decline_le_0_02": calmar_delta >= -0.02,
        "stress_total_return_above_baseline": bool(
            float(primary_stress["total_return"]) > float(baseline_stress["total_return"])
        ),
        "no_more_than_one_negative_period": negative_periods <= 1,
        "positive_contribution_not_concentrated": bool(
            max_positive_share <= 0.60 and primary_contrib["relative_terminal_wealth"].gt(0.0).any()
        ),
        "round_trips_per_year_le_3": bool(float(primary["round_trips_per_year"]) <= 3.0),
        "minimum_10_episodes": completed_episodes >= 10,
        "minimum_126_financed_sessions": expansion_sessions >= 126,
        "robustness_improves_primary_and_stress_return": bool(
            float(robustness["cagr"]) > float(baseline_primary["cagr"])
            and float(robustness_stress["total_return"]) > float(baseline_stress["total_return"])
            and float(robustness["max_drawdown"]) - float(baseline_primary["max_drawdown"]) >= -0.02
        ),
    }
    decision = (
        "promote_byd_v1_2_trend_expansion_candidate" if all(gates.values()) else "retain_byd_v1_1"
    )
    diagnostics = {
        "cagr_delta": cagr_delta,
        "max_drawdown_delta": mdd_delta,
        "calmar_delta": calmar_delta,
        "negative_periods": negative_periods,
        "max_positive_contribution_share": max_positive_share,
        "completed_expansion_episodes": completed_episodes,
        "financed_sessions": expansion_sessions,
        "primary_total_return": float(primary["total_return"]),
        "baseline_total_return": float(baseline_primary["total_return"]),
        "primary_stress_total_return": float(primary_stress["total_return"]),
        "baseline_stress_total_return": float(baseline_stress["total_return"]),
        "primary_financing_cost_paid": float(primary["financing_cost_paid"]),
    }
    return GovernedResult(decision=decision, gates=gates, diagnostics=diagnostics)
