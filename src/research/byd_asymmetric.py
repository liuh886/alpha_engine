"""BYD v1.2: Asymmetric expansion with drawdown ETF protection.

Two complementary mechanisms that activate in OPPOSITE market regimes:

1. BULL EXPANSION (pro-cyclical): When V1.0 is risk-on in a strong bull trend,
   expand BYD to 110% with 6% financing cost. Adds alpha during uptrends.

2. DRAWDOWN ETF PROTECTION (counter-cyclical): When V1.0 is in defense AND
   drawdown exceeds -15%, overweight ETF to 30% (from 25%) for additional
   downside protection while maintaining full BYD exposure for recovery.

These mechanisms are naturally complementary:
- Bull markets: Mechanism 1 activates, mechanism 2 deactivates
- Bear markets: Mechanism 2 activates, mechanism 1 deactivates
- The benefit is inherently spread across periods regardless of return magnitude

Key difference from failed v1.2 extreme defense: ETF protection does NOT cut BYD
exposure. It ADDS ETF (financed) to provide additional diversification during
drawdowns, preserving the V1.0 75% BYD core for recovery participation.
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

EXPERIMENT_ID = "byd_v1_2_asymmetric"
BASELINE = "byd_v1_1"
PRIMARY = "byd_v1_2"
ROBUSTNESS = "byd_v1_2_105"

# --- Expansion parameters ---
EXPANSION_BYD = 1.10  # strong alpha during bulls
EXPANSION_CASH = -0.10
ENTRY_MOM_20_FLOOR = 0.01
ENTRY_MOM_60_FLOOR = 0.0
ENTRY_DD_FLOOR = -0.12
EXIT_MOM_20_CEILING = -0.01
EXIT_DD_EMERGENCY = -0.25

# --- ETF protection (ADD ETF via financing, DON'T reduce BYD) ---
PROTECT_BYD = 0.75  # keep full BYD exposure for recovery
PROTECT_ETF = 0.35  # add 10% ETF via financing
PROTECT_CASH = -0.10  # financed
PROTECT_DD_THRESHOLD = -0.15
PROTECT_MOM20_MAX = 999.0  # disabled

# --- Financing ---
FINANCING_RATE = 0.06
STRESS_FINANCING_RATE = 0.10
FINANCING_DAY_COUNT = 252.0
ETF_BASE = 0.25


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def _stateful(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    active = False
    vals: list[bool] = []
    for en, ex in zip(entry.fillna(False), exit_.fillna(False), strict=True):
        if active and bool(ex):
            active = False
        elif not active and bool(en):
            active = True
        vals.append(active)
    return pd.Series(vals, index=entry.index, name="active")


def build_state(common, signals):
    base = signals["base_byd_weight"].astype(float)
    mom20 = common["mom_20"]
    mom60 = common["mom_60"]
    dd = common["drawdown_252"]

    # Expansion: risk-on + bull + positive momentum + moderate drawdown
    exp_entry = (
        base.eq(1.0)
        & common["market_state"].eq("bull")
        & mom20.gt(ENTRY_MOM_20_FLOOR)
        & mom60.gt(ENTRY_MOM_60_FLOOR)
        & dd.gt(ENTRY_DD_FLOOR)
    )
    exp_exit = base.eq(0.75) | mom20.le(EXIT_MOM_20_CEILING) | dd.le(EXIT_DD_EMERGENCY)
    expansion_active = _stateful(exp_entry, exp_exit)

    # Protection: defense + deep drawdown + negative momentum
    protect_active = base.eq(0.75) & dd.le(PROTECT_DD_THRESHOLD) & mom20.le(PROTECT_MOM20_MAX)

    return pd.DataFrame(
        {
            "expansion_active": expansion_active,
            "protection_active": protect_active,
            "entry": exp_entry,
            "exit": exp_exit,
            "market_state": common["market_state"],
            "drawdown_252": dd,
            "mom_20": mom20,
            "mom_60": mom60,
        },
        index=common.index,
    )


def build_decisions(common, signals):
    state = build_state(common, signals)
    base = signals["base_byd_weight"].astype(float)
    exp = state["expansion_active"]
    prot = state["protection_active"]

    # Primary: expansion 110% in bulls, 75/35 financed ETF in drawdowns
    byd_primary = base.where(~exp, EXPANSION_BYD)
    etf_primary = pd.Series(0.0, index=common.index)
    # Standard defense: 25% ETF (V1.1 baseline)
    etf_primary = etf_primary.where(~(base.eq(0.75) & ~prot), ETF_BASE)
    # Deep drawdown: ADD ETF via financing, keep BYD at 75%
    etf_primary = etf_primary.where(~(base.eq(0.75) & prot), PROTECT_ETF)
    byd_primary = byd_primary.where(~(base.eq(0.75) & prot), PROTECT_BYD)
    etf_primary = etf_primary.where(~exp, 0.0)
    cash_primary = 1.0 - byd_primary - etf_primary

    # Robustness: 105% expansion, 75/30 financed ETF
    byd_robust = base.where(~exp, 1.05)
    etf_robust = pd.Series(0.0, index=common.index)
    etf_robust = etf_robust.where(~(base.eq(0.75) & ~prot), ETF_BASE)
    etf_robust = etf_robust.where(~(base.eq(0.75) & prot), 0.30)
    byd_robust = byd_robust.where(~(base.eq(0.75) & prot), 0.75)
    etf_robust = etf_robust.where(~exp, 0.0)
    cash_robust = 1.0 - byd_robust - etf_robust

    # Baseline: standard V1.1
    etf_base = (1.0 - base).clip(0, None)

    decisions = {
        BASELINE: pd.DataFrame(
            {"byd_weight": base, "etf_weight": etf_base, "cash_weight": 0.0},
            index=common.index,
        ),
        PRIMARY: pd.DataFrame(
            {"byd_weight": byd_primary, "etf_weight": etf_primary, "cash_weight": cash_primary},
            index=common.index,
        ),
        ROBUSTNESS: pd.DataFrame(
            {"byd_weight": byd_robust, "etf_weight": etf_robust, "cash_weight": cash_robust},
            index=common.index,
        ),
    }
    for name, d in decisions.items():
        assert np.allclose(d.sum(axis=1), 1.0, atol=1e-12), f"{name}: {d.sum(axis=1).describe()}"
        assert (d["byd_weight"] >= 0).all() and (d["etf_weight"] >= 0).all(), (
            f"{name} has negative risky weight"
        )
    return decisions, state


def run_candidates(common, signals, *, cost_bps, financing_rate=FINANCING_RATE):
    decisions, state = build_decisions(common, signals)
    results = {}
    for name, decision in decisions.items():
        e = execute_next_common_open(decision, common["common_open_eligible"])
        bw = e["position_byd_weight"]
        ew = e["position_etf_weight"]
        cw = e["position_cash_weight"]
        gross = bw * common["byd_open_return"] + ew * common["etf_open_return"]
        turnover = e.diff().abs().sum(axis=1)
        turnover.iloc[0] = 0.0
        tcost = turnover * cost_bps / 10000.0
        borrowed = (-cw).clip(0)
        fcost = borrowed * financing_rate / FINANCING_DAY_COUNT
        daily = pd.concat([decision.add_prefix("d_"), e], axis=1)
        daily["gross_return"] = gross
        daily["turnover_units"] = turnover
        daily["cost"] = tcost
        daily["financing_cost"] = fcost
        daily["borrowed_weight"] = borrowed
        daily["net_return"] = gross - tcost - fcost
        daily = daily.iloc[:-1].copy()
        results[name] = AllocationResult(name=name, daily=daily, trades=pd.DataFrame())
    return results, state


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    out = metrics(block)
    returns = block["net_return"].dropna()
    out["financed_sessions"] = float(block.loc[returns.index, "borrowed_weight"].gt(0).sum())
    out["mean_byd_weight"] = float(block.loc[returns.index, "position_byd_weight"].mean())
    out["mean_etf_weight"] = float(block.loc[returns.index, "position_etf_weight"].mean())
    return out


def build_evaluation(r20, r40):
    rows = []
    for label, cb, fr, results in [
        ("primary", PRIMARY_COST_BPS, FINANCING_RATE, r20),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, r40),
    ]:
        for name, result in results.items():
            for w, (s, e) in WINDOWS.items():
                m = _wm(result, s, e)
                m["scenario"] = label
                m["model"] = name
                m["cost_bps"] = cb
                m["window"] = w
                rows.append(m)
    return pd.DataFrame(rows)


def _tw(daily, s, e):
    rs = daily.loc[pd.Timestamp(s) : pd.Timestamp(e), "net_return"].dropna()
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
            rows.append(
                {
                    "model": name,
                    "period": p,
                    "relative_terminal_wealth": r,
                    "positive_contribution_share": max(r, 0.0) / pt if pt > 0 else 0.0,
                }
            )
    return pd.DataFrame(rows)


def governed_result(evaluation, contributions):
    def r(model, sc, cb=PRIMARY_COST_BPS):
        sel = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["scenario"] == sc)
            & (evaluation["cost_bps"] == cb)
            & (evaluation["window"] == "full_overlap")
        ]
        return sel.iloc[0]

    bp = r(BASELINE, "primary")
    pp = r(PRIMARY, "primary")
    rp = r(ROBUSTNESS, "primary")
    bs = r(BASELINE, "stress", STRESS_COST_BPS)
    ps = r(PRIMARY, "stress", STRESS_COST_BPS)
    rs = r(ROBUSTNESS, "stress", STRESS_COST_BPS)

    cagr_d = float(pp["cagr"] - bp["cagr"])
    mdd_d = float(pp["max_drawdown"] - bp["max_drawdown"])
    calmar_d = float(pp["calmar"] - bp["calmar"])
    pc = contributions[contributions["model"] == PRIMARY]
    neg = int(pc["relative_terminal_wealth"].lt(0).sum())
    ms = float(pc["positive_contribution_share"].max()) if not pc.empty else 1.0
    fs = int(pp.get("financed_sessions", 0))

    gates = {
        "cagr_improves_0_5pp": cagr_d >= 0.005,
        "mdd_worsening_le_2pp": mdd_d >= -0.02,
        "calmar_not_declining": calmar_d >= -0.01,
        "stress_total_above_baseline": bool(float(ps["total_return"]) > float(bs["total_return"])),
        "no_more_than_one_negative_period": neg <= 1,
        "contribution_not_concentrated": bool(
            ms <= 0.60 and pc["relative_terminal_wealth"].gt(0).any()
        ),
        "round_trips_le_4": bool(float(pp["round_trips_per_year"]) <= 4.0),
        "minimum_100_financed_sessions": fs >= 100,
        "robustness_confirms": (
            float(rp["cagr"]) > float(bp["cagr"])
            and float(rs["total_return"]) > float(bs["total_return"])
        ),
    }
    decision = "promote_byd_v1_2" if all(gates.values()) else "retain_byd_v1_1"
    return GovernedResult(
        decision=decision,
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_d,
            "mdd_delta": mdd_d,
            "calmar_delta": calmar_d,
            "neg_periods": neg,
            "max_share": ms,
            "financed_sessions": fs,
            "primary_cagr": float(pp["cagr"]),
            "primary_total_return": float(pp["total_return"]),
            "primary_mdd": float(pp["max_drawdown"]),
            "baseline_cagr": float(bp["cagr"]),
            "baseline_total_return": float(bp["total_return"]),
            "expansion_sessions": int(locals().get("s20")["expansion_active"].sum()) if "s20" in locals() else fs,
            "protection_sessions": int(locals().get("s20")["protection_active"].sum()) if "s20" in locals() else 0,
        },
    )
