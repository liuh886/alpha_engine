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

EXPANSION_BYD = 1.10
EXPANSION_CASH = -0.10
ENTRY_MOM_20_FLOOR = 0.01
ENTRY_MOM_60_FLOOR = 0.0
ENTRY_DD_FLOOR = -0.12
EXIT_MOM_20_CEILING = -0.01
EXIT_DD_EMERGENCY = -0.25

PROTECT_BYD = 0.75
PROTECT_ETF = 0.35
PROTECT_CASH = -0.10
PROTECT_DD_THRESHOLD = -0.15
PROTECT_MOM20_MAX = 999.0

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

    exp_entry = (
        base.eq(1.0)
        & common["market_state"].eq("bull")
        & mom20.gt(ENTRY_MOM_20_FLOOR)
        & mom60.gt(ENTRY_MOM_60_FLOOR)
        & dd.gt(ENTRY_DD_FLOOR)
    )
    exp_exit = (
        base.eq(0.75)
        | mom20.le(EXIT_MOM_20_CEILING)
        | dd.le(EXIT_DD_EMERGENCY)
    )
    expansion_active = _stateful(exp_entry, exp_exit)

    protect_active = (
        base.eq(0.75)
        & dd.le(PROTECT_DD_THRESHOLD)
        & mom20.le(PROTECT_MOM20_MAX)
    )

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

    byd_primary = base.where(~exp, EXPANSION_BYD)
    etf_primary = pd.Series(0.0, index=common.index)
    etf_primary = etf_primary.where(~(base.eq(0.75) & ~prot), ETF_BASE)
    etf_primary = etf_primary.where(~(base.eq(0.75) & prot), PROTECT_ETF)
    byd_primary = byd_primary.where(~(base.eq(0.75) & prot), PROTECT_BYD)
    etf_primary = etf_primary.where(~exp, 0.0)
    cash_primary = 1.0 - byd_primary - etf_primary

    byd_robust = base.where(~exp, 1.05)
    etf_robust = pd.Series(0.0, index=common.index)
    etf_robust = etf_robust.where(~(base.eq(0.75) & ~prot), ETF_BASE)
    etf_robust = etf_robust.where(~(base.eq(0.75) & prot), 0.30)
    byd_robust = byd_robust.where(~(base.eq(0.75) & prot), 0.75)
    etf_robust = etf_robust.where(~exp, 0.0)
    cash_robust = 1.0 - byd_robust - etf_robust

    etf_base = (1.0 - base).clip(0, None)

    decisions = {
        BASELINE: pd.DataFrame(
            {"byd_weight": base, "etf_weight": etf_base, "cash_weight": 0.0},
            index=common.index,
        ),
        PRIMARY: pd.DataFrame(
            {
                "byd_weight": byd_primary,
                "etf_weight": etf_primary,
                "cash_weight": cash_primary,
            },
            index=common.index,
        ),
        ROBUSTNESS: pd.DataFrame(
            {
                "byd_weight": byd_robust,
                "etf_weight": etf_robust,
                "cash_weight": cash_robust,
            },
            index=common.index,
        ),
    }
    for name, decision in decisions.items():
        assert np.allclose(
            decision.sum(axis=1), 1.0, atol=1e-12
        ), f"{name}: {decision.sum(axis=1).describe()}"
        assert (
            (decision["byd_weight"] >= 0).all()
            and (decision["etf_weight"] >= 0).all()
        ), f"{name} has negative risky weight"
    return decisions, state


