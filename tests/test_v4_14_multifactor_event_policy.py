from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_14_multifactor_event_policy import (
    _action_weights,
    _event_action_trace,
    _run_policy,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_multifactor_events_v4_14_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _baseline(index: pd.DatetimeIndex) -> pd.DataFrame:
    daily = pd.DataFrame(index=index)
    daily["position_state"] = [0, 0, 1, 1, 2, 2, 2, 1, 1, 0]
    daily["weight_QQQI"] = [1, 1, 0.5, 0.5, 0, 0, 0, 0.5, 0.5, 1]
    daily["weight_QQQ"] = [0, 0, 0.5, 0.5, 0.25, 0.25, 0.25, 0.5, 0.5, 0]
    daily["weight_TQQQ"] = [0, 0, 0, 0, 0.75, 0.75, 0.75, 0, 0, 0]
    daily["QQQI_next_open_return"] = 0.001
    daily["QQQ_next_open_return"] = 0.002
    daily["TQQQ_next_open_return"] = 0.004
    return daily


def _events(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_family": ["tech_acceleration", "repair", "broad_rotation", "defense"],
            "event_id": ["accel", "repair", "rotation", "defense"],
            "rule_id": ["r1", "r2", "r3", "r4"],
            "action": [
                "NASDAQ_ACCELERATE",
                "NASDAQ_INCOME",
                "BROAD_EQUITY",
                "SGOV_DEFENSE",
            ],
            "execution_date": [index[1], index[2], index[3], index[4]],
            "event_end_date": [index[6], index[6], index[6], index[6]],
        }
    )


def test_priority_is_defense_then_rotation_then_repair_then_acceleration() -> None:
    index = pd.date_range("2024-01-02", periods=10, freq="B")
    trace = _event_action_trace(index, _events(index), _contract())
    assert trace.loc[index[1], "event_family"] == "tech_acceleration"
    assert trace.loc[index[2], "event_family"] == "repair"
    assert trace.loc[index[3], "event_family"] == "broad_rotation"
    assert trace.loc[index[4], "event_family"] == "defense"
    assert trace.loc[index[6], "event_family"] == "defense"


def test_action_weights_sum_to_one_and_use_proxy_income_mapping() -> None:
    index = pd.date_range("2024-01-02", periods=10, freq="B")
    baseline = _baseline(index)
    trace = _event_action_trace(index, _events(index), _contract())
    weights = _action_weights(baseline, trace, proxy_mode=True)
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert weights.loc[index[2], "QQQ"] == 1.0
    assert weights.loc[index[4], "cash"] == 1.0
    assert weights.loc[index[3], "VOO"] == 1.0


def test_actual_income_action_uses_qqqi_not_qqq() -> None:
    index = pd.date_range("2024-01-02", periods=10, freq="B")
    baseline = _baseline(index)
    trace = _event_action_trace(index, _events(index), _contract())
    weights = _action_weights(baseline, trace, proxy_mode=False)
    assert weights.loc[index[2], "QQQI"] == 1.0
    assert weights.loc[index[2], "QQQ"] == 0.0


def test_policy_cost_equals_turnover_times_ten_bps() -> None:
    index = pd.date_range("2024-01-02", periods=10, freq="B")
    baseline = _baseline(index)
    trace = _event_action_trace(index, _events(index), _contract())
    result = _run_policy(
        baseline,
        pd.Series(0.0015, index=index),
        pd.Series(0.0001, index=index),
        trace,
        _contract(),
        name="unit_policy",
        proxy_mode=False,
    )
    assert np.allclose(
        result.daily["transaction_cost"],
        result.daily["turnover_units"] * 0.001,
    )
    weight_columns = [
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "weight_VOO",
        "weight_cash",
    ]
    assert np.allclose(result.daily[weight_columns].sum(axis=1), 1.0)
