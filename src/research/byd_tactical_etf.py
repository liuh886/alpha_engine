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
    AllocationResult,
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    metrics,
    prepare_common_dataset,
)
from src.research.byd_515180_execution import execute_next_common_open

BASELINE = "byd_v1_1"
PRIMARY = "tactical_etf"
ROBUSTNESS = "tactical_etf_light"

ETF_MIN = 0.10
ETF_MAX = 0.40
ETF_MOM_WINDOW = 20
RS_WEIGHT = 0.5


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


def compute_tactical_weights(common, signals, etf_max=ETF_MAX):
    """Tactical ETF allocation based on BYD/ETF relative momentum."""
    base = signals["base_byd_weight"].astype(float)

    etf_mom = common["etf_close"].pct_change(ETF_MOM_WINDOW).fillna(0)
    byd_mom = common["byd_close"].pct_change(ETF_MOM_WINDOW).fillna(0)
    relative_strength = (etf_mom - byd_mom).clip(-0.3, 0.3)
    etf_signal = (relative_strength / 0.3).clip(-1, 1) * RS_WEIGHT

    base_etf = (1.0 - base).clip(0, None)
    tactical_adjustment = etf_signal * 0.15
    etf_target = (base_etf + tactical_adjustment).clip(ETF_MIN, etf_max)
    in_defense = base < 0.99
    etf_weight = base_etf.where(~in_defense, etf_target)

    byd_weight = base.copy()
    cash = 1.0 - byd_weight - etf_weight

    return pd.DataFrame(
        {
            "byd_weight": byd_weight,
            "etf_weight": etf_weight,
            "cash_weight": cash,
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
        PRIMARY: compute_tactical_weights(common, signals, ETF_MAX),
        ROBUSTNESS: compute_tactical_weights(common, signals, 0.35),
    }
    for name, frame in decisions.items():
        assert np.allclose(
            frame.sum(axis=1), 1.0, atol=1e-12
        ), f"{name}: {frame.sum(axis=1).describe()}"
        assert not (frame["byd_weight"] < -1e-12).any()
        assert not (frame["etf_weight"] < -1e-12).any()
    return decisions


def run_candidates(common, signals, *, cost_bps):
    decisions = build_decisions(common, signals)
    results = {}
    for name, decision in decisions.items():
        executed = execute_next_common_open(
            decision, common["common_open_eligible"]
        )
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
        results[name] = AllocationResult(
            name=name, daily=daily, trades=pd.DataFrame()
        )
    return results, decisions


def _wm(result, start, end):
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    return metrics(block)


def build_evaluation(r20, r40):
    rows = []
    for cost_bps, results in (
        (PRIMARY_COST_BPS, r20),
        (STRESS_COST_BPS, r40),
    ):
        for name, result in results.items():
            for window, (start, end) in WINDOWS.items():
                row = _wm(result, start, end)
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
    def row(model, cost_bps):
        selected = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["cost_bps"] == cost_bps)
            & (evaluation["window"] == "full_overlap")
        ]
        return selected.iloc[0]

    baseline_primary = row(BASELINE, PRIMARY_COST_BPS)
    primary = row(PRIMARY, PRIMARY_COST_BPS)
    baseline_stress = row(BASELINE, STRESS_COST_BPS)
    primary_stress = row(PRIMARY, STRESS_COST_BPS)
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
        "cagr_improves": cagr_delta >= 0.003,
        "mdd_ok": mdd_delta >= -0.01,
        "calmar_ok": float(primary["calmar"])
        >= float(baseline_primary["calmar"]),
        "stress_ok": float(primary_stress["total_return"])
        > float(baseline_stress["total_return"]),
        "neg_periods_0": negative_periods == 0,
        "concentration_le_60pct": max_share <= 0.60,
        "rt_le_4": float(primary["round_trips_per_year"]) <= 4.0,
    }
    return GovernedResult(
        decision="promote" if all(gates.values()) else "retain",
        gates=gates,
        diagnostics={
            "cagr_delta": cagr_delta,
            "mdd_delta": mdd_delta,
            "neg": negative_periods,
            "max_share": max_share,
        },
    )
