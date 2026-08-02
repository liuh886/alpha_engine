from __future__ import annotations

import pandas as pd
import pytest

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_baseline_diagnostics import (
    state_one_lifecycle_attribution,
    tail_risk_metrics,
)


def _result(key: str, states: list[int], returns: list[float], turnover: list[float]) -> StrategyResult:
    index = pd.date_range("2026-01-02", periods=len(states), freq="B")
    daily = pd.DataFrame(
        {
            "position_state": states,
            "gross_return": returns,
            "net_return": returns,
            "turnover_units": turnover,
            "transaction_cost": [value * 0.001 for value in turnover],
        },
        index=index,
    )
    return StrategyResult(key, daily, pd.DataFrame(), {"strategy": key})


def test_state_one_lifecycle_classification_and_cost_saving() -> None:
    states = [0, 1, 1, 2, 2, 1, 0]
    v4_1 = _result(
        "v4_1",
        states,
        [0.0, 0.01, -0.01, 0.02, 0.0, -0.02, 0.0],
        [1.0, 2.0, 0.0, 1.5, 0.0, 1.5, 2.0],
    )
    v4_2 = _result(
        "v4_2",
        states,
        [0.0, 0.008, -0.005, 0.02, 0.0, -0.01, 0.0],
        [1.0, 1.0, 0.0, 1.5, 0.0, 1.5, 1.0],
    )
    episodes, summary = state_one_lifecycle_attribution(v4_1, v4_2)
    assert episodes["lifecycle"].tolist() == ["0->1->2", "2->1->0"]
    first = episodes.iloc[0]
    assert first["turnover_saved"] == pytest.approx(1.0)
    assert set(summary["lifecycle"]) == {"0->1->2", "2->1->0"}


def test_state_trace_divergence_is_rejected() -> None:
    left = _result("left", [0, 1, 2], [0.0, 0.0, 0.0], [1.0, 2.0, 1.5])
    right = _result("right", [0, 0, 2], [0.0, 0.0, 0.0], [1.0, 0.0, 2.0])
    with pytest.raises(AssertionError, match="state traces"):
        state_one_lifecycle_attribution(left, right)


def test_tail_metrics_capture_drawdown_and_duration() -> None:
    result = _result(
        "tail",
        [0, 1, 1, 2, 2, 0],
        [0.02, -0.10, -0.05, 0.03, 0.04, 0.08],
        [1.0, 1.0, 0.0, 1.5, 0.0, 2.0],
    )
    metrics = tail_risk_metrics(result)
    assert metrics["max_drawdown"] < -0.10
    assert metrics["worst_daily_return"] == pytest.approx(-0.10)
    assert metrics["maximum_underwater_run_sessions"] >= 1
    assert metrics["state_tail"]["1"]["sessions"] == 2
