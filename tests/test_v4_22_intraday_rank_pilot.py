from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.v4_22_intraday_rank_pilot import (
    _build_exact_overlay_label,
    _strategy_daily,
    _trailing_percentile,
    fit_chronological_pilot,
)


def _contract() -> dict:
    features = [f"f{i}" for i in range(10)]
    return {
        "boundaries": {"transaction_cost_bps_per_turnover_unit": 10.0},
        "features": {"names": features},
        "model": {
            "estimator": "LogisticRegression",
            "penalty": "l2",
            "C": 1.0,
            "solver": "liblinear",
            "class_weight": "balanced",
            "max_iter": 1000,
            "random_state": 0,
            "imputer": "median",
            "training_score_percentile_trigger": 0.80,
        },
        "training": {"minimum_complete_training_events": 40},
        "outer_folds": [
            {
                "fold": "fold_a",
                "train_start": "2024-01-01",
                "train_end": "2024-03-31",
                "test_start": "2024-04-01",
                "test_end": "2024-04-30",
            },
            {
                "fold": "fold_b",
                "train_start": "2024-01-01",
                "train_end": "2024-04-30",
                "test_start": "2024-05-01",
                "test_end": "2024-05-31",
            },
        ],
    }


def test_trailing_percentile_uses_prior_observations_only():
    index = pd.date_range("2024-01-01", periods=25, freq="D")
    values = pd.Series(np.arange(25, dtype=float), index=index)
    original = _trailing_percentile(values, window=60, minimum=20)
    changed = values.copy()
    changed.iloc[-1] = -1000.0
    revised = _trailing_percentile(changed, window=60, minimum=20)
    pd.testing.assert_series_equal(original.iloc[:-1], revised.iloc[:-1])
    assert original.iloc[20] == 1.0
    assert revised.iloc[-1] == 0.0


def test_exact_overlay_label_includes_switch_and_next_reconciliation_costs():
    index = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
    frame = pd.DataFrame(
        {
            "QQQ_open": [100.0, 102.0],
            "QQQ_opening_close": [101.0, 103.0],
            "QQQ_next_open": [104.0, np.nan],
            "TQQQ_open": [50.0, 51.0],
            "TQQQ_opening_close": [51.5, 51.5],
            "TQQQ_next_open": [50.5, np.nan],
        },
        index=index,
    )
    baseline = pd.DataFrame(index=index)
    baseline["weight_QQQI"] = [0.0, 0.5]
    baseline["weight_QQQ"] = [0.25, 0.5]
    baseline["weight_TQQQ"] = [0.75, 0.0]
    baseline["net_return"] = [0.0, 0.0]
    baseline["turnover_units"] = [0.0, 1.0]
    result = _build_exact_overlay_label(frame, baseline, _contract())
    row = result.iloc[0]
    assert row["switch_turnover_units"] > 1.0
    assert row["overlay_next_reconcile_turnover_units"] == 1.0
    assert row["baseline_next_reconcile_turnover_units"] > 0.0
    assert np.isfinite(row["delever_to_qqq_net_advantage"])
    assert row["delever_positive"] == (
        row["delever_to_qqq_net_advantage"] > 0.0
    )


def _model_frame() -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", "2024-05-31")
    frame = pd.DataFrame(index=index)
    signal = np.sin(np.arange(len(index)) / 3.0)
    for position in range(10):
        frame[f"f{position}"] = signal + position * 0.01
    frame["delever_to_qqq_net_advantage"] = 0.01 * signal
    frame["delever_positive"] = frame[
        "delever_to_qqq_net_advantage"
    ].gt(0.0)
    frame["baseline_official_net_return"] = 0.001
    frame["incremental_turnover_units"] = 1.5
    frame["switch_turnover_units"] = 1.5
    frame["baseline_next_reconcile_turnover_units"] = 0.0
    frame["overlay_next_reconcile_turnover_units"] = 1.0
    return frame


def test_chronological_model_uses_training_threshold_and_untouched_test_rows():
    frame = _model_frame()
    predictions, coverage, coefficients, cosines = fit_chronological_pilot(
        frame, tuple(f"f{i}" for i in range(10)), _contract()
    )
    assert coverage["trainable"].all()
    assert len(predictions) == int(coverage["test_events"].sum())
    for fold, sample in predictions.groupby("fold"):
        threshold = sample["training_score_threshold"].unique()
        assert len(threshold) == 1
        declared = next(item for item in _contract()["outer_folds"] if item["fold"] == fold)
        assert sample.index.min() >= pd.Timestamp(declared["test_start"])
        assert sample.index.max() <= pd.Timestamp(declared["test_end"])
    assert set(coefficients["feature"]) == {f"f{i}" for i in range(10)}
    assert len(cosines) == 1


def test_strategy_daily_changes_only_declared_trigger_dates():
    index = pd.bdate_range("2024-01-01", periods=5)
    baseline = pd.DataFrame(
        {
            "net_return": [0.01, -0.02, 0.01, 0.0, 0.01],
            "turnover_units": [0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=index,
    )
    frame = pd.DataFrame(
        {"delever_to_qqq_net_advantage": [0.1, 0.2]},
        index=index[[1, 3]],
    )
    result = _strategy_daily(
        baseline, frame, pd.DatetimeIndex([index[1]]), name="pilot"
    )
    assert result.loc[index[1], "net_return"] == -0.02 + 0.1
    assert result.loc[index[3], "net_return"] == 0.0
    assert result["overlay_trigger"].sum() == 1
