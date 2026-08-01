from __future__ import annotations

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vxn_prospective_monitor import (
    latest_monitor_snapshot,
    monitoring_status,
    prospective_return_metrics,
    prospective_state_differences,
)


def _result() -> StrategyResult:
    index = pd.date_range("2026-07-30", periods=4, freq="B")
    daily = pd.DataFrame(
        {
            "net_return": [0.01, -0.01, 0.02, 0.01],
            "position_state": [1, 1, 2, 2],
            "position_label": ["attack", "attack", "partial_leverage", "partial_leverage"],
            "executed_reason": ["hold", "hold", "enter", "hold"],
            "weight_QQQI": [0.0, 0.0, 0.0, 0.0],
            "weight_QQQ": [1.0, 1.0, 0.25, 0.25],
            "weight_TQQQ": [0.0, 0.0, 0.75, 0.75],
            "turnover_units": [0.0, 0.0, 1.5, 0.0],
            "transaction_cost": [0.0, 0.0, 0.0015, 0.0],
        },
        index=index,
    )
    return StrategyResult(
        "test",
        daily,
        pd.DataFrame(),
        {"strategy": "rotation_vxn_leverage_v4_1_75"},
    )


def test_monitor_allows_zero_prospective_returns() -> None:
    metrics = prospective_return_metrics(_result(), "2027-01-01")
    assert metrics["status"] == "awaiting_first_prospective_return"
    assert metrics["observations"] == 0
    assert monitoring_status({"test": metrics}) == "awaiting_first_prospective_return"


def test_monitor_metrics_use_only_dates_on_or_after_start() -> None:
    metrics = prospective_return_metrics(_result(), "2026-08-03")
    assert metrics["observations"] == 2
    assert metrics["start_date"] == "2026-08-03"
    assert metrics["state_counts"]["partial_leverage"] == 2
    assert monitoring_status({"test": metrics}) == "prospective_monitoring_active"


def test_state_differences_are_filtered_by_monitoring_start() -> None:
    index = pd.date_range("2026-07-30", periods=5, freq="B")
    prepared = pd.DataFrame(
        {
            "vix_close": [20.0] * 5,
            "vxn_close": [25.0] * 5,
            "vix_stress": [False] * 5,
            "vxn_stress": [False, True, False, True, False],
            "TQQQ_next_open_return": [0.01, 0.02, 0.03, 0.04, float("nan")],
        },
        index=index,
    )
    baseline = pd.DataFrame(
        {
            "decision_state": [1, 2, 2, 2, 2],
            "decision_reason": ["hold", "enter", "hold", "hold", "hold"],
        },
        index=index,
    )
    overlay = baseline.copy()
    overlay.loc[index[1], ["decision_state", "decision_reason"]] = [1, "vxn_veto"]
    overlay.loc[index[3], ["decision_state", "decision_reason"]] = [1, "vxn_veto"]
    events = prospective_state_differences(
        prepared,
        baseline,
        overlay,
        start_date="2026-08-03",
        horizons=(1,),
    )
    assert events["signal_date"].tolist() == [index[3]]


def test_latest_snapshot_separates_executed_position_and_close_decision() -> None:
    result = _result()
    index = pd.date_range("2026-07-30", periods=5, freq="B")
    prepared = pd.DataFrame(
        {
            "vix_close": [20.0] * 5,
            "vxn_close": [25.0] * 5,
            "vix_stress": [False] * 5,
            "vix_easing": [True] * 5,
            "vix_normalized": [True] * 5,
            "vxn_stress": [False] * 5,
        },
        index=index,
    )
    decisions = pd.DataFrame(
        {
            "decision_state": [1, 1, 2, 2, 1],
            "decision_reason": ["hold", "hold", "enter", "hold", "vxn_exit"],
        },
        index=index,
    )
    snapshot = latest_monitor_snapshot(prepared, result, decisions)
    assert snapshot["latest_executed_position"]["position_label"] == "partial_leverage"
    assert snapshot["latest_close_signal"]["decision_label"] == "attack"
