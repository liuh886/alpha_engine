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
    AllocationResult, PRIMARY_COST_BPS, STRESS_COST_BPS,
    WINDOWS, metrics, prepare_common_dataset,
)
from src.research.byd_515180_execution import execute_next_common_open

BASELINE = "byd_v1_1"
PRIMARY = "mom_scaled_110"
ROBUSTNESS = "mom_scaled_105"
CANDIDATES = (BASELINE, PRIMARY, ROBUSTNESS)

PRIMARY_FINANCING_RATE = 0.06
STRESS_FINANCING_RATE = 0.10
FINANCING_DAY_COUNT = 252.0

# Conservative rules: moderate leverage, moderate thresholds
RULES = {
    "entry_base_byd_weight": 1.0,
    "entry_market_state": "bull",
    "entry_min_mom_20": 0.015,
    "entry_min_mom_60": 0.005,
    "entry_min_drawdown": -0.14,
    "exit_max_mom_20": -0.015,
    "exit_emergency_drawdown": -0.25,
    "max_leverage": 1.05,               # conservative cap
    "robustness_leverage": 1.025,       # half the adjustment
    "mom_scale_factor": 5.0,            # moderate scaling
    "dd_adjustment_power": 0.0,         # disabled
}


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def _stateful(entry, exit_):
    active = False; vals = []
    for en, ex in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active and bool(ex): active = False
        elif not active and bool(en): active = True
        vals.append(active)
    return pd.Series(vals, index=entry.index, name="expansion_active")


def build_state(common, signals):
    base = signals["base_byd_weight"].astype(float)
    mom20 = common["mom_20"]; mom60 = common["mom_60"]; dd = common["drawdown_252"]
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
    mom_strength = (mom20 - RULES["entry_min_mom_20"]).clip(0, 0.15) * RULES["mom_scale_factor"]
    mom_strength = mom_strength.clip(0, RULES["max_leverage"] - 1.0)
    return pd.DataFrame({
        "entry": entry, "exit": exit_, "expansion_active": active,
        "mom_strength": mom_strength, "mom_20": mom20, "drawdown_252": dd,
    }, index=common.index)


def build_decisions(common, signals):
    state = build_state(common, signals)
    base = signals["base_byd_weight"].astype(float)
    active = state["expansion_active"]
    strength = state["mom_strength"]  # already dd-adjusted

    baseline_byd = base.copy()
    # Primary: base + dd-adjusted momentum strength, capped at max_leverage
    primary_byd = base.where(~active, (base + strength).clip(upper=RULES["max_leverage"]))
    # Robustness: half the primary adjustment
    robust_byd = base.where(~active, (base + strength * 0.5).clip(upper=RULES["robustness_leverage"]))

    decisions = {}
    for label, byd_s in [(BASELINE, baseline_byd), (PRIMARY, primary_byd), (ROBUSTNESS, robust_byd)]:
        etf = (1.0 - byd_s).clip(0, None)
        cash = 1.0 - byd_s - etf
        decisions[label] = pd.DataFrame(
            {"byd_weight": byd_s, "etf_weight": etf, "cash_weight": cash}, index=common.index
        )
    for name, d in decisions.items():
        assert np.allclose(d.sum(axis=1), 1.0), f"{name} weights don't sum to 1"
    return decisions, state


def run_financed(name, common, decision, cost_bps, rate):
    execd = execute_next_common_open(decision, common["common_open_eligible"])
    bw, ew, cw = execd["position_byd_weight"], execd["position_etf_weight"], execd["position_cash_weight"]
    gross = bw * common["byd_open_return"] + ew * common["etf_open_return"]
    turnover = execd.diff().abs().sum(axis=1); turnover.iloc[0] = 0.0
    tcost = turnover * cost_bps / 10000.0
    borrowed = (-cw).clip(0)
    fcost = borrowed * rate / FINANCING_DAY_COUNT
    daily = pd.concat([decision.add_prefix("d_"), execd], axis=1)
    daily["gross_return"] = gross; daily["turnover_units"] = turnover
    daily["cost"] = tcost; daily["financing_cost"] = fcost
    daily["borrowed_weight"] = borrowed
    daily["net_return"] = gross - tcost - fcost
    daily = daily.iloc[:-1].copy()
    return AllocationResult(name=name, daily=daily, trades=pd.DataFrame())


