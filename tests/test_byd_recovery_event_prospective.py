from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_recovery_event_prospective import (
    HOLD_ELIGIBLE_SESSIONS,
    LAUNCH_AFTER,
    build_champion_targets,
    build_event_lifecycle_schedule,
)


def _series(index: pd.DatetimeIndex, values: list[object], *, dtype: str | None = None) -> pd.Series:
    return pd.Series(values, index=index, dtype=dtype)


def test_event_lifecycle_requires_new_post_launch_edge() -> None:
    index = pd.date_range(LAUNCH_AFTER, periods=6, freq="D")
    base = _series(index, [0.75] * 6, dtype="float64")
    detector = _series(index, [True, True, False, True, False, False], dtype="bool")
    common = _series(index, [True] * 6, dtype="bool")
    prospective = _series(index, [False, True, True, True, True, True], dtype="bool")

    schedule = build_event_lifecycle_schedule(
        index=index,
        base_target=base,
        detector=detector,
        common_open_eligible=common,
        prospective_eligible=prospective,
    )

    assert not bool(schedule.iloc[1]["lifecycle_started"])
    assert bool(schedule.iloc[3]["lifecycle_started"])
    assert int(schedule.iloc[3]["lifecycle_id"]) == 1


def test_detector_flicker_does_not_exit_active_lifecycle() -> None:
    index = pd.date_range(LAUNCH_AFTER, periods=7, freq="D")
    base = _series(index, [0.75] * 7, dtype="float64")
    detector = _series(index, [False, True, False, False, False, False, False], dtype="bool")
    common = _series(index, [True] * 7, dtype="bool")
    prospective = _series(index, [False] + [True] * 6, dtype="bool")

    schedule = build_event_lifecycle_schedule(
        index=index,
        base_target=base,
        detector=detector,
        common_open_eligible=common,
        prospective_eligible=prospective,
    )

    assert bool(schedule.iloc[1]["lifecycle_started"])
    assert schedule.iloc[2:]["overlay_decision_active"].all()


def test_core_recovery_terminates_before_max_hold() -> None:
    index = pd.date_range(LAUNCH_AFTER, periods=7, freq="D")
    base = _series(index, [0.75, 0.75, 0.75, 1.0, 1.0, 1.0, 1.0], dtype="float64")
    detector = _series(index, [False, True, False, False, False, False, False], dtype="bool")
    common = _series(index, [True] * 7, dtype="bool")
    prospective = _series(index, [False] + [True] * 6, dtype="bool")

    schedule = build_event_lifecycle_schedule(
        index=index,
        base_target=base,
        detector=detector,
        common_open_eligible=common,
        prospective_eligible=prospective,
    )

    assert bool(schedule.iloc[1]["overlay_decision_active"])
    assert bool(schedule.iloc[2]["overlay_decision_active"])
    assert not bool(schedule.iloc[3]["overlay_decision_active"])
    assert schedule.iloc[3]["termination_on_decision"] == "core_recovered"


def test_max_hold_counts_only_common_eligible_execution_opens() -> None:
    periods = HOLD_ELIGIBLE_SESSIONS + 5
    index = pd.date_range(LAUNCH_AFTER, periods=periods, freq="D")
    base = _series(index, [0.75] * periods, dtype="float64")
    detector = _series(index, [False, True] + [False] * (periods - 2), dtype="bool")
    common_values = [True] * periods
    common_values[5] = False
    common_values[8] = False
    common = _series(index, common_values, dtype="bool")
    prospective = _series(index, [False] + [True] * (periods - 1), dtype="bool")

    schedule = build_event_lifecycle_schedule(
        index=index,
        base_target=base,
        detector=detector,
        common_open_eligible=common,
        prospective_eligible=prospective,
    )

    active = schedule["overlay_decision_active"].astype(bool)
    executed_opens = 0
    for position in range(1, len(index)):
        if bool(active.iloc[position - 1]) and bool(common.iloc[position]):
            executed_opens += 1
    assert executed_opens == HOLD_ELIGIBLE_SESSIONS
    assert schedule.loc[active].iloc[-1]["remaining_eligible_sessions"] == 1
    first_inactive_after = active.index[(active.index > active[active].index[-1])][0]
    assert schedule.loc[first_inactive_after, "termination_on_decision"] == "max_hold"


def test_champion_target_uses_convex_momentum_budget() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    dataset = pd.DataFrame(
        {
            "market_state": ["bull", "bull", "bull", "bear"],
            "vol_state": ["low", "low", "low", "low"],
            "drawdown_252": [-0.05, -0.04, -0.03, -0.20],
            "mom_20": [0.075, 0.075, 0.075, -0.01],
            "mom_60": [0.10, 0.10, 0.10, -0.05],
        },
        index=index,
    )
    base = _series(index, [1.0, 1.0, 1.0, 0.75], dtype="float64")

    targets, diagnostics = build_champion_targets(dataset, base)

    expected_scale = (0.075 / 0.15) ** 4
    expected_increment = 0.125 * expected_scale
    assert np.isclose(diagnostics.iloc[0]["momentum_scale"], expected_scale)
    assert np.isclose(targets.iloc[0]["byd_weight"], 1.0 + expected_increment)
    assert np.isclose(targets.iloc[0]["cash_weight"], -expected_increment)
    assert np.isclose(targets.iloc[3]["byd_weight"], 0.75)
    assert np.isclose(targets.iloc[3]["etf_weight"], 0.25)
