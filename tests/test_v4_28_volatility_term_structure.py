from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_28_volatility_term_structure import (
    STATE2_GUARDED_TQQQ_WEIGHT,
    apply_backwardation_guard,
    build_term_confirmed_panic_trace,
    build_term_structure_trace,
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
            "vix_close": [35.0, 32.0, 29.0, 25.0, 22.0, 20.0, 18.0],
            "weight_QQQI": [1.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.0],
            "weight_QQQ": [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.25],
            "weight_TQQQ": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.75],
        },
        index=index,
    )


def _index_frame(values: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame({"close": values}, index=_index())


def _fear() -> pd.DataFrame:
    return pd.DataFrame(
        {"fear_greed_score": [5.0, 8.0, 15.0, 20.0, 30.0, 40.0, 50.0]},
        index=_index(),
    )


def _weights(daily: pd.DataFrame) -> pd.DataFrame:
    return daily[["weight_QQQI", "weight_QQQ", "weight_TQQQ"]].rename(
        columns={
            "weight_QQQI": "QQQI",
            "weight_QQQ": "QQQ",
            "weight_TQQQ": "TQQQ",
        }
    )


def test_term_structure_uses_exact_dates_without_forward_fill() -> None:
    daily = _daily()
    vix9d = _index_frame([40.0, None, 30.0, 20.0, 18.0, 17.0, 16.0])
    vix3m = _index_frame([30.0, 31.0, 30.0, 26.0, 23.0, 21.0, 19.0])
    trace = build_term_structure_trace(daily, vix9d, vix3m)

    assert not trace.iloc[1]["term_structure_complete_at_close"]
    assert pd.isna(trace.iloc[1]["vix9d_close"])
    assert not trace.iloc[1]["acute_normalized_at_close"]


def test_vix9d_confirmation_delays_panic_repair_activation() -> None:
    daily = _daily()
    vix9d = _index_frame([40.0, 38.0, 35.0, 27.0, 20.0, 18.0, 17.0])
    vix3m = _index_frame([30.0, 30.0, 30.0, 27.0, 24.0, 22.0, 20.0])
    term = build_term_structure_trace(daily, vix9d, vix3m)
    trace = build_term_confirmed_panic_trace(daily, _fear(), term)

    assert daily.iloc[3]["early_repair"]
    assert not term.iloc[3]["acute_normalized_at_close"]
    assert not trace.iloc[3]["panic_repair_active_at_close"]
    assert term.iloc[4]["acute_normalized_at_close"]
    assert trace.iloc[4]["panic_repair_active_at_close"]
    assert trace.iloc[5]["panic_repair_active_at_open"]


def test_backwardation_guard_uses_prior_close_and_only_state2() -> None:
    daily = _daily()
    daily.loc[daily.index[5], "vix_close"] = 25.0
    vix9d = _index_frame([30.0] * 7)
    vix3m = _index_frame([40.0, 40.0, 40.0, 40.0, 40.0, 20.0, 30.0])
    term = build_term_structure_trace(daily, vix9d, vix3m)
    guarded, active = apply_backwardation_guard(daily, _weights(daily), term)

    state2_date = daily.index[6]
    assert term.loc[daily.index[5], "curve_backwardation_at_close"]
    assert active.loc[state2_date]
    assert guarded.loc[state2_date, "TQQQ"] == pytest.approx(
        STATE2_GUARDED_TQQQ_WEIGHT
    )
    assert guarded.loc[state2_date, "QQQ"] == pytest.approx(0.50)


def test_backwardation_does_not_change_non_state2_weights() -> None:
    daily = _daily()
    daily["vix_close"] = 30.0
    vix9d = _index_frame([35.0] * 7)
    vix3m = _index_frame([20.0] * 7)
    term = build_term_structure_trace(daily, vix9d, vix3m)
    original = _weights(daily)
    guarded, active = apply_backwardation_guard(daily, original, term)

    non_state2 = daily["position_state"].ne(2)
    pd.testing.assert_frame_equal(guarded.loc[non_state2], original.loc[non_state2])
    assert not active.loc[non_state2].any()


def test_guard_restores_ordinary_state2_when_curve_normalizes() -> None:
    daily = _daily()
    daily.loc[daily.index[5], "vix_close"] = 18.0
    vix9d = _index_frame([20.0] * 7)
    vix3m = _index_frame([25.0] * 7)
    term = build_term_structure_trace(daily, vix9d, vix3m)
    guarded, active = apply_backwardation_guard(daily, _weights(daily), term)

    state2_date = daily.index[6]
    assert not active.loc[state2_date]
    assert guarded.loc[state2_date, "TQQQ"] == pytest.approx(0.75)
    assert guarded.loc[state2_date, "QQQ"] == pytest.approx(0.25)
