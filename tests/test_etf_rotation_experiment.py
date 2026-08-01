from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import (
    RotationConfig,
    build_signal_frame,
    conditional_asset_metrics,
    generate_decision_states,
    prepare_rotation_data,
    recovery_event_study,
    run_buy_and_hold,
    run_rotation_backtest,
)


def _bars(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(values))
    close = np.asarray(values, dtype=float)
    return pd.DataFrame({"date": dates, "open": close, "close": close})


def _three_asset_bars(qqq_values: list[float]) -> dict[str, pd.DataFrame]:
    qqq = _bars(qqq_values)
    qqqi = qqq.copy()
    qqqi[["open", "close"]] = 50.0 + (qqq[["open", "close"]] - qqq["close"].iloc[0]) * 0.35
    tqqq = qqq.copy()
    tqqq[["open", "close"]] = 30.0 + (qqq[["open", "close"]] - qqq["close"].iloc[0]) * 1.8
    return {"QQQI": qqqi, "QQQ": qqq, "TQQQ": tqqq}


def test_position_is_one_session_lagged_from_close_decision() -> None:
    values = list(np.linspace(100, 120, 80))
    config = RotationConfig(ma_long=20, ma_short=5, high_window=20, bollinger_window=5)
    prepared = prepare_rotation_data(_three_asset_bars(values), config)
    result = run_rotation_backtest(prepared, config, version="A")
    expected = result.daily["decision_state"].shift(1).fillna(0).astype(int)
    pd.testing.assert_series_equal(result.daily["position_state"], expected, check_names=False)


def test_switch_cost_uses_two_legs_and_initial_entry_one_leg() -> None:
    values = list(np.linspace(100, 120, 45)) + list(np.linspace(119, 70, 30))
    config = RotationConfig(
        ma_long=20,
        ma_short=5,
        high_window=20,
        bollinger_window=5,
        n_rise=2,
        transaction_cost_bps_per_leg=10.0,
    )
    prepared = prepare_rotation_data(_three_asset_bars(values), config)
    result = run_rotation_backtest(prepared, config, version="A")
    assert result.daily["turnover_legs"].iloc[0] == 1.0
    switches = result.daily.loc[result.daily["turnover_legs"].eq(2.0)]
    assert not switches.empty
    assert np.allclose(switches["transaction_cost"], 0.002)


def test_version_b_does_not_jump_directly_from_qqqi_to_tqqq() -> None:
    index = pd.bdate_range("2024-01-01", periods=4)
    signal = pd.DataFrame(
        {
            "enter_attack": [False, True, False, False],
            "enter_leveraged": [False, True, True, False],
            "defensive_break": [False, False, False, False],
            "exit_leveraged": [False, False, False, True],
            "ma_short_falling": [False] * 4,
        },
        index=index,
    )
    states = generate_decision_states(signal, RotationConfig(), version="B")
    assert states["decision_state"].tolist() == [0, 1, 2, 1]


def test_signal_history_has_no_dependency_on_future_rows() -> None:
    values = list(np.linspace(100, 130, 80))
    config = RotationConfig(ma_long=20, ma_short=5, high_window=20, bollinger_window=5)
    original = build_signal_frame(_bars(values), config)
    changed_values = values.copy()
    changed_values[-5:] = [10, 11, 12, 13, 14]
    changed = build_signal_frame(_bars(changed_values), config)
    pd.testing.assert_frame_equal(original.iloc[:-5], changed.iloc[:-5])


def test_buy_and_hold_and_rotation_share_the_same_return_window() -> None:
    values = list(np.linspace(100, 125, 70))
    config = RotationConfig(ma_long=20, ma_short=5, high_window=20, bollinger_window=5)
    prepared = prepare_rotation_data(_three_asset_bars(values), config)
    baseline = run_buy_and_hold(prepared, config, symbol="QQQ")
    rotation = run_rotation_backtest(prepared, config, version="B")
    assert baseline.metrics["observations"] == rotation.metrics["observations"]
    assert baseline.metrics["start_date"] == rotation.metrics["start_date"]
    assert baseline.metrics["end_date"] == rotation.metrics["end_date"]


def test_conditional_metrics_start_after_regime_confirmation() -> None:
    index = pd.bdate_range("2024-01-01", periods=3)
    prepared = pd.DataFrame(
        {
            "regime": ["weak_below_ma200", "transition", "transition"],
            "QQQI_next_open_return": [0.90, 0.01, 0.02],
            "QQQ_next_open_return": [0.80, 0.03, 0.04],
        },
        index=index,
    )
    table = conditional_asset_metrics(prepared)
    weak = table.loc["weak_below_ma200"]
    assert weak.loc["QQQI", "sessions"] == 1
    assert np.isclose(weak.loc["QQQI", "cumulative_return"], 0.01)
    assert np.isclose(weak.loc["QQQ", "cumulative_return"], 0.03)


def test_recovery_event_starts_at_next_open_after_cross_confirmation() -> None:
    index = pd.bdate_range("2024-01-01", periods=4)
    prepared = pd.DataFrame(
        {
            "qqq_close": [99.0, 101.0, 102.0, 103.0],
            "ma_long": [100.0, 100.0, 100.0, 100.0],
            "QQQI_next_open_return": [0.90, 0.80, 0.01, 0.02],
            "QQQ_next_open_return": [0.90, 0.70, 0.03, 0.04],
        },
        index=index,
    )
    events = recovery_event_study(prepared, horizon_sessions=1)
    assert len(events) == 1
    assert events.loc[0, "event_date"] == index[1]
    assert events.loc[0, "entry_date"] == index[2]
    assert np.isclose(events.loc[0, "QQQI_return"], 0.01)
    assert np.isclose(events.loc[0, "QQQ_return"], 0.03)
