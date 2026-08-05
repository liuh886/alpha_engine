"""Frozen trend-guard experiment for the BYD V1.0 515180 sleeve.

The BYD V1.0 75% / 100% risk budget is immutable. Only the released defensive
25% is split between 515180 and cash. Signals use the current close and execute
at the next independently confirmed common open through the existing engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    WINDOWS,
    AllocationResult,
    metrics,
    prepare_common_dataset,
)
from src.research.byd_515180_execution import run_allocation
from src.research.byd_defensive_sleeve_governance import relative_terminal_return

MODELS = (
    "v1_dividend_75_25",
    "v1_dividend_ma200_soft",
    "v1_dividend_ma120_soft",
    "v1_dividend_ma200_hard",
)
PRIMARY = "v1_dividend_ma200_soft"
ROBUSTNESS = "v1_dividend_ma120_soft"


@dataclass(frozen=True)
class TrendGuardInputs:
    byd_dir: Path
    etf_dir: Path


def trend_positive(close: pd.Series, window: int) -> pd.Series:
    """Return a close-based long-term trend flag with baseline warm-up.

    Before a complete moving-average window exists, the baseline full sleeve is
    retained. This prevents missing pre-listing history from becoming a hidden
    bearish signal.
    """

    average = close.rolling(window=window, min_periods=window).mean()
    return average.isna() | close.ge(average)


def _weights(
    base: pd.Series,
    trend: pd.Series,
    *,
    below_trend_etf_weight: float,
) -> pd.DataFrame:
    if not base.index.equals(trend.index):
        raise ValueError("base and trend indices must align")
    defense = base.eq(0.75)
    etf = pd.Series(0.0, index=base.index, dtype=float)
    etf.loc[defense & trend] = 0.25
    etf.loc[defense & ~trend] = below_trend_etf_weight
    cash = 1.0 - base - etf
    frame = pd.DataFrame(
        {"byd_weight": base.astype(float), "etf_weight": etf, "cash_weight": cash},
        index=base.index,
    )
    if (frame < -1e-12).any().any() or not np.allclose(frame.sum(axis=1), 1.0):
        raise AssertionError("trend guard produced invalid weights")
    return frame


def build_trend_guard_decisions(
    common: pd.DataFrame,
    signals: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    base = signals["base_byd_weight"].astype(float)
    close = common["etf_close"].astype(float)
    ma120 = trend_positive(close, 120)
    ma200 = trend_positive(close, 200)

    baseline = _weights(base, pd.Series(True, index=base.index), below_trend_etf_weight=0.25)
    decisions = {
        "v1_dividend_75_25": baseline,
        "v1_dividend_ma200_soft": _weights(
            base, ma200, below_trend_etf_weight=0.125
        ),
        "v1_dividend_ma120_soft": _weights(
            base, ma120, below_trend_etf_weight=0.125
        ),
        "v1_dividend_ma200_hard": _weights(
            base, ma200, below_trend_etf_weight=0.0
        ),
    }
    state = pd.DataFrame(
        {
            "etf_close": close,
            "ma120": close.rolling(120, min_periods=120).mean(),
            "ma200": close.rolling(200, min_periods=200).mean(),
            "ma120_positive": ma120,
            "ma200_positive": ma200,
            "v1_defense": base.eq(0.75),
        },
        index=common.index,
    )
    return decisions, state


def _window_metrics(result: AllocationResult, start: str, end: str) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise RuntimeError(f"empty evaluation window: {start} to {end}")
    return metrics(block)


def _period_contribution(evaluation: pd.DataFrame) -> pd.DataFrame:
    primary = evaluation.loc[evaluation["cost_bps"].eq(PRIMARY_COST_BPS)]
    rows: list[dict[str, Any]] = []
    windows = ("development", "fixed_validation", "retrospective_2025_plus")
    for model in MODELS[1:]:
        model_rows: list[dict[str, Any]] = []
        positive_total = 0.0
        for window in windows:
            candidate = primary.loc[
                primary["model"].eq(model) & primary["window"].eq(window)
            ].iloc[0]
            baseline = primary.loc[
                primary["model"].eq(MODELS[0]) & primary["window"].eq(window)
            ].iloc[0]
            relative = relative_terminal_return(
                float(candidate["total_return"]), float(baseline["total_return"])
            )
            positive_total += max(relative, 0.0)
            model_rows.append(
                {
                    "model": model,
                    "window": window,
                    "candidate_total_return": float(candidate["total_return"]),
                    "baseline_total_return": float(baseline["total_return"]),
                    "relative_terminal_return": relative,
                }
            )
        for row in model_rows:
            row["positive_contribution_share"] = (
                max(float(row["relative_terminal_return"]), 0.0) / positive_total
                if positive_total > 0.0
                else 1.0
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _govern(
    evaluation: pd.DataFrame,
    periods: pd.DataFrame,
) -> dict[str, Any]:
    full20 = evaluation.loc[
        evaluation["window"].eq("full_overlap")
        & evaluation["cost_bps"].eq(PRIMARY_COST_BPS)
    ].set_index("model")
    full40 = evaluation.loc[
        evaluation["window"].eq("full_overlap")
        & evaluation["cost_bps"].eq(STRESS_COST_BPS)
    ].set_index("model")
    baseline20 = full20.loc[MODELS[0]]
    baseline40 = full40.loc[MODELS[0]]
    primary20 = full20.loc[PRIMARY]
    primary40 = full40.loc[PRIMARY]
    robust20 = full20.loc[ROBUSTNESS]

    primary_periods = periods.loc[periods["model"].eq(PRIMARY)]
    validation = primary_periods.set_index("window")["relative_terminal_return"]
    risk_path = (
        float(primary20["max_drawdown"] - baseline20["max_drawdown"]) >= 0.015
        or float(primary20["calmar"] - baseline20["calmar"]) >= 0.02
    )
    robustness_direction = (
        float(robust20["max_drawdown"]) >= float(baseline20["max_drawdown"])
        or float(robust20["calmar"]) >= float(baseline20["calmar"])
    )
    gates = {
        "cagr_not_below_baseline_by_more_than_50bp": (
            float(primary20["cagr"] - baseline20["cagr"]) >= -0.005
        ),
        "drawdown_or_calmar_improvement": risk_path,
        "stress_total_not_below_baseline": (
            float(primary40["total_return"]) >= float(baseline40["total_return"])
        ),
        "validation_and_2025_not_both_negative": not (
            float(validation["fixed_validation"]) < 0.0
            and float(validation["retrospective_2025_plus"]) < 0.0
        ),
        "round_trips_at_most_3": float(primary20["round_trips_per_year"]) <= 3.0,
        "max_period_share_at_most_60pct": (
            float(primary_periods["positive_contribution_share"].max()) <= 0.60
        ),
        "ma120_robustness_same_direction": robustness_direction,
    }
    supported = all(gates.values())
    return {
        "schema_version": "byd_515180_trend_guard_v1",
        "issue": 554,
        "models": list(MODELS),
        "primary_candidate": PRIMARY,
        "robustness_candidate": ROBUSTNESS,
        "stress_candidate": "v1_dividend_ma200_hard",
        "gates": gates,
        "governed_decision": (
            "trend_guard_supported_historical"
            if supported
            else "retain_v1_dividend_75_25"
        ),
        "research_only": True,
        "trade_ready": False,
        "fresh_holdout": False,
    }


def run_trend_guard_screen(
    inputs: TrendGuardInputs,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    common, signals, _ = prepare_common_dataset(inputs.byd_dir, inputs.etf_dir)
    decisions, state = build_trend_guard_decisions(common, signals)

    results: dict[tuple[str, float], AllocationResult] = {}
    for cost in (PRIMARY_COST_BPS, STRESS_COST_BPS):
        for model, decision in decisions.items():
            results[(model, cost)] = run_allocation(
                model, common, decision, cost_bps=cost
            )

    rows: list[dict[str, Any]] = []
    for (model, cost), result in results.items():
        for window, (start, end) in WINDOWS.items():
            rows.append(
                {
                    "model": model,
                    "cost_bps": cost,
                    "window": window,
                    **_window_metrics(result, start, end),
                }
            )
    evaluation = pd.DataFrame(rows)
    periods = _period_contribution(evaluation)

    defense = state["v1_defense"]
    diagnostics = pd.DataFrame(
        [
            {
                "measure": "common_sessions",
                "value": float(len(common)),
            },
            {
                "measure": "common_eligible_opens",
                "value": float(common["common_open_eligible"].sum()),
            },
            {
                "measure": "defense_sessions",
                "value": float(defense.sum()),
            },
            {
                "measure": "defense_below_ma200_sessions",
                "value": float((defense & ~state["ma200_positive"]).sum()),
            },
            {
                "measure": "defense_below_ma120_sessions",
                "value": float((defense & ~state["ma120_positive"]).sum()),
            },
            {
                "measure": "ma200_signal_transitions",
                "value": float(state["ma200_positive"].ne(state["ma200_positive"].shift()).sum() - 1),
            },
            {
                "measure": "ma120_signal_transitions",
                "value": float(state["ma120_positive"].ne(state["ma120_positive"].shift()).sum() - 1),
            },
        ]
    )
    summary = _govern(evaluation, periods)
    summary.update(
        {
            "overlap_start": str(common.index.min().date()),
            "cutoff": str(common.index.max().date()),
            "execution": "prior_close_decision_next_common_eligible_open",
            "warmup_policy": "retain_full_25pct_etf_sleeve_until_ma_available",
        }
    )
    return evaluation, periods, diagnostics, summary
