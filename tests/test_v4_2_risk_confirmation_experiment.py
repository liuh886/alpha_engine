from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_risk_confirmation_experiment import (
    confirmation_research_gate,
    confirmed_execution_states,
    fixed_execution_delay_states,
    run_confirmation_comparison,
)
from src.research.vxn_bridge_allocation_experiment import (
    bridge_weights_for_states,
)


def _contract() -> dict:
    return {
        "portfolio": {
            "state_0": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
            "state_1_bridge": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
            "state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75},
            "transaction_cost_bps_per_turnover_unit": 10.0,
            "annual_risk_free_rate": 0.0,
            "charge_initial_entry": True,
        },
        "promotion_gate": {
            "max_drawdown_worsening_tolerance": 0.005,
            "min_positive_event_rate": 0.60,
            "max_top_positive_event_share": 0.50,
        },
    }


def _result() -> StrategyResult:
    index = pd.date_range("2026-01-02", periods=14, freq="B")
    decisions = pd.Series(
        [1, 2, 2, 1, 0, 1, 1, 2, 2, 1, 0, 1, 2, 2],
        index=index,
    )
    states = decisions.shift(1).fillna(0).astype(int)
    frame = pd.DataFrame(
        {
            "decision_state": decisions,
            "decision_reason": ["rule"] * len(index),
        },
        index=index,
    )
    weights = bridge_weights_for_states(states, _contract())
    returns = {
        "QQQI": [0.001] * len(index),
        "QQQ": [
            0.002,
            -0.010,
            -0.030,
            0.010,
            0.001,
            0.002,
            0.004,
            -0.020,
            0.015,
            0.005,
            0.001,
            0.003,
            -0.025,
            0.020,
        ],
        "TQQQ": [
            0.003,
            -0.030,
            -0.090,
            0.030,
            0.002,
            0.004,
            0.012,
            -0.060,
            0.045,
            0.015,
            0.002,
            0.009,
            -0.075,
            0.060,
        ],
    }
    for asset in ("QQQI", "QQQ", "TQQQ"):
        frame[f"weight_{asset}"] = weights[asset]
        frame[f"{asset}_next_open_return"] = returns[asset]
    frame["position_state"] = states
    frame["position_label"] = states.map(
        {0: "defensive", 1: "attack", 2: "partial_leverage"}
    )
    frame["gross_return"] = sum(
        frame[f"weight_{asset}"] * frame[f"{asset}_next_open_return"]
        for asset in ("QQQI", "QQQ", "TQQQ")
    )
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = weights.iloc[0].abs().sum()
    frame["turnover_units"] = turnover
    frame["transaction_cost"] = turnover * 10.0 / 10_000.0
    frame["net_return"] = frame["gross_return"] - frame["transaction_cost"]
    return StrategyResult(
        "baseline",
        frame,
        pd.DataFrame(),
        {"strategy": "rotation_vxn_bridge_v4_2_50_50"},
    )


def test_fixed_delay_differs_from_persistence_confirmation() -> None:
    decisions = pd.Series([1, 2, 2, 1, 0, 1])
    fixed = fixed_execution_delay_states(decisions, sessions=1)
    confirmed = confirmed_execution_states(
        decisions, mode="risk_increase_confirmation_1"
    )
    assert fixed.tolist() == [0, 0, 1, 2, 2, 1]
    assert confirmed.tolist() != fixed.tolist()


def test_bridge_and_leverage_confirmations_are_isolated() -> None:
    decisions = pd.Series([1, 1, 2, 2, 1])
    bridge = confirmed_execution_states(
        decisions, mode="bridge_entry_confirmation_1"
    )
    leverage = confirmed_execution_states(
        decisions, mode="leverage_entry_confirmation_1"
    )
    assert bridge.tolist() == [0, 0, 1, 2, 2]
    assert leverage.tolist() == [0, 1, 1, 1, 2]


def test_comparison_reproduces_baseline_and_attributes_events() -> None:
    metrics, segments, events, results = run_confirmation_comparison(
        _result(),
        _contract(),
        train_fraction=0.60,
    )
    np.testing.assert_allclose(
        results["baseline"].daily["net_return"],
        _result().daily["net_return"],
        atol=1e-12,
        rtol=0.0,
    )
    assert {
        "fixed_execution_delay_1",
        "bridge_entry_confirmation_1",
        "leverage_entry_confirmation_1",
        "risk_increase_confirmation_1",
    } <= set(metrics.index)
    assert set(segments["segment"]) == {"early", "late"}
    assert set(events["scenario"]) == {
        "bridge_entry_confirmation_1",
        "leverage_entry_confirmation_1",
        "risk_increase_confirmation_1",
    }


def test_gate_never_authorizes_direct_promotion() -> None:
    metrics, segments, events, _ = run_confirmation_comparison(
        _result(),
        _contract(),
        train_fraction=0.60,
    )
    gate = confirmation_research_gate(
        metrics,
        segments,
        events,
        _contract(),
    )
    assert gate["promotion_authorized"] is False
    assert gate["next_direction"] in {
        "open_separate_prospective_confirmation_challenger",
        "retain_v4_2_and_reject_confirmation_challenger",
    }
