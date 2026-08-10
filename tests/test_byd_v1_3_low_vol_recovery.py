from __future__ import annotations

import pandas as pd

from src.research.byd_v1_3_low_vol_recovery import (
    HOLD_ELIGIBLE_SESSIONS,
    build_recovery_decision,
)


def _champion(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "byd_weight": [0.75] * len(index),
            "etf_weight": [0.25] * len(index),
            "cash_weight": [0.0] * len(index),
        },
        index=index,
    )


def test_high_vol_edge_is_not_caught_up_later() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="B")
    champion = _champion(index)
    base = pd.Series([0.75] * 5, index=index)
    factor = pd.Series([0.0, 0.03, 0.03, 0.03, 0.03], index=index)
    vol = pd.Series(["high", "high", "low", "low", "low"], index=index)
    eligible = pd.Series([True] * 5, index=index)

    decision, state = build_recovery_decision(champion, base, factor, vol, eligible)

    assert state["event_edge"].tolist() == [False, True, False, False, False]
    assert not state["low_vol_confirmed_edge"].any()
    assert not state["lifecycle_started"].any()
    pd.testing.assert_frame_equal(decision, champion)


def test_low_vol_edge_starts_and_detector_flicker_does_not_exit() -> None:
    index = pd.date_range("2026-01-01", periods=6, freq="B")
    champion = _champion(index)
    base = pd.Series([0.75] * 6, index=index)
    factor = pd.Series([0.0, 0.03, 0.0, 0.0, 0.0, 0.0], index=index)
    vol = pd.Series(["low"] * 6, index=index)
    eligible = pd.Series([True] * 6, index=index)

    decision, state = build_recovery_decision(champion, base, factor, vol, eligible)

    assert state["lifecycle_started"].tolist() == [False, True, False, False, False, False]
    assert state["overlay_decision_active"].tolist() == [False, True, True, True, True, True]
    assert decision.loc[index[1]:, "byd_weight"].eq(1.0).all()
    assert decision.loc[index[1]:, "etf_weight"].eq(0.0).all()
    assert state.loc[index[1], "remaining_eligible_sessions_before_decision"] == HOLD_ELIGIBLE_SESSIONS


def test_v1_2_core_recovery_terminates_overlay() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="B")
    champion = _champion(index)
    champion.loc[index[3]:, "byd_weight"] = 1.0
    champion.loc[index[3]:, "etf_weight"] = 0.0
    base = pd.Series([0.75, 0.75, 0.75, 1.0, 1.0], index=index)
    factor = pd.Series([0.0, 0.03, 0.03, 0.03, 0.03], index=index)
    vol = pd.Series(["low"] * 5, index=index)
    eligible = pd.Series([True] * 5, index=index)

    decision, state = build_recovery_decision(champion, base, factor, vol, eligible)

    assert state.loc[index[1], "lifecycle_started"]
    assert state.loc[index[3], "termination_on_decision"] == "core_recovered"
    assert not state.loc[index[3], "overlay_decision_active"]
    pd.testing.assert_frame_equal(decision.loc[index[3]:], champion.loc[index[3]:])
