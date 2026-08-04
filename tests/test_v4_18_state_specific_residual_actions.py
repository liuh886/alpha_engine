from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_18_state_specific_residual_actions import (
    _state_actions,
    build_state_partitioned_frames,
    select_state_specific_events,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_state_specific_residual_actions_v4_18_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _bars(symbol: str, index: pd.DatetimeIndex, scale: float) -> pd.DataFrame:
    location = np.arange(len(index), dtype=float)
    close = scale * (100.0 + 0.05 * location + 3.0 * np.sin(location / 17.0))
    open_price = close * (1.0 + 0.001 * np.cos(location / 11.0))
    if symbol in {"^VIX", "^VXN"}:
        base = 20.0 if symbol == "^VIX" else 25.0
        close = base + 4.0 * np.sin(location / 15.0)
        open_price = close * 0.999
    return pd.DataFrame({"date": index, "open": open_price, "close": close})


def _baseline(index: pd.DatetimeIndex) -> pd.DataFrame:
    state = np.tile([0, 1, 2], int(np.ceil(len(index) / 3)))[: len(index)]
    daily = pd.DataFrame(index=index)
    daily["position_state"] = state
    daily["weight_QQQI"] = np.where(state == 0, 1.0, np.where(state == 1, 0.5, 0.0))
    daily["weight_QQQ"] = np.where(state == 1, 0.5, np.where(state == 2, 0.25, 0.0))
    daily["weight_TQQQ"] = np.where(state == 2, 0.75, 0.0)
    daily["net_return"] = 0.001
    return daily


def _inputs() -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2010-01-04", periods=760, freq="B")
    bars = {
        "QQQ": _bars("QQQ", index, 1.0),
        "TQQQ": _bars("TQQQ", index, 1.8),
        "VOO": _bars("VOO", index, 0.9),
        "BIL": _bars("BIL", index, 0.8),
        "SGOV": _bars("SGOV", index, 0.8),
        "QQQI": _bars("QQQI", index, 0.95),
        "^VIX": _bars("^VIX", index, 1.0),
        "^VXN": _bars("^VXN", index, 1.0),
    }
    return bars, _baseline(index), _baseline(index)


def test_state_action_sets_are_exact_and_novel() -> None:
    contract = _contract()
    assert _state_actions(contract, 0) == (
        "cash_defense",
        "broad_equity",
        "nasdaq_acceleration",
    )
    assert _state_actions(contract, 1) == _state_actions(contract, 0)
    assert _state_actions(contract, 2) == (
        "cash_defense",
        "broad_equity",
        "nasdaq_core",
    )
    assert "nasdaq_core" not in _state_actions(contract, 0)
    assert "nasdaq_core" not in _state_actions(contract, 1)
    assert "nasdaq_acceleration" not in _state_actions(contract, 2)


def test_partitioned_frame_keeps_twenty_nine_market_inputs() -> None:
    bars, proxy, actual = _inputs()
    proxy_frame, actual_frame, features, targets = build_state_partitioned_frames(
        bars, proxy, actual, _contract()
    )
    assert len(features) == 29
    assert len(set(features)) == 29
    assert len(targets) == 4
    assert "next_open_position_state" in proxy_frame
    assert "next_open_position_state" in actual_frame
    sampled = np.flatnonzero(proxy_frame["global_training_sample"].to_numpy(dtype=bool))
    assert sampled[0] == 0
    assert np.diff(sampled).tolist() == [10] * (len(sampled) - 1)


def _prediction_frame() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=45, freq="B")
    states = np.tile([0, 1, 2], 15)
    frame = pd.DataFrame(index=index)
    frame["next_open_position_state"] = states
    frame["qqq_distance_ma20"] = 0.01
    frame["qqq_distance_ma200"] = 0.10
    frame["voo_distance_ma200"] = 0.10
    frame["vol_max_percentile_252"] = 0.50
    frame["fold"] = "unit"
    for action, specification in _contract()["actions"].items():
        frame[f"predicted_{action}"] = np.nan
        frame[specification["target"]] = 0.01
    for state in (0, 1, 2):
        mask = frame["next_open_position_state"].eq(state)
        for action in _state_actions(_contract(), state):
            frame.loc[mask, f"predicted_{action}"] = 0.0
    return frame


def test_selector_never_uses_action_outside_frozen_state_set() -> None:
    frame = _prediction_frame()
    for date, state in frame["next_open_position_state"].items():
        forbidden = "nasdaq_core" if state in (0, 1) else "nasdaq_acceleration"
        frame.loc[date, f"predicted_{forbidden}"] = 0.05
    events = select_state_specific_events(frame, _contract(), sample="unit")
    assert events.empty


def test_selector_emits_novel_state_action_on_fresh_crossing() -> None:
    frame = _prediction_frame()
    state_two_dates = frame.index[frame["next_open_position_state"].eq(2)]
    signal = state_two_dates[2]
    frame.loc[signal, "predicted_nasdaq_core"] = 0.010
    frame.loc[signal, "predicted_cash_defense"] = 0.004
    events = select_state_specific_events(frame, _contract(), sample="unit")
    core = events.loc[events["event_family"].eq("nasdaq_core")]
    assert len(core) == 1
    event = core.iloc[0]
    assert event["baseline_state"] == 2
    assert event["signal_close_date"] == signal
    assert event["predicted_margin"] >= 0.0025


def test_acceleration_asset_guard_remains_frozen() -> None:
    frame = _prediction_frame()
    state_zero_dates = frame.index[frame["next_open_position_state"].eq(0)]
    extended = state_zero_dates[2]
    stressed = state_zero_dates[4]
    frame.loc[extended, "predicted_nasdaq_acceleration"] = 0.02
    frame.loc[extended, "qqq_distance_ma20"] = 0.06
    frame.loc[stressed, "predicted_nasdaq_acceleration"] = 0.02
    frame.loc[stressed, "vol_max_percentile_252"] = 0.90
    events = select_state_specific_events(frame, _contract(), sample="unit")
    assert not events["event_family"].eq("nasdaq_acceleration").any()
