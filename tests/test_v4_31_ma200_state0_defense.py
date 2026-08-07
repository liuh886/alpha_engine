from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_31_ma200_state0_defense import (
    DEFENSIVE_CASH_WEIGHT,
    DEFENSIVE_EQUITY_WEIGHT,
    apply_ma200_state0_defense,
    build_ma200_trend_trace,
)


def _index(count: int = 8) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-02", periods=count, freq="B")


def _daily() -> pd.DataFrame:
    index = _index()
    return pd.DataFrame(
        {
            "ma_long": [500.0, 501.0, 500.5, 500.0, 499.0, 498.0, 499.0, 500.0],
            "position_state": [0, 0, 0, 0, 0, 1, 2, 0],
            "weight_QQQI": [1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.0, 1.0],
            "weight_QQQ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.25, 0.0],
            "weight_TQQQ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.75, 0.0],
        },
        index=index,
    )


def _source(daily: pd.DataFrame) -> StrategyResult:
    return StrategyResult("fixture", daily, pd.DataFrame(), {"strategy": "fixture"})


def test_ma200_falling_signal_is_close_time_and_shifted_once() -> None:
    daily = _daily()
    trace = build_ma200_trend_trace(daily)

    assert not trace.iloc[1]["ma200_falling_at_close"]
    assert trace.iloc[2]["ma200_falling_at_close"]
    assert not trace.iloc[2]["ma200_falling_at_open"]
    assert trace.iloc[3]["ma200_falling_at_open"]


def test_guard_changes_only_falling_ma200_state0() -> None:
    daily = _daily()
    trace = build_ma200_trend_trace(daily)
    weights, active = apply_ma200_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )

    guarded = daily.index[3]
    assert active.loc[guarded]
    assert weights.loc[guarded, "QQQI"] == pytest.approx(DEFENSIVE_EQUITY_WEIGHT)
    assert weights.loc[guarded, "SGOV"] == pytest.approx(DEFENSIVE_CASH_WEIGHT)
    assert weights.loc[guarded, "TQQQ"] == 0.0


def test_guard_never_changes_state1_or_state2() -> None:
    daily = _daily()
    trace = pd.DataFrame(
        {"ma200_falling_at_open": [True] * len(daily)}, index=daily.index
    )
    weights, active = apply_ma200_state0_defense(
        _source(daily), trace, cash_symbol="BIL"
    )

    state1 = daily.index[5]
    state2 = daily.index[6]
    assert not active.loc[state1]
    assert not active.loc[state2]
    assert weights.loc[state1, "QQQI"] == pytest.approx(0.5)
    assert weights.loc[state1, "QQQ"] == pytest.approx(0.5)
    assert weights.loc[state2, "QQQ"] == pytest.approx(0.25)
    assert weights.loc[state2, "TQQQ"] == pytest.approx(0.75)
    assert weights.loc[state1, "BIL"] == 0.0
    assert weights.loc[state2, "BIL"] == 0.0


def test_guard_overrides_state0_panic_boost() -> None:
    daily = _daily()
    date = daily.index[3]
    daily.loc[date, "weight_QQQI"] = 0.75
    daily.loc[date, "weight_TQQQ"] = 0.25
    trace = pd.DataFrame(
        {"ma200_falling_at_open": [False, False, False, True, False, False, False, False]},
        index=daily.index,
    )
    weights, active = apply_ma200_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )

    assert active.loc[date]
    assert weights.loc[date, "QQQI"] == pytest.approx(0.5)
    assert weights.loc[date, "SGOV"] == pytest.approx(0.5)
    assert weights.loc[date, "TQQQ"] == 0.0


def test_all_weights_sum_to_one() -> None:
    daily = _daily()
    trace = build_ma200_trend_trace(daily)
    weights, _ = apply_ma200_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )
    assert np.allclose(weights.sum(axis=1), 1.0)
