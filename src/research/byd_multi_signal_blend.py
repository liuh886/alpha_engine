"""BYD v1.2: Volatility-adaptive ETF sizing on V1.0/V1.1 foundation.

During defense (V1.0 = 0.75), adjust ETF allocation based on BYD realized
volatility relative to its own history:

- High vol (> 1.2x median): ETF = 30% (increased diversification)
- Normal vol (0.8-1.2x median): ETF = 25% (V1.1 baseline)
- Low vol (< 0.8x median): ETF = 20% (leaning into BYD stability)

Signal is anchored to BYD's rolling 252-day median vol, making it adaptive
to changing market conditions. Uses 60-day realized vol for responsiveness.
No leverage, no BYD expansion, no financing.

Benefits are counter-cyclical: vol spikes during drawdowns (both bull and
bear market drawdowns), so the ETF cushion activates when most needed.
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

EXPERIMENT_ID = "byd_v1_2_vol_adaptive_etf"
BASELINE = "byd_v1_1"
PRIMARY = "byd_v1_2"
ROBUSTNESS = "byd_v1_2_conservative"

VOL_WINDOW = 60
VOL_MEDIAN_WINDOW = 252
HIGH_VOL_RATIO = 1.20
LOW_VOL_RATIO = 0.80
ETF_HIGH = 0.30
ETF_BASE = 0.25
ETF_LOW = 0.20


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def compute_weights(common, signals, etf_high=ETF_HIGH, etf_low=ETF_LOW):
    """Volatility-adaptive ETF sizing during defense."""
    v1_base = signals["base_byd_weight"].astype(float)

    byd_rets = common["byd_open_return"]
    realized_vol = byd_rets.rolling(VOL_WINDOW, min_periods=20).std(ddof=0) * np.sqrt(252)
    vol_median = realized_vol.rolling(VOL_MEDIAN_WINDOW, min_periods=60).median()
    vol_ratio = realized_vol / vol_median.replace(0, np.nan)
    vol_ratio = vol_ratio.fillna(1.0)

    in_defense = v1_base < 0.99
    etf_weight = pd.Series(ETF_BASE, index=common.index)
    etf_weight = etf_weight.where(~(in_defense & (vol_ratio > HIGH_VOL_RATIO)), etf_high)
    etf_weight = etf_weight.where(~(in_defense & (vol_ratio < LOW_VOL_RATIO)), etf_low)
    etf_weight = etf_weight.where(in_defense, 0.0)

    byd_weight = v1_base.copy()
    cash = 1.0 - byd_weight - etf_weight

    result = pd.DataFrame(
        {"byd_weight": byd_weight, "etf_weight": etf_weight, "cash_weight": cash},
        index=common.index,
    )
    assert np.allclose(result.sum(axis=1), 1.0, atol=1e-12)
    assert (result["byd_weight"] >= 0).all() and (result["etf_weight"] >= 0).all()
    return result


def build_decisions(common, signals):
    return {
        BASELINE: pd.DataFrame(
            {
                "byd_weight": signals["base_byd_weight"].astype(float),
                "etf_weight": 1.0 - signals["base_byd_weight"].astype(float),
                "cash_weight": 0.0,
            },
            index=common.index,
        ),
        PRIMARY: compute_weights(common, signals, ETF_HIGH, ETF_LOW),
        ROBUSTNESS: compute_weights(common, signals, 0.275, 0.225),
    }


def run_candidates(
    common: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    cost_bps: float,
) -> tuple[dict[str, AllocationResult], pd.DataFrame]:
    decisions = build_decisions(common, signals)
    results: dict[str, AllocationResult] = {}
    for name, decision in decisions.items():
        executed = execute_next_common_open(decision, common["common_open_eligible"])
        gross = (
            executed["position_byd_weight"] * common["byd_open_return"]
            + executed["position_etf_weight"] * common["etf_open_return"]
        )
        turnover = executed.diff().abs().sum(axis=1)
        turnover.iloc[0] = 0.0
        cost = turnover * cost_bps / 10000.0
        daily = pd.concat([decision.add_prefix("d_"), executed], axis=1)
        daily["gross_return"] = gross
        daily["turnover_units"] = turnover
        daily["cost"] = cost
        daily["net_return"] = gross - cost
        daily = daily.iloc[:-1].copy()
        results[name] = AllocationResult(name=name, daily=daily, trades=pd.DataFrame())
    return results, decisions


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    out = metrics(block)
    returns = block["net_return"].dropna()
    out["mean_etf_weight"] = float(block.loc[returns.index, "position_etf_weight"].mean())
    return out


def build_evaluation(r20, r40):
    rows = []
    for cb, results in ((PRIMARY_COST_BPS, r20), (STRESS_COST_BPS, r40)):
        for name, result in results.items():
            for w, (s, e) in WINDOWS.items():
                m = _wm(result, s, e)
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
    def r(model, cb):
        sel = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["cost_bps"] == cb)
            & (evaluation["window"] == "full_overlap")
        ]
        return sel.iloc[0]

    bp = r(BASELINE, PRIMARY_COST_BPS)
    pp = r(PRIMARY, PRIMARY_COST_BPS)
    rp_ = r(ROBUSTNESS, PRIMARY_COST_BPS)
    bs = r(BASELINE, STRESS_COST_BPS)
    ps = r(PRIMARY, STRESS_COST_BPS)
    rs_ = r(ROBUSTNESS, STRESS_COST_BPS)

    cagr_d = float(pp["cagr"] - bp["cagr"])
    mdd_d = float(pp["max_drawdown"] - bp["max_drawdown"])
    pc = contributions[contributions["model"] == PRIMARY]
    neg = int(pc["relative_terminal_wealth"].lt(0).sum())
    ms = float(pc["positive_contribution_share"].max()) if not pc.empty else 1.0

    gates = {
        "cagr_improves": cagr_d >= 0.002,
        "mdd_not_worse": mdd_d >= -0.01,
        "calmar_ok": float(pp["calmar"]) >= float(bp["calmar"]),
        "stress_above_baseline": float(ps["total_return"]) > float(bs["total_return"]),
        "neg_periods_0": neg == 0,
        "concentration_le_60pct": ms <= 0.60,
        "rt_le_3": float(pp["round_trips_per_year"]) <= 3.0,
        "robustness_confirm": float(rp_["cagr"]) >= float(bp["cagr"]) - 0.002
        and float(rs_["total_return"]) > float(bs["total_return"]),
    }
    decision = "promote_byd_v1_2" if all(gates.values()) else "retain_byd_v1_1"
    return GovernedResult(
        decision=decision,
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_d,
            "mdd_delta": mdd_d,
            "neg": neg,
            "max_share": ms,
            "primary_cagr": float(pp["cagr"]),
            "baseline_cagr": float(bp["cagr"]),
            "primary_total": float(pp["total_return"]),
            "baseline_total": float(bp["total_return"]),
        },
    )
