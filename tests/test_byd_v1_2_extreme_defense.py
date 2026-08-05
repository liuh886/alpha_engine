from __future__ import annotations

import pandas as pd

from src.research.byd_515180_allocation import PRIMARY_COST_BPS, STRESS_COST_BPS
from src.research.byd_v1_2_extreme_defense import (
    BASELINE,
    PRIMARY,
    ROBUSTNESS,
    build_decisions,
    governed_result,
)


def test_extreme_state_is_stateful_and_preserves_declared_weights() -> None:
    index = pd.date_range("2026-01-01", periods=7, freq="D")
    common = pd.DataFrame(
        {
            "market_state": ["sideways", "bear", "bear", "bear", "bear", "bear", "bull"],
            "vol_state": ["low", "high", "high", "high", "high", "low", "low"],
            "drawdown_252": [-0.10, -0.21, -0.25, -0.24, -0.22, -0.18, -0.05],
            "mom_20": [-0.01, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03],
            "mom_60": [-0.01, -0.04, -0.05, -0.03, -0.02, -0.01, 0.02],
        },
        index=index,
    )
    signals = pd.DataFrame(
        {"base_byd_weight": [0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 1.0]},
        index=index,
    )

    decisions, state = build_decisions(common, signals)

    assert state["extreme_defense_active"].tolist() == [
        False,
        True,
        True,
        True,
        False,
        False,
        False,
    ]
    assert decisions[BASELINE].loc[index[2]].to_dict() == {
        "byd_weight": 0.75,
        "etf_weight": 0.25,
        "cash_weight": 0.0,
    }
    assert decisions[PRIMARY].loc[index[2]].to_dict() == {
        "byd_weight": 0.50,
        "etf_weight": 0.50,
        "cash_weight": 0.0,
    }
    assert decisions[ROBUSTNESS].loc[index[2]].to_dict() == {
        "byd_weight": 0.625,
        "etf_weight": 0.375,
        "cash_weight": 0.0,
    }
    for decision in decisions.values():
        assert (decision >= 0.0).all().all()
        assert decision.sum(axis=1).round(12).eq(1.0).all()


def test_governance_requires_all_frozen_gates() -> None:
    evaluation = pd.DataFrame(
        [
            {
                "model": BASELINE,
                "cost_bps": PRIMARY_COST_BPS,
                "window": "full_overlap",
                "cagr": 0.350,
                "total_return": 5.80,
                "max_drawdown": -0.49,
                "calmar": 0.71,
                "round_trips_per_year": 1.0,
            },
            {
                "model": PRIMARY,
                "cost_bps": PRIMARY_COST_BPS,
                "window": "full_overlap",
                "cagr": 0.356,
                "total_return": 6.05,
                "max_drawdown": -0.45,
                "calmar": 0.79,
                "round_trips_per_year": 1.5,
            },
            {
                "model": ROBUSTNESS,
                "cost_bps": PRIMARY_COST_BPS,
                "window": "full_overlap",
                "cagr": 0.353,
                "total_return": 5.95,
                "max_drawdown": -0.47,
                "calmar": 0.75,
                "round_trips_per_year": 1.3,
            },
            {
                "model": BASELINE,
                "cost_bps": STRESS_COST_BPS,
                "window": "full_overlap",
                "cagr": 0.340,
                "total_return": 5.50,
                "max_drawdown": -0.50,
                "calmar": 0.68,
                "round_trips_per_year": 1.0,
            },
            {
                "model": PRIMARY,
                "cost_bps": STRESS_COST_BPS,
                "window": "full_overlap",
                "cagr": 0.345,
                "total_return": 5.65,
                "max_drawdown": -0.46,
                "calmar": 0.75,
                "round_trips_per_year": 1.5,
            },
        ]
    )
    contributions = pd.DataFrame(
        [
            {
                "model": PRIMARY,
                "period": "development",
                "relative_terminal_wealth": 0.02,
                "positive_contribution_share": 0.40,
            },
            {
                "model": PRIMARY,
                "period": "fixed_validation",
                "relative_terminal_wealth": 0.015,
                "positive_contribution_share": 0.30,
            },
            {
                "model": PRIMARY,
                "period": "retrospective_2025_plus",
                "relative_terminal_wealth": 0.015,
                "positive_contribution_share": 0.30,
            },
        ]
    )

    result = governed_result(evaluation, contributions)

    assert result.decision == "promote_byd_v1_2_candidate"
    assert all(result.gates.values())