def run_candidates(common, signals, *, cost_bps, financing_rate=FINANCING_RATE):
    decisions, state = build_decisions(common, signals)
    results = {}
    for name, decision in decisions.items():
        executed = execute_next_common_open(
            decision, common["common_open_eligible"]
        )
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
        fcost = borrowed * financing_rate / FINANCING_DAY_COUNT
        daily = pd.concat([decision.add_prefix("d_"), executed], axis=1)
        daily["gross_return"] = gross
        daily["turnover_units"] = turnover
        daily["cost"] = tcost
        daily["financing_cost"] = fcost
        daily["borrowed_weight"] = borrowed
        daily["net_return"] = gross - tcost - fcost
        daily = daily.iloc[:-1].copy()
        results[name] = AllocationResult(
            name=name, daily=daily, trades=pd.DataFrame()
        )
    return results, state


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    out = metrics(block)
    returns = block["net_return"].dropna()
    out["financed_sessions"] = float(
        block.loc[returns.index, "borrowed_weight"].gt(0).sum()
    )
    out["mean_byd_weight"] = float(
        block.loc[returns.index, "position_byd_weight"].mean()
    )
    out["mean_etf_weight"] = float(
        block.loc[returns.index, "position_etf_weight"].mean()
    )
    return out


def build_evaluation(r20, r40):
    rows = []
    for label, cost_bps, _financing_rate, results in [
        ("primary", PRIMARY_COST_BPS, FINANCING_RATE, r20),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, r40),
    ]:
        for name, result in results.items():
            for window, (start, end) in WINDOWS.items():
                row = _wm(result, start, end)
                row["scenario"] = label
                row["model"] = name
                row["cost_bps"] = cost_bps
                row["window"] = window
                rows.append(row)
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
    def row(model, scenario, cost_bps=PRIMARY_COST_BPS):
        selected = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["scenario"] == scenario)
            & (evaluation["cost_bps"] == cost_bps)
            & (evaluation["window"] == "full_overlap")
        ]
        return selected.iloc[0]

    baseline_primary = row(BASELINE, "primary")
    primary = row(PRIMARY, "primary")
    robustness = row(ROBUSTNESS, "primary")
    baseline_stress = row(BASELINE, "stress", STRESS_COST_BPS)
    primary_stress = row(PRIMARY, "stress", STRESS_COST_BPS)
    robustness_stress = row(ROBUSTNESS, "stress", STRESS_COST_BPS)

    cagr_delta = float(primary["cagr"] - baseline_primary["cagr"])
    mdd_delta = float(
        primary["max_drawdown"] - baseline_primary["max_drawdown"]
    )
    calmar_delta = float(primary["calmar"] - baseline_primary["calmar"])
    primary_contributions = contributions[contributions["model"] == PRIMARY]
    negative_periods = int(
        primary_contributions["relative_terminal_wealth"].lt(0).sum()
    )
    max_share = (
        float(primary_contributions["positive_contribution_share"].max())
        if not primary_contributions.empty
        else 1.0
    )
    financed_sessions = int(primary.get("financed_sessions", 0))

    gates = {
        "cagr_improves_0_5pp": cagr_delta >= 0.005,
        "mdd_worsening_le_2pp": mdd_delta >= -0.02,
        "calmar_not_declining": calmar_delta >= -0.01,
        "stress_total_above_baseline": bool(
            float(primary_stress["total_return"])
            > float(baseline_stress["total_return"])
        ),
        "no_more_than_one_negative_period": negative_periods <= 1,
        "contribution_not_concentrated": bool(
            max_share <= 0.60
            and primary_contributions["relative_terminal_wealth"].gt(0).any()
        ),
        "round_trips_le_4": bool(
            float(primary["round_trips_per_year"]) <= 4.0
        ),
        "minimum_100_financed_sessions": financed_sessions >= 100,
        "robustness_confirms": (
            float(robustness["cagr"]) > float(baseline_primary["cagr"])
            and float(robustness_stress["total_return"])
            > float(baseline_stress["total_return"])
        ),
    }
    decision = (
        "promote_byd_v1_2" if all(gates.values()) else "retain_byd_v1_1"
    )
    return GovernedResult(
        decision=decision,
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_delta,
            "mdd_delta": mdd_delta,
            "calmar_delta": calmar_delta,
            "neg_periods": negative_periods,
            "max_share": max_share,
            "financed_sessions": financed_sessions,
            "primary_cagr": float(primary["cagr"]),
            "primary_total_return": float(primary["total_return"]),
            "primary_mdd": float(primary["max_drawdown"]),
            "baseline_cagr": float(baseline_primary["cagr"]),
            "baseline_total_return": float(baseline_primary["total_return"]),
        },
    )
