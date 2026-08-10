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

VOL_LOOKBACK = 60
TARGET_VOL = 0.35
VOL_FLOOR = 0.18
MIN_BYD = 0.60
MAX_BYD = 1.10
MAX_ETF = 0.40
SMOOTHING = 3

FINANCING_RATE = 0.06
FINANCING_DAY_COUNT = 252.0


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def compute_vol_target(common, signals, max_byd=MAX_BYD):
    """Compute continuous vol-targeted BYD weight."""
    base = signals["base_byd_weight"].astype(float)

    rolling_vol = (
        common["byd_open_return"]
        .rolling(VOL_LOOKBACK, min_periods=20)
        .std(ddof=0)
        .multiply(np.sqrt(252))
    )
    vol_forecast = rolling_vol.ewm(span=SMOOTHING, min_periods=20).mean()
    vol_forecast = vol_forecast.clip(lower=VOL_FLOOR).fillna(TARGET_VOL)

    scale = TARGET_VOL / vol_forecast
    byd_target = base * scale
    byd_weight = byd_target.clip(lower=MIN_BYD, upper=max_byd)

    etf_ratio = (1.0 - base).clip(0, None)
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
    base = signals["base_byd_weight"].astype(float)
    decisions = {
        BASELINE: pd.DataFrame(
            {
                "byd_weight": base,
                "etf_weight": 1.0 - base,
                "cash_weight": 0.0,
            },
            index=common.index,
        ),
        PRIMARY: compute_vol_target(common, signals, MAX_BYD),
        ROBUSTNESS: compute_vol_target(common, signals, max_byd=1.05),
    }
    for name, frame in decisions.items():
        assert np.allclose(
            frame.sum(axis=1), 1.0, atol=1e-12
        ), f"{name} weights don't sum to 1"
        assert not (frame["byd_weight"] < -1e-12).any(), (
            f"{name} has negative BYD weight"
        )
        assert not (frame["etf_weight"] < -1e-12).any(), (
            f"{name} has negative ETF weight"
        )
    return decisions


def run_candidates(common, signals, *, cost_bps):
    decisions = build_decisions(common, signals)
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
        cost = turnover * cost_bps / 10000.0
        borrowed = (-cash_weight).clip(0)
        fcost = borrowed * FINANCING_RATE / FINANCING_DAY_COUNT
        daily = pd.concat([decision.add_prefix("d_"), executed], axis=1)
        daily["gross_return"] = gross
        daily["turnover_units"] = turnover
        daily["cost"] = cost
        daily["financing_cost"] = fcost
        daily["net_return"] = gross - cost - fcost
        daily = daily.iloc[:-1].copy()
        results[name] = AllocationResult(
            name=name, daily=daily, trades=pd.DataFrame()
        )
    return results, decisions


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty window {start} to {end}")
    out = metrics(block)
    returns = block["net_return"].dropna()
    out["mean_byd_weight"] = float(
        block.loc[returns.index, "position_byd_weight"].mean()
    )
    return out


def build_evaluation(r20, r40):
    rows = []
    for label, cost_bps, results in [
        ("primary", PRIMARY_COST_BPS, r20),
        ("stress", STRESS_COST_BPS, r40),
    ]:
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
    def row(model, scenario, cost_bps=PRIMARY_COST_BPS):
        selected = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["scenario"] == scenario)
            & (evaluation["cost_bps"] == cost_bps)
            & (evaluation["window"] == "full_overlap")
        ]
        if len(selected) != 1:
            raise ValueError(
                f"Expected 1 row for {model}/{scenario}/{cost_bps}, "
                f"got {len(selected)}"
            )
        return selected.iloc[0]

    baseline_primary = row(BASELINE, "primary")
    primary = row(PRIMARY, "primary")
    baseline_stress = row(BASELINE, "stress", STRESS_COST_BPS)
    primary_stress = row(PRIMARY, "stress", STRESS_COST_BPS)
    cagr_delta = float(primary["cagr"] - baseline_primary["cagr"])
    mdd_delta = float(
        primary["max_drawdown"] - baseline_primary["max_drawdown"]
    )
    primary_contributions = contributions[contributions["model"] == PRIMARY]
    negative_periods = int(
        primary_contributions["relative_terminal_wealth"].lt(0).sum()
    )
    max_share = (
        float(primary_contributions["positive_contribution_share"].max())
        if not primary_contributions.empty
        else 1.0
    )

    gates = {
        "cagr_improves": cagr_delta >= 0.002,
        "mdd_ok": mdd_delta >= -0.02,
        "calmar_ok": float(primary["calmar"])
        >= float(baseline_primary["calmar"]),
        "stress_ok": float(primary_stress["total_return"])
        > float(baseline_stress["total_return"]),
        "neg_periods_le_1": negative_periods <= 1,
        "concentration_le_60pct": max_share <= 0.60,
        "rt_le_6": float(primary["round_trips_per_year"]) <= 6.0,
    }
    return GovernedResult(
        decision="promote" if all(gates.values()) else "retain",
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_delta,
            "mdd_delta": mdd_delta,
            "neg": negative_periods,
            "max_share": max_share,
            "primary_cagr": float(primary["cagr"]),
            "primary_mdd": float(primary["max_drawdown"]),
        },
    )
