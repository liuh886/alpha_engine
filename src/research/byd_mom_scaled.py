"""Minimal-change momentum-strength scaled expansion.

The closest experiment to beating v1.1 was v1.2 trend expansion (CAGR +0.59pp).
This module applies ONLY the minimum changes needed:
1. Remove vol_state filter (increases sessions from 86 to target 126+)
2. Scale leverage by momentum strength (spreads benefit across periods)
3. Add mild drawdown exit guard

No other mechanism changes. No tiered system. Just: expand when V1.0 says
risk-on + bull market + mom_20>0, scale leverage 1.0-1.10 by mom_20 strength,
exit when momentum turns negative or DD emergency triggers.
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
    prepare_common_dataset,
)
from src.research.byd_515180_execution import execute_next_common_open

BASELINE = "byd_v1_1"
PRIMARY = "mom_scaled_110"
ROBUSTNESS = "mom_scaled_105"
CANDIDATES = (BASELINE, PRIMARY, ROBUSTNESS)

PRIMARY_FINANCING_RATE = 0.06
STRESS_FINANCING_RATE = 0.10
FINANCING_DAY_COUNT = 252.0

RULES = {
    "entry_base_byd_weight": 1.0,
    "entry_market_state": "bull",
    "entry_min_mom_20": 0.015,
    "entry_min_mom_60": 0.005,
    "entry_min_drawdown": -0.14,
    "exit_max_mom_20": -0.015,
    "exit_emergency_drawdown": -0.25,
    "max_leverage": 1.05,
    "robustness_leverage": 1.025,
    "mom_scale_factor": 5.0,
    "dd_adjustment_power": 0.0,
}


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def _stateful(entry, exit_):
    active = False
    vals = []
    for en, ex in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active and bool(ex):
            active = False
        elif not active and bool(en):
            active = True
        vals.append(active)
    return pd.Series(vals, index=entry.index, name="expansion_active")


def build_state(common, signals):
    base = signals["base_byd_weight"].astype(float)
    mom20 = common["mom_20"]
    mom60 = common["mom_60"]
    dd = common["drawdown_252"]
    entry = (
        base.eq(RULES["entry_base_byd_weight"])
        & common["market_state"].eq(RULES["entry_market_state"])
        & mom20.gt(RULES["entry_min_mom_20"])
        & mom60.gt(RULES["entry_min_mom_60"])
        & dd.gt(RULES["entry_min_drawdown"])
    )
    exit_ = (
        base.eq(0.75)
        | mom20.le(RULES["exit_max_mom_20"])
        | dd.le(RULES["exit_emergency_drawdown"])
    )
    active = _stateful(entry, exit_)
    mom_strength = (
        (mom20 - RULES["entry_min_mom_20"]).clip(0, 0.15)
        * RULES["mom_scale_factor"]
    )
    mom_strength = mom_strength.clip(0, RULES["max_leverage"] - 1.0)
    return pd.DataFrame(
        {
            "entry": entry,
            "exit": exit_,
            "expansion_active": active,
            "mom_strength": mom_strength,
            "mom_20": mom20,
            "drawdown_252": dd,
        },
        index=common.index,
    )


def build_decisions(common, signals):
    state = build_state(common, signals)
    base = signals["base_byd_weight"].astype(float)
    active = state["expansion_active"]
    strength = state["mom_strength"]

    baseline_byd = base.copy()
    primary_byd = base.where(
        ~active, (base + strength).clip(upper=RULES["max_leverage"])
    )
    robust_byd = base.where(
        ~active,
        (base + strength * 0.5).clip(upper=RULES["robustness_leverage"]),
    )

    decisions = {}
    for label, byd_weight in [
        (BASELINE, baseline_byd),
        (PRIMARY, primary_byd),
        (ROBUSTNESS, robust_byd),
    ]:
        etf_weight = (1.0 - byd_weight).clip(0, None)
        cash_weight = 1.0 - byd_weight - etf_weight
        decisions[label] = pd.DataFrame(
            {
                "byd_weight": byd_weight,
                "etf_weight": etf_weight,
                "cash_weight": cash_weight,
            },
            index=common.index,
        )
    for name, decision in decisions.items():
        assert np.allclose(
            decision.sum(axis=1), 1.0
        ), f"{name} weights don't sum to 1"
    return decisions, state


def run_financed(name, common, decision, cost_bps, rate):
    executed = execute_next_common_open(decision, common["common_open_eligible"])
    byd_weight = executed["position_byd_weight"]
    etf_weight = executed["position_etf_weight"]
    cash_weight = executed["position_cash_weight"]
    gross = (
        byd_weight * common["byd_open_return"]
        + etf_weight * common["etf_open_return"]
    )
    turnover = executed.diff().abs().sum(axis=1)
    turnover.iloc[0] = 0.0
    tcost = turnover * cost_bps / 10000.0
    borrowed = (-cash_weight).clip(0)
    fcost = borrowed * rate / FINANCING_DAY_COUNT
    daily = pd.concat([decision.add_prefix("d_"), executed], axis=1)
    daily["gross_return"] = gross
    daily["turnover_units"] = turnover
    daily["cost"] = tcost
    daily["financing_cost"] = fcost
    daily["borrowed_weight"] = borrowed
    daily["net_return"] = gross - tcost - fcost
    daily = daily.iloc[:-1].copy()
    return AllocationResult(name=name, daily=daily, trades=pd.DataFrame())


def run_candidates(common, signals, *, cost_bps, annual_financing_rate):
    decisions, state = build_decisions(common, signals)
    results = {
        name: run_financed(
            name, common, decision, cost_bps, annual_financing_rate
        )
        for name, decision in decisions.items()
    }
    return results, state


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    out = metrics(block)
    returns = block["net_return"].dropna()
    out["financed_sessions"] = float(
        block.loc[returns.index, "borrowed_weight"].gt(0).sum()
    )
    return out


def build_evaluation(r20, r40):
    rows = []
    scenarios = [
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE, r20),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, r40),
    ]
    for label, cost_bps, _rate, results in scenarios:
        for name, result in results.items():
            for window, (start, end) in WINDOWS.items():
                rows.append(
                    {
                        "scenario": label,
                        "model": name,
                        "cost_bps": cost_bps,
                        "window": window,
                        **_wm(result, start, end),
                    }
                )
    return pd.DataFrame(rows)


def _tw(daily, start, end):
    returns = daily.loc[
        pd.Timestamp(start) : pd.Timestamp(end), "net_return"
    ].dropna()
    return float((1.0 + returns).prod())


def period_contribution(results):
    rows = []
    periods = {key: value for key, value in WINDOWS.items() if key != "full_overlap"}
    for name in (PRIMARY, ROBUSTNESS):
        relative = {}
        for period, (start, end) in periods.items():
            relative[period] = (
                _tw(results[name].daily, start, end)
                / _tw(results[BASELINE].daily, start, end)
                - 1.0
            )
        positive_total = sum(max(value, 0.0) for value in relative.values())
        for period, value in relative.items():
            rows.append(
                {
                    "model": name,
                    "period": period,
                    "relative_terminal_wealth": value,
                    "positive_contribution_share": (
                        max(value, 0.0) / positive_total
                        if positive_total > 0
                        else 0.0
                    ),
                }
            )
    return pd.DataFrame(rows)


def governed_result(evaluation, contributions):
    def row(model, scenario):
        selected = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["scenario"] == scenario)
            & (evaluation["window"] == "full_overlap")
        ]
        return selected.iloc[0]

    baseline_primary = row(BASELINE, "primary")
    primary = row(PRIMARY, "primary")
    robustness = row(ROBUSTNESS, "primary")
    baseline_stress = row(BASELINE, "stress")
    primary_stress = row(PRIMARY, "stress")
    robustness_stress = row(ROBUSTNESS, "stress")
    cagr_delta = float(primary["cagr"] - baseline_primary["cagr"])
    mdd_delta = float(
        primary["max_drawdown"] - baseline_primary["max_drawdown"]
    )
    primary_contributions = contributions[contributions["model"] == PRIMARY]
    negative_periods = int(
        primary_contributions["relative_terminal_wealth"].lt(0).sum()
    )
    max_share = float(primary_contributions["positive_contribution_share"].max())
    financed_sessions = int(primary["financed_sessions"])

    gates = {
        "cagr_improves_0_5pp": cagr_delta >= 0.005,
        "mdd_worsening_le_2pp": mdd_delta >= -0.02,
        "calmar_not_below": float(primary["calmar"])
        >= float(baseline_primary["calmar"]),
        "stress_above_baseline": float(primary_stress["total_return"])
        > float(baseline_stress["total_return"]),
        "neg_periods_le_1": negative_periods <= 1,
        "concentration_le_60pct": max_share <= 0.60,
        "rt_le_4": float(primary["round_trips_per_year"]) <= 4.0,
        "min_100_sessions": financed_sessions >= 100,
        "robustness_confirm": (
            float(robustness["cagr"]) > float(baseline_primary["cagr"])
            and float(robustness_stress["total_return"])
            > float(baseline_stress["total_return"])
        ),
    }
    return GovernedResult(
        decision="promote" if all(gates.values()) else "retain",
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_delta,
            "mdd_delta": mdd_delta,
            "sessions": financed_sessions,
            "neg": negative_periods,
            "max_share": max_share,
        },
    )
