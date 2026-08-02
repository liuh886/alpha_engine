from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_state2_tail_experiment import (
    _delayed_execution_states,
    execution_robustness_comparison,
    open_to_open_contribution_decomposition,
    state_two_episode_attribution,
    state_two_research_gate,
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
        "research_gate": {
            "max_overnight_loss_share": 0.50,
            "min_previous_close_warning_rate": 0.50,
            "min_gradual_episode_rate": 0.50,
            "max_risk_reduction_delay_cagr_delta": -0.03,
        },
    }


def _result() -> StrategyResult:
    index = pd.date_range("2026-01-02", periods=10, freq="B")
    decisions = pd.Series([1, 2, 2, 2, 1, 2, 2, 1, 0, 1], index=index)
    states = decisions.shift(1).fillna(0).astype(int)
    frame = pd.DataFrame(
        {
            "decision_state": decisions,
            "decision_reason": ["rule"] * len(index),
            "executed_reason": ["rule"] * len(index),
            "vix_close": [18.0] * len(index),
            "vxn_close": [24.0] * len(index),
            "vix_stress": [False] * len(index),
            "vxn_stress": [
                False,
                False,
                False,
                True,
                False,
                False,
                True,
                False,
                False,
                False,
            ],
            "below_ma_short_n": [False] * len(index),
            "ma_short": [100.0] * len(index),
        },
        index=index,
    )
    weights = bridge_weights_for_states(states, _contract())
    returns = {
        "QQQI": [0.001] * len(index),
        "QQQ": [
            0.002,
            0.003,
            -0.010,
            -0.025,
            0.010,
            0.004,
            -0.030,
            0.020,
            0.001,
            0.002,
        ],
        "TQQQ": [
            0.003,
            0.005,
            -0.030,
            -0.075,
            0.030,
            0.006,
            -0.090,
            0.060,
            0.002,
            0.004,
        ],
    }
    for asset in ("QQQI", "QQQ", "TQQQ"):
        frame[f"weight_{asset}"] = weights[asset]
        frame[f"{asset}_open"] = 100.0
        frame[f"{asset}_next_open_return"] = returns[asset]
        frame[f"{asset}_close"] = [
            100.0 * (1.0 + value * 0.40) for value in returns[asset]
        ]
    frame["QQQ_close"] = 99.0
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
    frame["equity"] = (1.0 + frame["net_return"]).cumprod()
    frame["drawdown"] = frame["equity"] / frame["equity"].cummax() - 1.0
    return StrategyResult(
        "test",
        frame,
        pd.DataFrame(),
        {"strategy": "rotation_vxn_bridge_v4_2_50_50"},
    )


def test_open_to_open_decomposition_ties_to_gross_return() -> None:
    result = _result()
    decomposed = open_to_open_contribution_decomposition(result.daily)
    np.testing.assert_allclose(
        decomposed["reconstructed_gross_return"],
        result.daily["gross_return"],
        atol=1e-12,
        rtol=0.0,
    )


def test_state_two_episodes_capture_gap_and_warning_mechanics() -> None:
    episodes, summary, tail_days = state_two_episode_attribution(
        _result(),
        top_n=4,
    )
    assert len(episodes) == 2
    assert int(summary.iloc[0]["episodes"]) == 2
    assert set(episodes["tail_mechanism"]) <= {
        "abrupt_or_gap_dominated",
        "gradual_or_distributed",
    }
    assert len(tail_days) == 4
    assert {
        "intraday_contribution",
        "overnight_contribution",
        "previous_close_warning",
        "same_close_exit_signal",
    } <= set(tail_days.columns)


def test_delay_modes_only_delay_selected_transition_direction() -> None:
    decisions = pd.Series([1, 2, 2, 1, 0, 1])
    baseline = _delayed_execution_states(decisions, mode="baseline")
    risk_up = _delayed_execution_states(
        decisions, mode="risk_increase_delay_1"
    )
    risk_down = _delayed_execution_states(
        decisions, mode="risk_reduction_delay_1"
    )
    assert baseline.tolist() == [0, 1, 2, 2, 1, 0]
    assert risk_up.iloc[1] == 0
    assert risk_up.iloc[3] == 2
    assert risk_down.iloc[1] == 1
    assert risk_down.iloc[4] == 2


def test_execution_baseline_reproduces_frozen_v4_2() -> None:
    table, scenarios = execution_robustness_comparison(
        _result(), _contract()
    )
    assert scenarios["baseline"].daily["position_state"].equals(
        _result().daily["position_state"]
    )
    np.testing.assert_allclose(
        scenarios["baseline"].daily["net_return"],
        _result().daily["net_return"],
        atol=1e-12,
        rtol=0.0,
    )
    assert {
        "all_transitions_delay_1",
        "risk_increase_delay_1",
        "risk_reduction_delay_1",
        "baseline_plus_20bps",
    } <= set(table.index)


def test_research_gate_blocks_gap_dominated_tail() -> None:
    episode_summary = pd.DataFrame(
        [{"abrupt_or_gap_dominated_rate": 0.75}]
    )
    tail_days = pd.DataFrame(
        {
            "intraday_contribution": [-0.01, -0.01],
            "overnight_contribution": [-0.03, -0.02],
            "previous_close_warning": [True, True],
            "same_close_exit_signal": [False, True],
        }
    )
    execution = pd.DataFrame(
        {
            "cagr_delta_vs_baseline": [0.0, -0.01],
        },
        index=["baseline", "risk_reduction_delay_1"],
    )
    gate = state_two_research_gate(
        episode_summary, tail_days, execution, _contract()
    )
    assert gate[
        "eligible_for_continuous_state2_volatility_budget"
    ] is False
    assert "gap_risk" in gate["next_direction"]
