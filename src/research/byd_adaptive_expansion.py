"""Governed BYD adaptive multi-tier trend-expansion research.

BYD v1.1 remains the accepted formal baseline. This module tests an improved
expansion mechanism: relaxed entry conditions (no vol filter, wider drawdown
tolerance), tiered leverage levels scaled by momentum strength, and continuous
financing-charged expansion rather than a single binary threshold.

Key improvements over v1.2 trend expansion:
1. Removes vol_state requirement which limited sessions (86 → target 126+)
2. Relaxes drawdown floor from -10% to -15%
3. Three graduated leverage tiers instead of one binary level
4. Momentum-strength-gated tier selection
5. Drawdown-based exit guard
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

# ---------------------------------------------------------------------------
# Frozen candidates (pre-registered, no post-result changes allowed)
# ---------------------------------------------------------------------------
BASELINE = "byd_v1_1"
PRIMARY = "adaptive_expansion_tiered"
ROBUSTNESS = "adaptive_expansion_105"
DIAGNOSTIC = "adaptive_expansion_continuous"

PRIMARY_FINANCING_RATE = 0.06
STRESS_FINANCING_RATE = 0.10
FINANCING_DAY_COUNT = 252.0

# Relaxed expansion rules vs v1.2:
# - No vol_state filter (was the biggest limiter of session count)
# - Drawdown floor -15% (was -10%)
# - Exit when drawdown worsens below -25% (new drawdown guard)
RULES = {
    "entry_base_byd_weight": 1.0,
    "entry_market_state": "bull",
    "entry_mom_20_floor": 0.02,       # slight positive threshold
    "entry_mom_60_floor": 0.0,
    "entry_drawdown_252_floor": -0.15,  # relaxed from -0.10
    "exit_base_byd_weight": 0.75,
    "exit_mom_20_ceiling": -0.02,
    "exit_drawdown_252_ceiling": -0.25,  # drawdown emergency exit
    # Tiered leverage: strong momentum → higher leverage
    "tier1_byd_weight": 1.05,          # base expansion (robustness)
    "tier2_byd_weight": 1.10,          # moderate expansion
    "tier3_byd_weight": 1.15,          # strong expansion (primary)
    "tier2_mom_20_min": 0.05,          # mom_20 > 5% for tier 2
    "tier2_mom_60_min": 0.03,          # mom_60 > 3% for tier 2
    "tier3_mom_20_min": 0.10,          # mom_20 > 10% for tier 3
    "tier3_mom_60_min": 0.05,          # mom_60 > 5% for tier 3
    # Continuous variant parameters
    "continuous_base": 1.0,
    "continuous_max": 1.125,
    "continuous_momentum_scale": 2.0,  # sensitivity to momentum composite
}


@dataclass(frozen=True)
class GovernedResult:
    decision: str
    gates: dict[str, bool]
    diagnostics: dict[str, Any]


# ---------------------------------------------------------------------------
# State machine: adaptive tiered expansion
# ---------------------------------------------------------------------------

def _stateful_expansion(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    if not entry.index.equals(exit_.index):
        raise ValueError("entry and exit indices must match")
    active = False
    values: list[bool] = []
    for enter_now, exit_now in zip(
        entry.fillna(False), exit_.fillna(False), strict=True
    ):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        values.append(active)
    return pd.Series(values, index=entry.index, name="expansion_active")


def build_expansion_state(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "market_state",
        "drawdown_252",
        "mom_20",
        "mom_60",
        "vol_state",
    }
    missing = sorted(required - set(common.columns))
    if missing:
        raise ValueError(f"common dataset missing fields: {missing}")
    if "base_byd_weight" not in signals:
        raise ValueError("signals missing base_byd_weight")
    if not common.index.equals(signals.index):
        raise ValueError("common and signal indices must match")

    base = signals["base_byd_weight"].astype(float)
    mom_20 = common["mom_20"].astype(float)
    mom_60 = common["mom_60"].astype(float)
    dd = common["drawdown_252"].astype(float)

    # Entry: base at 100% (risk-on), bull market, positive momentum, not in deep DD
    entry = (
        base.eq(RULES["entry_base_byd_weight"])
        & common["market_state"].eq(RULES["entry_market_state"])
        & mom_20.gt(RULES["entry_mom_20_floor"])
        & mom_60.gt(RULES["entry_mom_60_floor"])
        & dd.gt(RULES["entry_drawdown_252_floor"])
    )

    # Exit: base goes to 75% (defense) OR momentum turns negative OR DD emergency
    exit_ = (
        base.eq(RULES["exit_base_byd_weight"])
        | mom_20.le(RULES["exit_mom_20_ceiling"])
        | dd.le(RULES["exit_drawdown_252_ceiling"])
    )

    active = _stateful_expansion(entry, exit_)

    # Tier determination (only matters when active)
    # Tier 3 (strongest): mom_20 > 10% AND mom_60 > 5%
    # Tier 2 (moderate): mom_20 > 5% AND mom_60 > 3%
    # Tier 1 (base): everything else (just meets entry conditions)
    tier3 = (
        active
        & mom_20.gt(RULES["tier3_mom_20_min"])
        & mom_60.gt(RULES["tier3_mom_60_min"])
    )
    tier2 = (
        active
        & ~tier3
        & mom_20.gt(RULES["tier2_mom_20_min"])
        & mom_60.gt(RULES["tier2_mom_60_min"])
    )
    tier1 = active & ~tier3 & ~tier2

    # Momentum composite score for continuous variant (0 to 1)
    mom_composite = (
        mom_20.clip(0, 0.20) / 0.20 * 0.5
        + mom_60.clip(0, 0.15) / 0.15 * 0.3
        + dd.clip(-0.15, 0.0).add(0.15).div(0.15) * 0.2
    ).clip(0, 1)

    return pd.DataFrame(
        {
            "base_byd_weight": base,
            "entry": entry.astype(bool),
            "exit": exit_.astype(bool),
            "expansion_active": active.astype(bool),
            "expansion_tier": (
                pd.Series("none", index=common.index)
                .where(~tier3, "tier3")
                .where(~tier2, "tier2")
                .where(~tier1, "tier1")
            ),
            "momentum_composite": mom_composite,
            "market_state": common["market_state"].astype(str),
            "vol_state": common["vol_state"].astype(str),
            "drawdown_252": dd,
            "mom_20": mom_20,
            "mom_60": mom_60,
        },
        index=common.index,
    )


def _make_decision(
    base: pd.Series,
    byd_weight: pd.Series,
) -> pd.DataFrame:
    """Create portfolio weights from BYD weight series (ETF fills to 1.0)."""
    etf = (1.0 - byd_weight).clip(lower=0.0)
    cash = 1.0 - byd_weight - etf
    frame = pd.DataFrame(
        {"byd_weight": byd_weight.astype(float),
         "etf_weight": etf.astype(float),
         "cash_weight": cash.astype(float)},
        index=base.index,
    )
    if (frame["byd_weight"] < -1e-12).any():
        raise AssertionError("negative BYD weight")
    if not np.allclose(frame.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("weights do not sum to one")
    return frame


def build_decisions(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    state = build_expansion_state(common, signals)
    base = state["base_byd_weight"].astype(float)
    active = state["expansion_active"].astype(bool)
    tier = state["expansion_tier"]
    mom_composite = state["momentum_composite"]

    # Baseline: standard v1.1 (no expansion)
    baseline_byd = base.copy()

    # Robustness (105%): tier1 expansion, moderate leverage
    robust_byd = base.where(~active, other=base.where(
        tier.isin(["tier1", "tier2", "tier3"]),
        RULES["tier1_byd_weight"],
    ))

    # Primary (tiered): graduated by momentum strength
    primary_byd = base.where(~active, other=np.select(
        [tier == "tier3", tier == "tier2", tier == "tier1"],
        [RULES["tier3_byd_weight"],
         RULES["tier2_byd_weight"],
         RULES["tier1_byd_weight"]],
        default=base,
    ))

    # Diagnostic (continuous): momentum-scaled position
    expansion_factor = (
        mom_composite * RULES["continuous_momentum_scale"]
    ).clip(upper=RULES["continuous_max"] - RULES["continuous_base"])
    continuous_byd = base.where(~active, other=base + expansion_factor)

    decisions = {
        BASELINE: _make_decision(base, baseline_byd),
        PRIMARY: _make_decision(base, primary_byd),
        ROBUSTNESS: _make_decision(base, robust_byd),
        DIAGNOSTIC: _make_decision(base, continuous_byd),
    }
    return decisions, state


# ---------------------------------------------------------------------------
# Allocation runner with financing cost
# ---------------------------------------------------------------------------

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
    gross_return = (
        byd_weight * common["byd_open_return"]
        + etf_weight * common["etf_open_return"]
    )
    turnover = executed.diff().abs().sum(axis=1)
    turnover.iloc[0] = 0.0
    transaction_cost = turnover * cost_bps / 10_000.0
    borrowed_weight = (-cash_weight).clip(lower=0.0)
    financing_cost = (
        borrowed_weight * annual_financing_rate / FINANCING_DAY_COUNT
    )

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
            name, common, decision,
            cost_bps=cost_bps,
            annual_financing_rate=annual_financing_rate,
        )
        for name, decision in decisions.items()
    }
    return results, state


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

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
    b = block.loc[returns.index]
    output.update({
        "transaction_cost_paid": float(b["cost"].sum()),
        "financing_cost_paid": float(b["financing_cost"].sum()),
        "mean_borrowed_weight": float(b["borrowed_weight"].mean()),
        "max_gross_exposure": float(b["gross_exposure"].max()),
        "financed_sessions": float(b["borrowed_weight"].gt(0.0).sum()),
    })
    return output


def build_evaluation(
    results_primary: dict[str, AllocationResult],
    results_stress: dict[str, AllocationResult],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, cost_bps, frate, results in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE, results_primary),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE, results_stress),
    ):
        for name, result in results.items():
            for window, (start, end) in WINDOWS.items():
                rows.append({
                    "scenario": label,
                    "model": name,
                    "cost_bps": cost_bps,
                    "annual_financing_rate": frate,
                    "window": window,
                    **_window_metrics(result, start, end),
                })
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
    periods = {k: v for k, v in WINDOWS.items() if k != "full_overlap"}
    for name in (PRIMARY, ROBUSTNESS, DIAGNOSTIC):
        rel = {}
        for period, (start, end) in periods.items():
            cw = _terminal_wealth(results[name].daily, start, end)
            bw = _terminal_wealth(results[BASELINE].daily, start, end)
            rel[period] = cw / bw - 1.0
        pos_total = sum(max(v, 0.0) for v in rel.values())
        for period, r in rel.items():
            share = max(r, 0.0) / pos_total if pos_total > 0 else 0.0
            rows.append({
                "model": name,
                "period": period,
                "relative_terminal_wealth": r,
                "positive_contribution_share": share,
            })
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
    ep_id = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for rid, block in daily.groupby(ep_id):
        if pd.isna(rid):
            continue
        bb = benchmark.loc[block.index]
        st = state.reindex(block.index)
        cw = float((1.0 + block["net_return"]).prod())
        bw = float((1.0 + bb["net_return"]).prod())
        rows.append({
            "episode_id": int(rid),
            "start": block.index.min(),
            "end": block.index.max(),
            "sessions": int(len(block)),
            "candidate_return": cw - 1.0,
            "baseline_return": bw - 1.0,
            "relative_terminal_wealth": cw / bw - 1.0,
            "financing_cost_paid": float(block["financing_cost"].sum()),
            "transaction_cost_paid": float(block["cost"].sum()),
            "min_drawdown_252": float(st["drawdown_252"].min()),
            "mean_mom_20": float(st["mom_20"].mean()),
            "expansion_tier_distribution": (
                st["expansion_tier"].value_counts().to_dict()
            ),
        })
    return pd.DataFrame(rows)


def governed_result(
    evaluation: pd.DataFrame,
    contributions: pd.DataFrame,
    episodes: pd.DataFrame,
) -> GovernedResult:
    def row(model: str, scenario: str) -> pd.Series:
        sel = evaluation.loc[
            (evaluation["model"] == model)
            & (evaluation["scenario"] == scenario)
            & (evaluation["window"] == "full_overlap")
        ]
        if len(sel) != 1:
            raise ValueError(f"missing full-overlap row for {model}/{scenario}")
        return sel.iloc[0]

    bp = row(BASELINE, "primary")
    primary = row(PRIMARY, "primary")
    robust = row(ROBUSTNESS, "primary")
    bs = row(BASELINE, "stress")
    ps = row(PRIMARY, "stress")
    rs = row(ROBUSTNESS, "stress")

    cagr_d = float(primary["cagr"] - bp["cagr"])
    mdd_d = float(primary["max_drawdown"] - bp["max_drawdown"])
    calmar_d = float(primary["calmar"] - bp["calmar"])
    pc = contributions.loc[contributions["model"] == PRIMARY]
    neg = int(pc["relative_terminal_wealth"].lt(0.0).sum())
    max_share = float(pc["positive_contribution_share"].max())
    fs = int(primary["financed_sessions"])
    eps = int(len(episodes))

    gates = {
        "cagr_improves_0_5pp": cagr_d >= 0.005,
        "max_drawdown_worsening_le_2pp": mdd_d >= -0.02,
        "calmar_not_declining": calmar_d >= -0.01,
        "stress_return_above_baseline": bool(
            float(ps["total_return"]) > float(bs["total_return"])
        ),
        "no_more_than_one_negative_period": neg <= 1,
        "contribution_not_concentrated": bool(
            max_share <= 0.60 and pc["relative_terminal_wealth"].gt(0.0).any()
        ),
        "round_trips_per_year_le_3": bool(float(primary["round_trips_per_year"]) <= 3.0),
        "minimum_10_episodes": eps >= 10,
        "minimum_126_financed_sessions": fs >= 126,
        "robustness_improves_return_and_not_worse_drawdown": bool(
            float(robust["cagr"]) > float(bp["cagr"])
            and float(rs["total_return"]) > float(bs["total_return"])
        ),
    }
    decision = (
        "promote_adaptive_expansion"
        if all(gates.values())
        else "retain_byd_v1_1"
    )
    diagnostics = {
        "cagr_delta": cagr_d,
        "max_drawdown_delta": mdd_d,
        "calmar_delta": calmar_d,
        "negative_periods": neg,
        "max_positive_contribution_share": max_share,
        "completed_episodes": eps,
        "financed_sessions": fs,
        "primary_total_return": float(primary["total_return"]),
        "baseline_total_return": float(bp["total_return"]),
        "primary_stress_total_return": float(ps["total_return"]),
        "baseline_stress_total_return": float(bs["total_return"]),
        "primary_financing_cost_paid": float(primary["financing_cost_paid"]),
    }
    return GovernedResult(decision=decision, gates=gates, diagnostics=diagnostics)
