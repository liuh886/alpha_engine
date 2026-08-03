from __future__ import annotations

import pandas as pd
import pytest

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_2_post_defense_state2_accelerator import (
    _candidate_weights,
    build_single_use_accelerator_trace,
)


def _index(count: int = 9) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-02", periods=count, freq="B")


def test_single_release_arms_only_first_formal_state2_episode() -> None:
    index = _index()
    daily = pd.DataFrame(
        {
            "position_state": [0, 0, 0, 1, 1, 2, 2, 1, 2],
            "overlay_active_at_close": [
                False,
                True,
                True,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
        },
        index=index,
    )
    trace = build_single_use_accelerator_trace(daily)

    assert trace.loc[index[2], "defense_activation_execution"]
    assert trace.loc[index[4], "defense_release_execution"]
    assert trace.loc[index[4], "accelerator_armed"]
    assert trace.loc[index[5], "accelerator_active"]
    assert trace.loc[index[6], "accelerator_active"]
    assert not trace.loc[index[7], "accelerator_active"]
    assert not trace.loc[index[8], "accelerator_active"]
    assert trace.loc[index[5], "accelerator_arm_id"] == 1


def test_new_defense_activation_cancels_stale_arm() -> None:
    index = _index()
    daily = pd.DataFrame(
        {
            "position_state": [0, 0, 1, 1, 1, 2, 1, 1, 2],
            "overlay_active_at_close": [
                False,
                True,
                False,
                False,
                True,
                True,
                False,
                False,
                False,
            ],
        },
        index=index,
    )
    trace = build_single_use_accelerator_trace(daily)

    assert trace.loc[index[3], "defense_release_execution"]
    assert trace.loc[index[3], "accelerator_armed"]
    assert trace.loc[index[5], "defense_activation_execution"]
    assert not trace.loc[index[5], "accelerator_active"]
    assert not trace.loc[index[5], "accelerator_armed"]
    assert trace.loc[index[7], "defense_release_execution"]
    assert trace.loc[index[8], "accelerator_active"]
    assert trace.loc[index[8], "accelerator_arm_id"] == 2


def test_accelerated_weights_are_100_percent_tqqq_only_on_trace() -> None:
    index = _index()
    daily = pd.DataFrame(
        {
            "position_state": [0, 0, 0, 1, 1, 2, 2, 1, 2],
            "overlay_active_at_close": [
                False,
                True,
                True,
                False,
                False,
                False,
                False,
                False,
                False,
            ],
            "weight_QQQI": [1.0, 1.0, 1.0, 0.5, 0.5, 0.0, 0.0, 0.5, 0.0],
            "weight_QQQ": [0.0, 0.0, 0.0, 0.5, 0.5, 0.25, 0.25, 0.5, 0.25],
            "weight_TQQQ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.75, 0.75, 0.0, 0.75],
            "weight_SGOV": [0.0] * 9,
        },
        index=index,
    )
    source = StrategyResult("fixture", daily, pd.DataFrame(), {"strategy": "fixture"})
    trace = build_single_use_accelerator_trace(daily)
    contract = {
        "allocations": {
            "accelerated_state_2": {
                "QQQI": 0.0,
                "QQQ": 0.0,
                "TQQQ": 1.0,
                "SGOV": 0.0,
            }
        }
    }
    weights = _candidate_weights(source, trace, contract)

    assert weights.loc[index[5], "TQQQ"] == pytest.approx(1.0)
    assert weights.loc[index[6], "TQQQ"] == pytest.approx(1.0)
    assert weights.loc[index[8], "TQQQ"] == pytest.approx(0.75)
    assert weights.loc[index[8], "QQQ"] == pytest.approx(0.25)
    assert weights.sum(axis=1).eq(1.0).all()


def test_trace_rejects_missing_required_columns() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        build_single_use_accelerator_trace(
            pd.DataFrame({"position_state": [0]}, index=_index(1))
        )
