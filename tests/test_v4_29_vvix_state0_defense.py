from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_29_vvix_state0_defense import (
    DEFENSIVE_CASH_WEIGHT,
    DEFENSIVE_EQUITY_WEIGHT,
    VVIX_STRESS_QUANTILE,
    VVIX_WINDOW,
    apply_vvix_state0_defense,
    build_vvix_stress_trace,
)


def _index(count: int = 260) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-02", periods=count, freq="B")


def _daily(count: int = 260) -> pd.DataFrame:
    index = _index(count)
    state = [0] * count
    if count >= 4:
        state[-2] = 1
        state[-1] = 2
    qqqi = [1.0 if value == 0 else (0.5 if value == 1 else 0.0) for value in state]
    qqq = [0.0 if value == 0 else (0.5 if value == 1 else 0.25) for value in state]
    tqqq = [0.0 if value in (0, 1) else 0.75 for value in state]
    return pd.DataFrame(
        {
            "position_state": state,
            "weight_QQQI": qqqi,
            "weight_QQQ": qqq,
            "weight_TQQQ": tqqq,
        },
        index=index,
    )


def _source(daily: pd.DataFrame) -> StrategyResult:
    return StrategyResult("fixture", daily, pd.DataFrame(), {"strategy": "fixture"})


def test_vvix_stress_uses_252_session_80th_percentile_and_next_open() -> None:
    daily = _daily()
    values = np.linspace(80.0, 120.0, len(daily))
    vvix = pd.DataFrame({"close": values}, index=daily.index)
    trace = build_vvix_stress_trace(daily, vvix)

    assert trace["vvix_stress_threshold"].iloc[VVIX_WINDOW - 2] != trace[
        "vvix_stress_threshold"
    ].iloc[VVIX_WINDOW - 2]
    expected = pd.Series(values[:VVIX_WINDOW]).quantile(VVIX_STRESS_QUANTILE)
    assert trace["vvix_stress_threshold"].iloc[VVIX_WINDOW - 1] == pytest.approx(expected)
    assert trace["vvix_stress_at_close"].iloc[VVIX_WINDOW - 1]
    assert trace["vvix_stress_at_open"].iloc[VVIX_WINDOW]


def test_missing_vvix_is_not_forward_filled() -> None:
    daily = _daily()
    values = np.linspace(80.0, 120.0, len(daily))
    values[-1] = np.nan
    vvix = pd.DataFrame({"close": values}, index=daily.index)
    trace = build_vvix_stress_trace(daily, vvix)

    assert pd.isna(trace["vvix_close"].iloc[-1])
    assert not trace["vvix_stress_at_close"].iloc[-1]


def test_guard_changes_only_stressed_executed_state0() -> None:
    daily = _daily()
    trace = pd.DataFrame(
        {"vvix_stress_at_open": [False] * (len(daily) - 3) + [True, True, True]},
        index=daily.index,
    )
    weights, active = apply_vvix_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )

    guarded_state0 = daily.index[-3]
    assert active.loc[guarded_state0]
    assert weights.loc[guarded_state0, "QQQI"] == pytest.approx(DEFENSIVE_EQUITY_WEIGHT)
    assert weights.loc[guarded_state0, "SGOV"] == pytest.approx(DEFENSIVE_CASH_WEIGHT)
    assert weights.loc[guarded_state0, "TQQQ"] == 0.0

    state1 = daily.index[-2]
    state2 = daily.index[-1]
    assert not active.loc[state1]
    assert not active.loc[state2]
    assert weights.loc[state1, "QQQI"] == pytest.approx(0.5)
    assert weights.loc[state1, "QQQ"] == pytest.approx(0.5)
    assert weights.loc[state2, "QQQ"] == pytest.approx(0.25)
    assert weights.loc[state2, "TQQQ"] == pytest.approx(0.75)


def test_defense_overrides_state0_tqqq_boost() -> None:
    daily = _daily()
    date = daily.index[-3]
    daily.loc[date, "weight_QQQI"] = 0.75
    daily.loc[date, "weight_TQQQ"] = 0.25
    trace = pd.DataFrame(
        {"vvix_stress_at_open": [False] * (len(daily) - 3) + [True, False, False]},
        index=daily.index,
    )
    weights, active = apply_vvix_state0_defense(
        _source(daily), trace, cash_symbol="SGOV"
    )

    assert active.loc[date]
    assert weights.loc[date, "QQQI"] == pytest.approx(0.5)
    assert weights.loc[date, "SGOV"] == pytest.approx(0.5)
    assert weights.loc[date, "TQQQ"] == 0.0


def test_weights_always_sum_to_one() -> None:
    daily = _daily()
    trace = pd.DataFrame(
        {"vvix_stress_at_open": [True] * len(daily)}, index=daily.index
    )
    weights, _ = apply_vvix_state0_defense(_source(daily), trace, cash_symbol="BIL")
    assert np.allclose(weights.sum(axis=1), 1.0)
