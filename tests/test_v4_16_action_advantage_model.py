from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_16_action_advantage_model import (
    ACTION_KEYS,
    _embargo_train_end,
    _model_pipeline,
    select_advantage_events,
)
from src.research.v4_16_action_advantage_runtime import (
    build_action_advantage_frame,
)

CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _bars(symbol: str, index: pd.DatetimeIndex, scale: float) -> pd.DataFrame:
    location = np.arange(len(index), dtype=float)
    close = scale * (
        100.0 + 0.08 * location + 4.0 * np.sin(location / 19.0)
    )
    open_price = close * (1.0 + 0.001 * np.cos(location / 11.0))
    if symbol in {"^VIX", "^VXN"}:
        base = 20.0 if symbol == "^VIX" else 25.0
        close = base + 4.0 * np.sin(location / 17.0)
        open_price = close * 0.999
    return pd.DataFrame({"date": index, "open": open_price, "close": close})


def _inputs() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    index = pd.date_range("2010-01-04", periods=720, freq="B")
    bars = {
        "QQQ": _bars("QQQ", index, 1.0),
        "TQQQ": _bars("TQQQ", index, 1.8),
        "VOO": _bars("VOO", index, 0.9),
        "BIL": _bars("BIL", index, 0.8),
        "^VIX": _bars("^VIX", index, 1.0),
        "^VXN": _bars("^VXN", index, 1.0),
    }
    baseline = pd.DataFrame(index=index)
    baseline["net_return"] = 0.001
    return bars, baseline


def test_frame_has_fixed_features_interactions_and_global_sampling() -> None:
    bars, baseline = _inputs()
    frame, features, targets = build_action_advantage_frame(
        bars, baseline, _contract()
    )
    assert len(features) == 29
    assert len(set(features)) == 29
    assert len(targets) == 4
    assert tuple(targets) == tuple(
        _contract()["actions"][action]["target"] for action in ACTION_KEYS
    )
    sampled_positions = np.flatnonzero(
        frame["global_training_sample"].to_numpy(dtype=bool)
    )
    assert sampled_positions[0] == 0
    assert np.diff(sampled_positions).tolist() == [10] * (
        len(sampled_positions) - 1
    )


def test_action_label_is_next_open_advantage_less_frozen_label_cost() -> None:
    bars, baseline = _inputs()
    frame, _, _ = build_action_advantage_frame(bars, baseline, _contract())
    valid = frame[
        ["forward_bil_10d", "cash_defense_advantage_10d"]
    ].dropna()
    date = valid.index[10]
    location = frame.index.get_loc(date)
    baseline_forward = (1.001**10) - 1.0
    expected = (
        float(frame.iloc[location]["forward_bil_10d"])
        - baseline_forward
        - 0.002
    )
    assert np.isclose(
        frame.loc[date, "cash_defense_advantage_10d"], expected
    )


def test_model_pipeline_is_fixed_ridge_alpha_100() -> None:
    pipeline = _model_pipeline(_contract())
    ridge = pipeline.named_steps["model"]
    assert ridge.alpha == 100.0
    assert ridge.fit_intercept is True
    assert list(pipeline.named_steps) == ["imputer", "scaler", "model"]


def test_embargo_end_is_at_least_ten_sessions_before_test() -> None:
    index = pd.date_range("2014-01-02", periods=800, freq="B")
    test_start = index[500]
    end = _embargo_train_end(
        index,
        test_start,
        declared_train_end=index[499],
        embargo_sessions=10,
    )
    end_location = int(index.get_loc(end))
    test_location = int(index.get_loc(test_start))
    assert test_location - end_location >= 11


def _prediction_frame() -> pd.DataFrame:
    index = pd.date_range("2020-01-02", periods=24, freq="B")
    frame = pd.DataFrame(index=index)
    for action in ACTION_KEYS:
        frame[f"predicted_{action}"] = 0.0
        frame[_contract()["actions"][action]["target"]] = 0.01
    frame["qqq_distance_ma20"] = 0.01
    frame["qqq_distance_ma200"] = 0.10
    frame["voo_distance_ma200"] = 0.10
    frame["vol_max_percentile_252"] = 0.50
    frame["fold"] = "unit"
    return frame


def test_event_requires_fresh_threshold_and_margin_crossing() -> None:
    frame = _prediction_frame()
    index = frame.index
    frame.loc[index[2:6], "predicted_cash_defense"] = 0.010
    frame.loc[index[2:6], "predicted_nasdaq_core"] = 0.004
    frame.loc[index[12], "predicted_cash_defense"] = 0.010
    frame.loc[index[12], "predicted_nasdaq_core"] = 0.009
    events = select_advantage_events(frame, _contract(), sample="unit")
    cash = events.loc[events["event_family"].eq("cash_defense")]
    assert len(cash) == 1
    assert cash.iloc[0]["signal_close_date"] == index[2]
    assert cash.iloc[0]["execution_date"] == index[3]
    assert cash.iloc[0]["holding_sessions"] == 10
    assert cash.iloc[0]["predicted_margin"] >= 0.0025


def test_acceleration_eligibility_blocks_extended_or_stressed_signal() -> None:
    frame = _prediction_frame()
    index = frame.index
    frame.loc[index[2], "predicted_nasdaq_acceleration"] = 0.02
    frame.loc[index[2], "qqq_distance_ma20"] = 0.06
    frame.loc[index[10], "predicted_nasdaq_acceleration"] = 0.02
    frame.loc[index[10], "vol_max_percentile_252"] = 0.90
    events = select_advantage_events(frame, _contract(), sample="unit")
    assert not events["event_family"].eq("nasdaq_acceleration").any()


def test_broad_equity_requires_voo_above_ma200() -> None:
    frame = _prediction_frame()
    index = frame.index
    frame.loc[index[2], "predicted_broad_equity"] = 0.02
    frame.loc[index[2], "voo_distance_ma200"] = -0.01
    frame.loc[index[12], "predicted_broad_equity"] = 0.02
    frame.loc[index[12], "voo_distance_ma200"] = 0.01
    events = select_advantage_events(frame, _contract(), sample="unit")
    broad = events.loc[events["event_family"].eq("broad_equity")]
    assert len(broad) == 1
    assert broad.iloc[0]["signal_close_date"] == index[12]
