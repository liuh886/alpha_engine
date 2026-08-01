from __future__ import annotations

import pandas as pd

from src.research.vix_rotation_experiment import VixRotationConfig
from src.research.vxn_bridge_allocation_experiment import (
    bridge_weights_for_states,
    run_bridge_state_backtest,
)


def _contract() -> dict[str, object]:
    return {
        "portfolio": {
            "state_0": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
            "state_1_bridge": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
            "state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75},
        }
    }


def test_bridge_weights_are_exact_and_sum_to_one() -> None:
    states = pd.Series(
        [0, 1, 2],
        index=pd.bdate_range("2024-01-02", periods=3),
    )
    weights = bridge_weights_for_states(states, _contract())
    assert weights.loc[states.index[0]].to_dict() == {
        "QQQI": 1.0,
        "QQQ": 0.0,
        "TQQQ": 0.0,
    }
    assert weights.loc[states.index[1]].to_dict() == {
        "QQQI": 0.5,
        "QQQ": 0.5,
        "TQQQ": 0.0,
    }
    assert weights.loc[states.index[2]].to_dict() == {
        "QQQI": 0.0,
        "QQQ": 0.25,
        "TQQQ": 0.75,
    }
    assert weights.sum(axis=1).eq(1.0).all()


def test_bridge_backtest_preserves_shifted_state_trace() -> None:
    index = pd.bdate_range("2024-01-02", periods=6)
    prepared = pd.DataFrame(
        {
            "QQQI_next_open_return": [0.0, 0.001, 0.002, -0.001, 0.001, 0.0],
            "QQQ_next_open_return": [0.0, 0.002, 0.004, -0.002, 0.002, 0.0],
            "TQQQ_next_open_return": [0.0, 0.006, 0.012, -0.006, 0.006, 0.0],
            "vix_close": [15.0] * 6,
            "vix_regime": ["normal"] * 6,
            "vxn_close": [20.0] * 6,
            "vxn_regime": ["normal"] * 6,
        },
        index=index,
    )
    decisions = pd.DataFrame(
        {
            "decision_state": [0, 1, 2, 1, 0, 0],
            "decision_reason": [
                "hold",
                "enter_bridge",
                "enter_leverage",
                "exit_leverage",
                "defense",
                "hold",
            ],
        },
        index=index,
    )
    result = run_bridge_state_backtest(
        prepared,
        VixRotationConfig(leveraged_tqqq_weight=0.75),
        decisions,
        _contract(),
    )
    assert result.daily["position_state"].tolist() == [0, 0, 1, 2, 1, 0]
    bridge_row = result.daily.loc[index[2]]
    assert bridge_row["weight_QQQI"] == 0.5
    assert bridge_row["weight_QQQ"] == 0.5
    assert bridge_row["weight_TQQQ"] == 0.0
    leveraged_row = result.daily.loc[index[3]]
    assert leveraged_row["weight_QQQI"] == 0.0
    assert leveraged_row["weight_QQQ"] == 0.25
    assert leveraged_row["weight_TQQQ"] == 0.75


def test_bridge_reduces_turnover_for_same_state_sequence() -> None:
    states = pd.Series(
        [0, 1, 2, 1, 0],
        index=pd.bdate_range("2024-01-02", periods=5),
    )
    bridge = bridge_weights_for_states(states, _contract())
    bridge_turnover = bridge.diff().abs().sum(axis=1)
    bridge_turnover.iloc[0] = bridge.iloc[0].abs().sum()

    baseline = pd.DataFrame(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.25, 0.75],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
        index=states.index,
        columns=["QQQI", "QQQ", "TQQQ"],
    )
    baseline_turnover = baseline.diff().abs().sum(axis=1)
    baseline_turnover.iloc[0] = baseline.iloc[0].abs().sum()

    assert bridge_turnover.sum() == 6.0
    assert baseline_turnover.sum() == 8.0
    assert bridge_turnover.sum() < baseline_turnover.sum()
