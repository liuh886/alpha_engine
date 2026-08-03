from __future__ import annotations

import pandas as pd

from src.research.v4_2_donor_state2_sgov_tqqq_runtime import (
    _assert_scope_probability_coverage,
    _overlapping_predictions,
    build_target_state2_prediction_rows,
)


def test_target_prediction_rows_do_not_require_cash_outcome_labels() -> None:
    index = pd.date_range("2018-01-02", periods=9, freq="B")
    daily = pd.DataFrame(
        {
            "position_state": [1, 1, 2, 2, 2, 1, 2, 2, 1],
        },
        index=index,
    )
    features = ["feature_a", "feature_b"]
    feature_frame = pd.DataFrame(
        {
            "feature_a": range(len(index)),
            "feature_b": [0.5] * len(index),
            "cash_next_open_return": [float("nan")] * len(index),
        },
        index=index,
    )
    rows = build_target_state2_prediction_rows(
        daily, feature_frame, features=features
    )
    assert len(rows) == 2
    assert rows["execution_date"].tolist() == [index[2], index[6]]
    assert rows["episode_end_date"].tolist() == [index[4], index[7]]
    assert rows["feature_a"].tolist() == [1.0, 5.0]


def test_scope_selection_keeps_episode_started_before_scope() -> None:
    predictions = pd.DataFrame(
        {
            "asset_episode_id": ["QQQ_001", "QQQ_002"],
            "execution_date": pd.to_datetime(["2018-12-28", "2019-06-03"]),
            "episode_end_date": pd.to_datetime(["2019-01-08", "2019-06-10"]),
            "probability": [0.7, 0.3],
            "probability_bucket": ["high", "low"],
        }
    )
    selected = _overlapping_predictions(
        predictions,
        start=pd.Timestamp("2019-01-02"),
        end=pd.Timestamp("2019-12-31"),
    )
    assert selected["asset_episode_id"].tolist() == ["QQQ_001", "QQQ_002"]


def test_scope_probability_coverage_accepts_cross_boundary_episode() -> None:
    index = pd.date_range("2019-01-02", periods=6, freq="B")
    baseline = type("Baseline", (), {})()
    baseline.daily = pd.DataFrame(
        {"position_state": [2, 2, 1, 1, 2, 2]}, index=index
    )
    predictions = pd.DataFrame(
        {
            "asset_episode_id": ["QQQ_001", "QQQ_002"],
            "execution_date": pd.to_datetime(["2018-12-28", index[4]]),
            "episode_end_date": pd.to_datetime([index[1], index[5]]),
            "probability": [0.7, 0.3],
            "probability_bucket": ["high", "low"],
        }
    )
    _assert_scope_probability_coverage(baseline, predictions, index)
