from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_2_panic_repair_boost import (
    TQQQ_BOOST,
    build_panic_repair_trace,
    panic_repair_weights,
)


def _index(count: int = 7) -> pd.DatetimeIndex:
    return pd.date_range("2026-03-30", periods=count, freq="B")


def _daily() -> pd.DataFrame:
    index = _index()
    return pd.DataFrame(
        {
            "rsi_14": [25.0, 28.0, 33.0, 36.0, 40.0, 45.0, 50.0],
            "decision_state": [0, 0, 0, 1, 1, 2, 2],
            "position_state": [0, 0, 0, 0, 1, 1, 2],
            "early_repair": [False, False, False, True, True, True, True],
            "stress_price_failure": [True, True, True, False, False, False, False],
            "vix_easing": [False, False, False, True, True, True, True],
            "vix_normalized": [False] * 7,
            "weight_QQQI": [1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.0],
            "weight_QQQ": [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.25],
            "weight_TQQQ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.75],
            "weight_SGOV": [0.0] * 7,
        },
        index=index,
    )


def _sentiment(scores: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame({"fear_greed_score": scores}, index=_index())


def test_panic_arms_but_does_not_buy_tqqq_immediately() -> None:
    daily = _daily()
    trace = build_panic_repair_trace(
        daily,
        _sentiment([5.0, 8.0, 15.0, 20.0, 30.0, 40.0, 50.0]),
    )

    assert trace.iloc[0]["panic_start_at_close"]
    assert trace.iloc[0]["panic_repair_armed_at_close"]
    assert not trace.iloc[0]["panic_repair_active_at_close"]
    assert not trace.iloc[1]["panic_repair_active_at_open"]


def test_repair_close_activates_only_at_next_open() -> None:
    daily = _daily()
    trace = build_panic_repair_trace(
        daily,
        _sentiment([5.0, 8.0, 15.0, 20.0, 30.0, 40.0, 50.0]),
    )

    assert trace.iloc[3]["repair_ready_at_close"]
    assert trace.iloc[3]["panic_repair_active_at_close"]
    assert not trace.iloc[3]["panic_repair_active_at_open"]
    assert trace.iloc[4]["panic_repair_active_at_open"]


def test_missing_sentiment_is_not_forward_filled() -> None:
    daily = _daily()
    sentiment = _sentiment([5.0, None, None, 20.0, 30.0, 40.0, 50.0])
    trace = build_panic_repair_trace(daily, sentiment)

    assert trace.iloc[0]["panic_start_at_close"]
    assert pd.isna(trace.iloc[1]["fear_greed_score"])
    assert not trace.iloc[1]["panic_condition_at_close"]


def test_boost_adds_exactly_25pp_tqqq_and_preserves_state2() -> None:
    daily = _daily()
    trace = build_panic_repair_trace(
        daily,
        _sentiment([5.0, 8.0, 15.0, 20.0, 30.0, 40.0, 50.0]),
    )
    weights = panic_repair_weights(daily, trace)

    active_date = daily.index[4]
    assert weights.loc[active_date, "TQQQ"] == pytest.approx(TQQQ_BOOST)
    assert weights.loc[active_date, "QQQI"] == pytest.approx(0.375)
    assert weights.loc[active_date, "QQQ"] == pytest.approx(0.375)

    state_two_date = daily.index[6]
    assert weights.loc[state_two_date, "TQQQ"] == pytest.approx(0.75)
    assert weights.loc[state_two_date, "QQQ"] == pytest.approx(0.25)
    assert weights.sum(axis=1).eq(1.0).all()


def test_repair_failure_exits_boost_at_next_open() -> None:
    daily = _daily()
    daily.loc[daily.index[4], "stress_price_failure"] = True
    trace = build_panic_repair_trace(
        daily,
        _sentiment([5.0, 8.0, 15.0, 20.0, 30.0, 40.0, 50.0]),
    )

    assert trace.iloc[4]["panic_repair_reason_at_close"] == "repair_failure_exits_boost"
    assert not trace.iloc[5]["panic_repair_active_at_open"]


def test_formal_state2_cancels_unconsumed_arm() -> None:
    daily = _daily()
    daily["early_repair"] = False
    daily["vix_easing"] = False
    trace = build_panic_repair_trace(
        daily,
        _sentiment([5.0, 8.0, 15.0, 20.0, 30.0, 40.0, 50.0]),
    )

    assert trace.iloc[0]["panic_repair_armed_at_close"]
    assert not trace.iloc[5]["panic_repair_armed_at_close"]
    assert trace.iloc[5]["panic_repair_reason_at_close"] == "formal_state2_cancels_arm"
