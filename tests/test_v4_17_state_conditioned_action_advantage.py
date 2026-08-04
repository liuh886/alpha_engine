from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_17_state_conditioned_action_advantage import (
    _action_eligible,
    _state_features,
    action_novelty_l1,
    build_state_conditioned_frames,
    select_novel_action_events,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_state_conditioned_action_advantage_v4_17_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _bars(symbol: str, index: pd.DatetimeIndex, scale: float) -> pd.DataFrame:
    location = np.arange(len(index), dtype=float)
    close = scale * (100.0 + 0.06 * location + 3.0 * np.sin(location / 17.0))
    open_price = close * (1.0 + 0.001 * np.cos(location / 9.0))
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
    proxy = _baseline(index)
    actual = _baseline(index)
    return bars, proxy, actual


def test_next_open_state_features_equal_following_executed_baseline_row() -> None:
    _, proxy, _ = _inputs()
    state = _state_features(proxy, proxy.index)
    for location in range(len(proxy) - 1):
        date = proxy.index[location]
        next_date = proxy.index[location + 1]
        assert state.loc[date, "next_open_position_state"] == proxy.loc[
            next_date, "position_state"
        ]
        for asset in ("QQQI", "QQQ", "TQQQ"):
            assert state.loc[date, f"next_open_weight_{asset}"] == proxy.loc[
                next_date, f"weight_{asset}"
            ]


def test_state_conditioned_schema_has_exactly_fifty_nine_inputs() -> None:
    bars, proxy, actual = _inputs()
    proxy_frame, actual_frame, features, targets = build_state_conditioned_frames(
        bars, proxy, actual, _contract()
    )
    assert len(features) == 59
    assert len(set(features)) == 59
    assert len(targets) == 4
    assert proxy_frame.columns.is_unique
    assert actual_frame.columns.is_unique
    state_interactions = [name for name in features if "next_open_state_" in name and "__" in name]
    assert len(state_interactions) == 24


def _prediction_rows() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=36, freq="B")
    state = np.tile([0, 1, 2], 12)
    frame = pd.DataFrame(index=index)
    frame["next_open_position_state"] = state
    frame["next_open_weight_QQQI"] = np.where(state == 0, 1.0, np.where(state == 1, 0.5, 0.0))
    frame["next_open_weight_QQQ"] = np.where(state == 1, 0.5, np.where(state == 2, 0.25, 0.0))
    frame["next_open_weight_TQQQ"] = np.where(state == 2, 0.75, 0.0)
    frame["qqq_distance_ma20"] = 0.01
    frame["qqq_distance_ma200"] = 0.10
    frame["voo_distance_ma200"] = 0.10
    frame["vol_max_percentile_252"] = 0.50
    frame["fold"] = "unit"
    for action, specification in _contract()["actions"].items():
        frame[f"predicted_{action}"] = 0.0
        frame[specification["target"]] = 0.01
    return frame


def test_proxy_novelty_excludes_core_in_states_zero_one_and_acceleration_in_state_two() -> None:
    frame = _prediction_rows()
    for state in (0, 1):
        mask = frame["next_open_position_state"].eq(state)
        assert action_novelty_l1(frame.loc[mask], "nasdaq_core", _contract()).eq(0.0).all()
        assert not _action_eligible(frame.loc[mask], "nasdaq_core", _contract()).any()
    state_two = frame["next_open_position_state"].eq(2)
    assert action_novelty_l1(
        frame.loc[state_two], "nasdaq_acceleration", _contract()
    ).eq(0.0).all()
    assert not _action_eligible(
        frame.loc[state_two], "nasdaq_acceleration", _contract()
    ).any()


def test_cash_and_broad_equity_are_novel_in_all_states() -> None:
    frame = _prediction_rows()
    for action in ("cash_defense", "broad_equity"):
        novelty = action_novelty_l1(frame, action, _contract())
        assert novelty.ge(0.50).all()


def test_selector_never_emits_redundant_action_state_cell() -> None:
    frame = _prediction_rows()
    for date, state in frame["next_open_position_state"].items():
        if state in (0, 1):
            frame.loc[date, "predicted_nasdaq_core"] = 0.02
        else:
            frame.loc[date, "predicted_nasdaq_acceleration"] = 0.02
    events = select_novel_action_events(frame, _contract(), sample="unit")
    assert events.empty
    assert "baseline_state" in events.columns


def test_selector_emits_only_fresh_novel_threshold_crossing() -> None:
    frame = _prediction_rows()
    index = frame.index
    state_zero_dates = frame.index[frame["next_open_position_state"].eq(0)]
    first = state_zero_dates[2]
    next_same_state = state_zero_dates[3]
    frame.loc[first, "predicted_nasdaq_acceleration"] = 0.010
    frame.loc[first, "predicted_cash_defense"] = 0.004
    frame.loc[next_same_state, "predicted_nasdaq_acceleration"] = 0.010
    frame.loc[next_same_state, "predicted_cash_defense"] = 0.004
    events = select_novel_action_events(frame, _contract(), sample="unit")
    acceleration = events.loc[
        events["event_family"].eq("nasdaq_acceleration")
    ]
    assert len(acceleration) == 1
    event = acceleration.iloc[0]
    assert event["signal_close_date"] == first
    assert event["baseline_state"] == 0
    assert event["novelty_l1"] >= 0.50
    assert event["execution_date"] == index[index.get_loc(first) + 1]