def run_candidates(common, signals, *, cost_bps, annual_financing_rate):
    decisions, state = build_decisions(common, signals)
    results = {n: run_financed(n, common, d, cost_bps, annual_financing_rate) for n, d in decisions.items()}
    return results, state


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start): pd.Timestamp(end)]
    out = metrics(block)
    rs = block["net_return"].dropna()
    out["financed_sessions"] = float(block.loc[rs.index, "borrowed_weight"].gt(0).sum())
    return out


def build_evaluation(r20, r40):
    rows = []
    for label, cb, rate, results in [("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE, r20), ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, r40)]:
        for name, result in results.items():
            for w, (s, e) in WINDOWS.items():
                rows.append({"scenario": label, "model": name, "cost_bps": cb, "window": w, **_wm(result, s, e)})
    return pd.DataFrame(rows)


def _tw(daily, s, e):
    rs = daily.loc[pd.Timestamp(s): pd.Timestamp(e), "net_return"].dropna()
    return float((1.0 + rs).prod())


def period_contribution(results):
    rows = []
    periods = {k: v for k, v in WINDOWS.items() if k != "full_overlap"}
    for name in (PRIMARY, ROBUSTNESS):
        rel = {}
        for p, (s, e) in periods.items():
            rel[p] = _tw(results[name].daily, s, e) / _tw(results[BASELINE].daily, s, e) - 1.0
        pt = sum(max(v, 0.0) for v in rel.values())
        for p, r in rel.items():
            rows.append({"model": name, "period": p, "relative_terminal_wealth": r, "positive_contribution_share": max(r, 0.0) / pt if pt > 0 else 0.0})
    return pd.DataFrame(rows)


def governed_result(evaluation, contributions):
    def r(model, sc):
        sel = evaluation.loc[(evaluation["model"]==model) & (evaluation["scenario"]==sc) & (evaluation["window"]=="full_overlap")]
        return sel.iloc[0]
    bp = r(BASELINE, "primary"); pr = r(PRIMARY, "primary"); rb = r(ROBUSTNESS, "primary")
    bs = r(BASELINE, "stress"); ps = r(PRIMARY, "stress"); rs = r(ROBUSTNESS, "stress")
    cagr_d = float(pr["cagr"] - bp["cagr"])
    mdd_d = float(pr["max_drawdown"] - bp["max_drawdown"])
    pc = contributions[contributions["model"]==PRIMARY]
    neg = int(pc["relative_terminal_wealth"].lt(0).sum())
    ms = float(pc["positive_contribution_share"].max())
    fs = int(pr["financed_sessions"])

    gates = {
        "cagr_improves_0_5pp": cagr_d >= 0.005,
        "mdd_worsening_le_2pp": mdd_d >= -0.02,
        "calmar_not_below": float(pr["calmar"]) >= float(bp["calmar"]),
        "stress_above_baseline": float(ps["total_return"]) > float(bs["total_return"]),
        "neg_periods_le_1": neg <= 1,
        "concentration_le_60pct": ms <= 0.60,
        "rt_le_4": float(pr["round_trips_per_year"]) <= 4.0,
        "min_100_sessions": fs >= 100,
        "robustness_confirm": float(rb["cagr"]) > float(bp["cagr"]) and float(rs["total_return"]) > float(bs["total_return"]),
    }
    return GovernedResult(
        decision="promote" if all(gates.values()) else "retain",
        gates=gates,
        diagnostics={"cagr_delta": cagr_d, "mdd_delta": mdd_d, "sessions": fs, "neg": neg, "max_share": ms},
    )
