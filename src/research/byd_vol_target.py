"""Volatility-targeted continuous position sizing for BYD.

Instead of binary 75%/100% positions (V1.0) with fixed 515180 sleeve (V1.1),
this module dynamically adjusts BYD exposure based on rolling realized
volatility. The mechanism:

- Compute 60-day rolling annualized volatility
- When vol is low (<30%): allow modest expansion (up to 1.10)
- When vol is moderate (30-45%): maintain base V1.0/V1.1 weights
- When vol is high (>45%): reduce BYD exposure (down to 0.60)

This spreads benefit across ALL market regimes because vol spikes happen in
bull AND bear markets. The 515180 allocation scales proportionally.
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
PRIMARY = "vol_target"
ROBUSTNESS = "vol_target_wide"

# Parameters
VOL_LOOKBACK = 60
TARGET_VOL = 0.35  # 35% annualized target
VOL_FLOOR = 0.18  # prevent division by zero
MIN_BYD = 0.60  # minimum BYD weight (floor)
MAX_BYD = 1.10  # maximum BYD weight (ceiling)
MAX_ETF = 0.40  # maximum ETF allocation
SMOOTHING = 3  # EMA smoothing days


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def compute_vol_target(common, signals, max_byd=MAX_BYD):
    """Compute continuous vol-targeted BYD weight."""
    base = signals["base_byd_weight"].astype(float)

    # Rolling realized volatility (annualized)
    rolling_vol = (
        common["byd_open_return"]
        .rolling(VOL_LOOKBACK, min_periods=20)
        .std(ddof=0)
        .multiply(np.sqrt(252))
    )
    # Smooth
    vol_forecast = rolling_vol.ewm(span=SMOOTHING, min_periods=20).mean()
    vol_forecast = vol_forecast.clip(lower=VOL_FLOOR).fillna(TARGET_VOL)

    # Scale factor: target_vol / realized_vol
    scale = TARGET_VOL / vol_forecast
    # When vol > target: scale < 1 (reduce)
    # When vol < target: scale > 1 (expand)

    # Target BYD weight: base × scale, bounded
    byd_target = base * scale
    byd_weight = byd_target.clip(lower=MIN_BYD, upper=max_byd)

    # ETF: keep proportional to base allocation, but bounded
    # V1.0 base determines ETF: when base=0.75, ETF=0.25; when base=1.0, ETF=0.0
    etf_ratio = (1.0 - base).clip(0, None)
    # When vol scaling reduces BYD, extra capital goes to ETF or cash
    # When vol scaling increases BYD, reduce ETF
    remaining = (1.0 - byd_weight).clip(0, None)
    etf_weight = pd.concat([remaining, etf_ratio], axis=1).min(axis=1)
    etf_weight = etf_weight.clip(0, MAX_ETF)
    cash = 1.0 - byd_weight - etf_weight

    return pd.DataFrame(
        {
            "byd_weight": byd_weight.astype(float),
            "etf_weight": etf_weight.astype(float),
            "cash_weight": cash.astype(float),
        },
        index=common.index,
    )


def build_decisions(common, signals):
    d = {
        BASELINE: pd.DataFrame(
            {
                "byd_weight": signals["base_byd_weight"].astype(float),
                "etf_weight": 1.0 - signals["base_byd_weight"].astype(float),
                "cash_weight": 0.0,
            },
            index=common.index,
        ),
        PRIMARY: compute_vol_target(common, signals, MAX_BYD),
        ROBUSTNESS: compute_vol_target(common, signals, max_byd=1.05),
    }
    for name, frame in d.items():
        assert np.allclose(frame.sum(axis=1), 1.0, atol=1e-12), f"{name} weights don't sum to 1"
        assert not (frame["byd_weight"] < -1e-12).any(), f"{name} has negative BYD weight"
        assert not (frame["etf_weight"] < -1e-12).any(), f"{name} has negative ETF weight"
    return d


# Financing
FINANCING_RATE = 0.06
FINANCING_DAY_COUNT = 252.0


def run_candidates(common, signals, *, cost_bps):
    decisions = build_decisions(common, signals)
    results = {}
    for name, decision in decisions.items():
        e = execute_next_common_open(decision, common["common_open_eligible"])
        bw = e["position_byd_weight"]
        ew = e["position_etf_weight"]
        cw = e["position_cash_weight"]
        gross = bw * common["byd_open_return"] + ew * common["etf_open_return"]
        turnover = e.diff().abs().sum(axis=1)
        turnover.iloc[0] = 0.0
        cost = turnover * cost_bps / 10000.0
        borrowed = (-cw).clip(0)
        fcost = borrowed * FINANCING_RATE / FINANCING_DAY_COUNT
        daily = pd.concat([decision.add_prefix("d_"), e], axis=1)
        daily["gross_return"] = gross
        daily["turnover_units"] = turnover
        daily["cost"] = cost
        daily["financing_cost"] = fcost
        daily["net_return"] = gross - cost - fcost
        daily = daily.iloc[:-1].copy()
        results[name] = AllocationResult(name=name, daily=daily, trades=pd.DataFrame())
    return results, decisions


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty window {start} to {end}")
    out = metrics(block)
    returns = block["net_return"].dropna()
    out["mean_byd_weight"] = float(block.loc[returns.index, "position_byd_weight"].mean())
    return out


def build_evaluation(r20, r40):
    rows = []
    for label, cb, results in [
        ("primary", PRIMARY_COST_BPS, r20),
        ("stress", STRESS_COST_BPS, r40),
    ]:
        for name, result in results.items():
            for w, (s, e) in WINDOWS.items():
                rows.append(
                    {
                        "scenario": label,
                        "model": name,
                        "cost_bps": cb,
                        "window": w,
                        **_wm(result, s, e),
                    }
                )
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
        if len(sel) != 1:
            raise ValueError(f"Expected 1 row for {model}/{sc}/{cb}, got {len(sel)}")
        return sel.iloc[0]

    bp = r(BASELINE, "primary")
    pp = r(PRIMARY, "primary")
    r(ROBUSTNESS, "primary")
    bs = r(BASELINE, "stress", STRESS_COST_BPS)
    ps = r(PRIMARY, "stress", STRESS_COST_BPS)
    r(ROBUSTNESS, "stress", STRESS_COST_BPS)
    cagr_d = float(pp["cagr"] - bp["cagr"])
    mdd_d = float(pp["max_drawdown"] - bp["max_drawdown"])
    pc = contributions[contributions["model"] == PRIMARY]
    neg = int(pc["relative_terminal_wealth"].lt(0).sum())
    ms = float(pc["positive_contribution_share"].max()) if not pc.empty else 1.0

    gates = {
        "cagr_improves": cagr_d >= 0.002,
        "mdd_ok": mdd_d >= -0.02,
        "calmar_ok": float(pp["calmar"]) >= float(bp["calmar"]),
        "stress_ok": float(ps["total_return"]) > float(bs["total_return"]),
        "neg_periods_le_1": neg <= 1,
        "concentration_le_60pct": ms <= 0.60,
        "rt_le_6": float(pp["round_trips_per_year"]) <= 6.0,
    }
    return GovernedResult(
        decision="promote" if all(gates.values()) else "retain",
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_d,
            "mdd_delta": mdd_d,
            "neg": neg,
            "max_share": ms,
            "primary_cagr": float(pp["cagr"]),
            "primary_mdd": float(pp["max_drawdown"]),
        },
    )
