from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_32_ma200_fast_repair_release import apply_fast_release_state0_defense
from src.research.v4_33_ma200_ma20_vix_release import (
    DEFENSIVE_CASH_WEIGHT,
    DEFENSIVE_EQUITY_WEIGHT,
    build_ma200_ma20_vix_release_trace,
)


def _index(count: int = 8) -> pd.DatetimeIndex:
    return pd.date_range("2026-03-30", periods=count, freq="B")


def _daily() -> pd.DataFrame:
    index = _index()
    return pd.DataFrame(
        {
            "ma_long": [500.0, 499.5, 499.0, 498.5, 498.0, 497.5, 497.0, 497.5],
            "stress_price_failure": [True, True, True, False, False, True, True, False],
            "vix_easing": [False, False, False, True, True, False, False, True],
            "vix_normalized": [False] * 8,
            "position_state": [0, 0, 0, 0, 0, 0, 1, 2],
            "weight_QQQI": [1.0, 1.0, 1.0, 1.0, 0.75, 1.0, 0.5, 0.0],
            "weight_QQQ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.25],
            "weight_TQQQ": [0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.75],
        },
        index=index,
    )


def _source(daily: pd.DataFrame) -> StrategyResult:
    return StrategyResult("fixture", daily, pd.DataFrame(), {"strategy": "fixture"})


def test_ma200_falling_enters_strong_defense_next_open() -> None:
    daily = _daily()
    trace = build_ma200_ma20_vix_release_trace(daily)

    assert trace.iloc[1]["ma200_falling_at_close"]
    assert not trace.iloc[1]["fast_price_vol_repair_at_close"]
    assert trace.iloc[1]["strong_defense_at_close"]
    assert trace.iloc[2]["strong_defense_at_open"]


def test_ma20_plus_vix_repair_releases_without_ma20_slope_confirmation() -> None:
    daily = _daily()
    trace = build_ma200_ma20_vix_release_trace(daily)

    repair_signal = daily.index[3]
    release_open = daily.index[4]
    assert trace.loc[repair_signal, "ma200_falling_at_close"]
    assert trace.loc[repair_signal, "price_repaired_at_close"]
    assert trace.loc[repair_signal, "volatility_repaired_at_close"]
    assert trace.loc[repair_signal, "fast_price_vol_repair_at_close"]
    assert not trace.loc[release_open, "strong_defense_at_open"]


def test_price_repair_without_vix_repair_does_not_release() -> None:
    daily = _daily()
    date = daily.index[3]
    daily.loc[date, "vix_easing"] = False
    trace = build_ma200_ma20_vix_release_trace(daily)

    assert trace.loc[date, "price_repaired_at_close"]
    assert not trace.loc[date, "volatility_repaired_at_close"]
    assert trace.loc[date, "strong_defense_at_close"]


def test_vix_repair_while_price_below_ma20_does_not_release() -> None:
    daily = _daily()
    date = daily.index[2]
    daily.loc[date, "vix_easing"] = True
    trace = build_ma200_ma20_vix_release_trace(daily)

    assert not trace.loc[date, "price_repaired_at_close"]
    assert trace.loc[date, "volatility_repaired_at_close"]
    assert trace.loc[date, "strong_defense_at_close"]


def test_repair_release_preserves_v427_state0_boost() -> None:
    daily = _daily()
    trace = build_ma200_ma20_vix_release_trace(daily)
    weights, active = apply_fast_release_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )

    boost_open = daily.index[4]
    assert not active.loc[boost_open]
    assert weights.loc[boost_open, "QQQI"] == pytest.approx(0.75)
    assert weights.loc[boost_open, "TQQQ"] == pytest.approx(0.25)
    assert weights.loc[boost_open, "SGOV"] == 0.0


def test_strong_defense_overrides_state0_boost_before_repair() -> None:
    daily = _daily()
    date = daily.index[2]
    daily.loc[date, "weight_QQQI"] = 0.75
    daily.loc[date, "weight_TQQQ"] = 0.25
    trace = build_ma200_ma20_vix_release_trace(daily)
    weights, active = apply_fast_release_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )

    assert active.loc[date]
    assert weights.loc[date, "QQQI"] == pytest.approx(DEFENSIVE_EQUITY_WEIGHT)
    assert weights.loc[date, "SGOV"] == pytest.approx(DEFENSIVE_CASH_WEIGHT)
    assert weights.loc[date, "TQQQ"] == 0.0


def test_state1_state2_and_weight_conservation() -> None:
    daily = _daily()
    trace = pd.DataFrame(
        {"strong_defense_at_open": [True] * len(daily)}, index=daily.index
    )
    weights, active = apply_fast_release_state0_defense(
        _source(daily), trace, cash_symbol="BIL"
    )

    state1 = daily.index[6]
    state2 = daily.index[7]
    assert not active.loc[state1]
    assert not active.loc[state2]
    assert weights.loc[state1, "QQQI"] == pytest.approx(0.5)
    assert weights.loc[state1, "QQQ"] == pytest.approx(0.5)
    assert weights.loc[state2, "QQQ"] == pytest.approx(0.25)
    assert weights.loc[state2, "TQQQ"] == pytest.approx(0.75)
    assert np.allclose(weights.sum(axis=1), 1.0)
