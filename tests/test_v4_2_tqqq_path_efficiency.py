from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.v4_2_tqqq_path_efficiency import (
    _horizon_metrics,
    path_efficiency_decision,
)


def _daily_fixture() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=6, freq="B")
    qqq_returns = np.array([0.01, -0.005, 0.012, -0.003, 0.008])
    tqqq_returns = 3.0 * qqq_returns
    qqq_open = [100.0]
    tqqq_open = [50.0]
    for qqq_return, tqqq_return in zip(qqq_returns, tqqq_returns, strict=True):
        qqq_open.append(qqq_open[-1] * (1.0 + qqq_return))
        tqqq_open.append(tqqq_open[-1] * (1.0 + tqqq_return))
    frame = pd.DataFrame(index=index)
    frame["QQQ_open"] = qqq_open
    frame["QQQ_close"] = frame["QQQ_open"]
    frame["TQQQ_open"] = tqqq_open
    frame["TQQQ_close"] = frame["TQQQ_open"]
    frame["QQQ_next_open_return"] = frame["QQQ_open"].shift(-1) / frame[
        "QQQ_open"
    ] - 1.0
    frame["TQQQ_next_open_return"] = frame["TQQQ_open"].shift(-1) / frame[
        "TQQQ_open"
    ] - 1.0
    return frame


def test_horizon_metrics_reconcile_exact_daily_three_x_path() -> None:
    metrics = _horizon_metrics(
        _daily_fixture(),
        start=0,
        horizon=5,
        counterfactual_leverage=3.0,
    )

    assert np.isclose(
        metrics["tqqq_return_5d"], metrics["counterfactual_3x_qqq_return_5d"]
    )
    assert np.isclose(metrics["tqqq_tracking_compounding_residual_5d"], 0.0)
    assert metrics["qqq_sign_reversals_5d"] == 4
    assert np.isclose(metrics["qqq_intraday_log_return_5d"], 0.0)
    assert np.isfinite(metrics["qqq_overnight_log_return_5d"])


def test_decision_blocks_new_hypothesis_without_late_failure() -> None:
    rows = []
    for index in range(12):
        success = index % 2 == 0
        segment = "late" if index >= 9 else "early"
        if segment == "late":
            success = True
        rows.append(
            {
                "event_id": f"event_{index:02d}",
                "marginal_success": success,
                "failure_type": (
                    "successful_recovery"
                    if success
                    else "failed_recovery_reached_state2_but_extra_leverage_lost"
                    if index % 3
                    else "failed_recovery_reverted_before_state2"
                ),
                "chronological_segment": segment,
                "event_directional_leverage_component": 0.01 if success else -0.01,
                "event_tracking_compounding_component": -0.0002,
            }
        )
    table = pd.DataFrame(rows)
    separation = pd.DataFrame(
        {
            "feature": ["qqq_return_5d", "qqq_mae_5d"],
            "descriptively_stable": [True, True],
        }
    )
    contract = {
        "validation": {
            "minimum_event_count": 12,
            "minimum_successful_event_count": 4,
            "minimum_failed_event_count": 4,
            "minimum_failure_subtype_count": 2,
            "maximum_mechanism_fields": 6,
        }
    }

    decision = path_efficiency_decision(table, separation, contract)

    assert decision["path_mechanism_explanation_justified"] is True
    assert decision["prospective_path_monitoring_justified"] is True
    assert decision["new_preregistered_trading_hypothesis_justified"] is False
    assert decision["checks"]["late_segment_contains_success_and_failure"] is False
    assert decision["mechanism"] == (
        "underlying_path_and_entry_timing_dominate_tracking_residual"
    )
