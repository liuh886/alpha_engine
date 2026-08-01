from __future__ import annotations

import pandas as pd

from src.research.absolute_breadth_scaling_experiment import (
    _run_scaled_attack_backtest,
    build_absolute_breadth_features,
)
from src.research.vix_rotation_experiment import VixRotationConfig


def test_absolute_breadth_uses_own_trend_not_relative_strength() -> None:
    index = pd.date_range("2024-01-01", periods=25, freq="B")
    bars = pd.DataFrame(
        {
            "date": index,
            "close": [100.0 + value for value in range(25)],
        }
    )
    features = build_absolute_breadth_features(
        bars, ma_window=20, momentum_sessions=5
    )
    assert "qqqe_qqq_ratio" not in features.columns
    assert features["absolute_breadth_confirmed"].iloc[-1]


def _prepared() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=6, freq="B")
    return pd.DataFrame(
        {
            "QQQ_next_open_return": [0.01, 0.01, -0.01, 0.02, -0.02, 0.01],
            "TQQQ_next_open_return": [0.03, 0.03, -0.03, 0.06, -0.06, 0.03],
            "absolute_breadth_confirmed": [False, False, True, True, False, True],
            "qqqe_close": [100.0] * 6,
            "qqqe_ma": [99.0] * 6,
            "qqqe_momentum": [0.01] * 6,
        },
        index=index,
    )


def test_soft_scaling_preserves_decisions_and_uses_50_75_schedule() -> None:
    prepared = _prepared()
    decisions = pd.DataFrame(
        {
            "decision_state": [2, 2, 2, 2, 1, 1],
            "decision_reason": ["entry", "hold", "hold", "hold", "exit", "hold"],
        },
        index=prepared.index,
    )
    result = _run_scaled_attack_backtest(
        prepared,
        decisions,
        VixRotationConfig(leveraged_tqqq_weight=0.75),
        strategy_key="soft",
        display_name="soft",
        weak_tqqq_weight=0.50,
        confirmed_tqqq_weight=0.75,
        dynamic_breadth=True,
    )
    assert result.daily["source_position_state"].tolist() == [0, 2, 2, 2, 2, 1]
    assert result.daily["weight_TQQQ"].tolist() == [0.0, 0.5, 0.5, 0.75, 0.75, 0.0]


def test_fixed_baseline_always_uses_75_percent_when_leveraged() -> None:
    prepared = _prepared()
    decisions = pd.DataFrame(
        {
            "decision_state": [2, 2, 2, 2, 1, 1],
            "decision_reason": ["entry", "hold", "hold", "hold", "exit", "hold"],
        },
        index=prepared.index,
    )
    result = _run_scaled_attack_backtest(
        prepared,
        decisions,
        VixRotationConfig(leveraged_tqqq_weight=0.75),
        strategy_key="fixed",
        display_name="fixed",
        weak_tqqq_weight=0.75,
        confirmed_tqqq_weight=0.75,
        dynamic_breadth=False,
    )
    leveraged = result.daily["position_state"].eq(1)
    assert result.daily.loc[leveraged, "weight_TQQQ"].eq(0.75).all()
