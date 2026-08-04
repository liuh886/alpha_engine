from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_v1_3_recovery_overlay import (
    COOLDOWN_ELIGIBLE_OPENS,
    HOLD_ELIGIBLE_INTERVALS,
    SNAPSHOT_SHA256,
    branch_conditions,
    build_overlay_schedule,
)


def _dataset(periods: int = 40) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-02", periods=periods)
    frame = pd.DataFrame(index=index)
    frame["market_state"] = "bear"
    frame["vol_state"] = "low"
    frame["drawdown_252"] = -0.20
    frame["distance_from_low_20"] = 0.06
    frame["open_return_autocorr_20"] = -0.10
    frame["momentum_accel_20_60"] = 0.10
    frame["open_research_eligible"] = True
    return frame


def test_snapshot_identity_and_frozen_clocks() -> None:
    assert SNAPSHOT_SHA256 == (
        "2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179"
    )
    assert HOLD_ELIGIBLE_INTERVALS == 10
    assert COOLDOWN_ELIGIBLE_OPENS == 10


def test_overlay_holds_exactly_ten_eligible_intervals() -> None:
    dataset = _dataset(25)
    dataset.iloc[0:3, dataset.columns.get_loc("open_return_autocorr_20")] = 0.10
    base = pd.Series(0.75, index=dataset.index)
    schedule = build_overlay_schedule(dataset, base)

    assert schedule.overlay_active.iloc[:10].all()
    assert not bool(schedule.overlay_active.iloc[10])
    event = schedule.event_ledger.iloc[0]
    assert event["eligible_intervals"] == 10
    assert event["entry_execution_date"] == dataset.index[1]
    assert event["last_active_open_date"] == dataset.index[10]
    assert event["exit_execution_date"] == dataset.index[11]
    assert bool(event["completed"])


def test_quarantined_open_does_not_advance_holding_clock() -> None:
    dataset = _dataset(25)
    dataset.iloc[0:3, dataset.columns.get_loc("open_return_autocorr_20")] = 0.10
    dataset.iloc[5, dataset.columns.get_loc("open_research_eligible")] = False
    base = pd.Series(0.75, index=dataset.index)
    schedule = build_overlay_schedule(dataset, base)

    assert schedule.overlay_active.iloc[:11].all()
    assert not bool(schedule.overlay_active.iloc[11])
    event = schedule.event_ledger.iloc[0]
    assert event["eligible_intervals"] == 10
    assert event["last_active_open_date"] == dataset.index[11]
    assert event["exit_execution_date"] == dataset.index[12]


def test_same_branch_cooldown_blocks_early_retrigger() -> None:
    dataset = _dataset(35)
    autocorr_col = dataset.columns.get_loc("open_return_autocorr_20")
    dataset.iloc[0:2, autocorr_col] = 0.10
    dataset.iloc[12, autocorr_col] = 0.10
    dataset.iloc[21, autocorr_col] = 0.10
    base = pd.Series(0.75, index=dataset.index)
    schedule = build_overlay_schedule(dataset, base)

    assert len(schedule.event_ledger) == 2
    assert schedule.event_ledger.iloc[0]["trigger_date"] == dataset.index[0]
    assert schedule.event_ledger.iloc[1]["trigger_date"] == dataset.index[21]


def test_overlay_never_reduces_or_exceeds_declared_positions() -> None:
    dataset = _dataset(30)
    dataset.iloc[0:3, dataset.columns.get_loc("open_return_autocorr_20")] = 0.10
    base = pd.Series(
        np.where(np.arange(len(dataset)) % 4 == 0, 1.0, 0.75),
        index=dataset.index,
    )
    schedule = build_overlay_schedule(dataset, base)
    assert (schedule.final_decision_position >= base).all()
    assert set(schedule.final_decision_position.unique()).issubset({0.75, 1.0})


def test_branch_b_is_restricted_to_bull_high_volatility() -> None:
    dataset = _dataset(5)
    dataset["market_state"] = "bull"
    dataset["vol_state"] = "high"
    dataset["drawdown_252"] = -0.12
    dataset["momentum_accel_20_60"] = 0.05
    conditions = branch_conditions(dataset)
    assert conditions["bull_high_vol"].all()
    assert not conditions["bear_sideways_low_vol"].any()
