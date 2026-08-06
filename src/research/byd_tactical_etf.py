"""Tactical ETF sleeve weighting based on BYD/ETF relative momentum.

When BYD V1.0 signals defense (75% BYD), instead of fixed 25% ETF,
adjust ETF allocation based on:
- ETF recent momentum: strong → increase ETF (up to 40%)
- BYD recent momentum: weak → shift more to ETF
- Relative volatility: stable → maintain allocation

This naturally provides counter-cyclical benefit because ETF gets
overweighted when BYD is weak (more benefit in weak periods) and
underweighted when BYD is strong (preserving upside).
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
PRIMARY = "tactical_etf"
ROBUSTNESS = "tactical_etf_light"

# Tactical ETF parameters
ETF_MIN = 0.10    # minimum ETF allocation in defense
ETF_MAX = 0.40    # maximum ETF allocation in defense
ETF_MOM_WINDOW = 20
RS_WEIGHT = 0.5   # weight on relative strength signal


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def compute_tactical_weights(common, signals, etf_max=ETF_MAX):
    """Tactical ETF allocation based on BYD/ETF relative momentum."""
    base = signals["base_byd_weight"].astype(float)

    # ETF momentum signal
    etf_mom = common["etf_close"].pct_change(ETF_MOM_WINDOW).fillna(0)
    byd_mom = common["byd_close"].pct_change(ETF_MOM_WINDOW).fillna(0)
    rs = (etf_mom - byd_mom).clip(-0.3, 0.3)  # positive = ETF outperforming
    etf_signal = (rs / 0.3).clip(-1, 1)  # normalize to [-1, 1]
    etf_signal = etf_signal * RS_WEIGHT

    # Base ETF allocation from v1.1: 0% when risk-on (base=1.0), 25% when defense (base=0.75)
    base_etf = (1.0 - base).clip(0, None)
    # Tactical adjustment: add/subtract up to 15% based on RS
    tactical_adj = etf_signal * 0.15
    etf_target = (base_etf + tactical_adj).clip(ETF_MIN, etf_max)
    # Only apply tactical in defense (base < 1.0)
    in_defense = base < 0.99
    etf_weight = base_etf.where(~in_defense, etf_target)

    byd_weight = base.copy()
    cash = 1.0 - byd_weight - etf_weight

    return pd.DataFrame(
        {"byd_weight": byd_weight, "etf_weight": etf_weight, "cash_weight": cash},
        index=common.index,
    )


def build_decisions(common, signals):
    d = {
        BASELINE: pd.DataFrame(
            {"byd_weight": signals["base_byd_weight"].astype(float),
             "etf_weight": 1.0 - signals["base_byd_weight"].astype(float),
             "cash_weight": 0.0},
            index=common.index,
        ),
        PRIMARY: compute_tactical_weights(common, signals, ETF_MAX),
        ROBUSTNESS: compute_tactical_weights(common, signals, 0.35),
    }
    for name, frame in d.items():
        assert np.allclose(frame.sum(axis=1), 1.0, atol=1e-12), f"{name}: {frame.sum(axis=1).describe()}"
        assert not (frame["byd_weight"] < -1e-12).any()
        assert not (frame["etf_weight"] < -1e-12).any()
    return d


def run_candidates(common, signals, *, cost_bps):
    decisions = build_decisions(common, signals)
    results = {}
    for name, decision in decisions.items():
        e = execute_next_common_open(decision, common["common_open_eligible"])
        gross = e["position_byd_weight"] * common["byd_open_return"] + e["position_etf_weight"] * common["etf_open_return"]
        turnover = e.diff().abs().sum(axis=1); turnover.iloc[0] = 0.0
        cost = turnover * cost_bps / 10000.0
        daily = pd.concat([decision.add_prefix("d_"), e], axis=1)
        daily["gross_return"] = gross; daily["turnover_units"] = turnover
        daily["cost"] = cost; daily["net_return"] = gross - cost
        daily = daily.iloc[:-1].copy()
        results[name] = AllocationResult(name=name, daily=daily, trades=pd.DataFrame())
    return results, decisions


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start):pd.Timestamp(end)]
    return metrics(block)


def build_evaluation(r20, r40):
    rows = []
    for cb, results in ((PRIMARY_COST_BPS, r20), (STRESS_COST_BPS, r40)):
        for name, result in results.items():
            for w, (s, e) in WINDOWS.items():
                m = _wm(result, s, e)
                m["model"] = name; m["cost_bps"] = cb; m["window"] = w
                rows.append(m)
    return pd.DataFrame(rows)


def _tw(daily, s, e):
    rs = daily.loc[pd.Timestamp(s):pd.Timestamp(e), "net_return"].dropna()
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
            rows.append({"model": name, "period": p, "relative_terminal_wealth": r, "positive_contribution_share": max(r, 0.0)/pt if pt > 0 else 0.0})
    return pd.DataFrame(rows)


def governed_result(evaluation, contributions):
    def r(model, cb):
        sel = evaluation.loc[(evaluation["model"]==model)&(evaluation["cost_bps"]==cb)&(evaluation["window"]=="full_overlap")]
        return sel.iloc[0]
    bp = r(BASELINE, PRIMARY_COST_BPS); pp = r(PRIMARY, PRIMARY_COST_BPS)
    rp = r(ROBUSTNESS, PRIMARY_COST_BPS)
    bs = r(BASELINE, STRESS_COST_BPS); ps = r(PRIMARY, STRESS_COST_BPS)
    cagr_d = float(pp["cagr"] - bp["cagr"]); mdd_d = float(pp["max_drawdown"] - bp["max_drawdown"])
    pc = contributions[contributions["model"]==PRIMARY]
    neg = int(pc["relative_terminal_wealth"].lt(0).sum())
    ms = float(pc["positive_contribution_share"].max()) if not pc.empty else 1.0

    gates = {
        "cagr_improves": cagr_d >= 0.003,
        "mdd_ok": mdd_d >= -0.01,
        "calmar_ok": float(pp["calmar"]) >= float(bp["calmar"]),
        "stress_ok": float(ps["total_return"]) > float(bs["total_return"]),
        "neg_periods_0": neg == 0,
        "concentration_le_60pct": ms <= 0.60,
        "rt_le_4": float(pp["round_trips_per_year"]) <= 4.0,
    }
    return GovernedResult(
        decision="promote" if all(gates.values()) else "retain",
        gates=gates,
        diagnostics={"cagr_delta": cagr_d, "mdd_delta": mdd_d, "neg": neg, "max_share": ms},
    )
