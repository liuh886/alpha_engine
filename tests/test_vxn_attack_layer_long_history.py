from __future__ import annotations

import pandas as pd

from src.research.vix_rotation_experiment import VixRotationConfig
from src.research.vxn_attack_layer_long_history import _run_attack_backtest


def _prepared() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=6, freq="B")
    return pd.DataFrame(
        {
            "QQQ_next_open_return": [0.01, 0.01, -0.01, 0.02, -0.02, 0.01],
            "TQQQ_next_open_return": [0.03, 0.03, -0.03, 0.06, -0.06, 0.03],
            "vix_close": [20.0] * 6,
            "vxn_close": [25.0] * 6,
            "vix_regime": ["normal"] * 6,
            "vxn_regime": ["normal"] * 6,
        },
        index=index,
    )


def test_source_states_zero_and_one_both_hold_qqq() -> None:
    decisions = pd.DataFrame(
        {
            "decision_state": [0, 1, 1, 0, 1, 1],
            "decision_reason": ["hold"] * 6,
        },
        index=_prepared().index,
    )
    result = _run_attack_backtest(
        _prepared(),
        decisions,
        VixRotationConfig(leveraged_tqqq_weight=0.75),
        strategy_key="test",
        display_name="test",
    )
    assert result.daily["weight_TQQQ"].eq(0.0).all()
    assert result.daily["weight_QQQ"].eq(1.0).all()


def test_source_state_two_uses_frozen_75_percent_tqqq() -> None:
    decisions = pd.DataFrame(
        {
            "decision_state": [0, 2, 2, 1, 2, 2],
            "decision_reason": ["hold", "enter", "hold", "exit", "enter", "hold"],
        },
        index=_prepared().index,
    )
    result = _run_attack_backtest(
        _prepared(),
        decisions,
        VixRotationConfig(leveraged_tqqq_weight=0.75),
        strategy_key="test",
        display_name="test",
    )
    leveraged = result.daily["position_state"].eq(1)
    assert result.daily.loc[leveraged, "weight_TQQQ"].eq(0.75).all()
    assert result.daily.loc[leveraged, "weight_QQQ"].eq(0.25).all()


def test_cost_change_does_not_change_position_trace() -> None:
    decisions = pd.DataFrame(
        {
            "decision_state": [0, 2, 2, 1, 2, 2],
            "decision_reason": ["hold", "enter", "hold", "exit", "enter", "hold"],
        },
        index=_prepared().index,
    )
    low = _run_attack_backtest(
        _prepared(),
        decisions,
        VixRotationConfig(
            leveraged_tqqq_weight=0.75,
            transaction_cost_bps_per_turnover_unit=10.0,
        ),
        strategy_key="low",
        display_name="low",
    )
    high = _run_attack_backtest(
        _prepared(),
        decisions,
        VixRotationConfig(
            leveraged_tqqq_weight=0.75,
            transaction_cost_bps_per_turnover_unit=50.0,
        ),
        strategy_key="high",
        display_name="high",
    )
    pd.testing.assert_series_equal(
        low.daily["position_state"], high.daily["position_state"], check_names=False
    )
    assert high.metrics["transaction_cost_paid"] > low.metrics["transaction_cost_paid"]
