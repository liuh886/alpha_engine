from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_xgb_v1_1 import (
    BASE_FEATURE_NAMES,
    TARGET_COLUMN,
    XGBTimeSeriesConfig,
    build_momentum_dataset,
    build_xgb_position,
    factor_diagnostics,
    map_prediction_to_position,
    walk_forward_xgb,
)


def _synthetic_ohlcv(periods: int = 1800) -> pd.DataFrame:
    index = pd.bdate_range("2010-01-04", periods=periods)
    rng = np.random.default_rng(503)
    regime = np.where((np.arange(periods) // 140) % 2 == 0, 0.0010, -0.0002)
    returns = regime + rng.normal(0.0, 0.018, periods)
    close = 20.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.0025, periods))
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0.001, 0.015, periods))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0.001, 0.015, periods))
    return pd.DataFrame(
        {
            "date": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        }
    )


def test_forward_target_starts_next_open_and_spans_ten_sessions() -> None:
    frame = _synthetic_ohlcv(600)
    dataset, _ = build_momentum_dataset(frame)
    opens = dataset["open"]
    position = 300
    expected = opens.iloc[position + 11] / opens.iloc[position + 1] - 1.0
    assert np.isclose(dataset[TARGET_COLUMN].iloc[position], expected)


def test_future_mutation_cannot_change_prior_momentum_features() -> None:
    original = _synthetic_ohlcv(900)
    dataset_a, features_a = build_momentum_dataset(original)
    changed = original.copy()
    price_columns = ["open", "high", "low", "close"]
    changed.loc[changed.index >= 820, price_columns] *= 1.7
    changed.loc[changed.index >= 820, "volume"] *= 2
    dataset_b, features_b = build_momentum_dataset(changed)
    assert features_a == features_b
    cutoff = dataset_a.index[819]
    pd.testing.assert_frame_equal(
        dataset_a.loc[:cutoff, list(features_a)],
        dataset_b.loc[:cutoff, list(features_b)],
    )


def test_feature_contract_is_complete_without_benchmark() -> None:
    dataset, features = build_momentum_dataset(_synthetic_ohlcv(700))
    assert features == BASE_FEATURE_NAMES
    assert set(features).issubset(dataset.columns)
    assert len(features) >= 40


def test_position_mappings_are_frozen() -> None:
    assert map_prediction_to_position(0.01, "xgb_binary_0_100") == 1.0
    assert map_prediction_to_position(-0.01, "xgb_binary_0_100") == 0.0
    assert map_prediction_to_position(0.01, "xgb_core75_100") == 1.0
    assert map_prediction_to_position(-0.01, "xgb_core75_100") == 0.75
    assert map_prediction_to_position(0.03, "xgb_four_state") == 1.0
    assert map_prediction_to_position(0.01, "xgb_four_state") == 0.75
    assert map_prediction_to_position(-0.01, "xgb_four_state") == 0.50
    assert map_prediction_to_position(-0.03, "xgb_four_state") == 0.0


def test_decision_positions_hold_between_ten_session_predictions() -> None:
    index = pd.bdate_range("2023-01-02", periods=35)
    predictions = pd.DataFrame(
        {"predicted_forward_return_10": [0.03, -0.01, -0.03]},
        index=[index[0], index[10], index[20]],
    )
    position = build_xgb_position(index, predictions, "xgb_four_state")
    assert position.iloc[:10].eq(1.0).all()
    assert position.iloc[10:20].eq(0.50).all()
    assert position.iloc[20:].eq(0.0).all()


def test_walk_forward_manifest_enforces_label_embargo() -> None:
    dataset, features = build_momentum_dataset(_synthetic_ohlcv(1500))
    result = walk_forward_xgb(
        dataset,
        features,
        training_start="2011-01-01",
        prediction_start="2014-06-01",
        prediction_end=dataset.index[-1].strftime("%Y-%m-%d"),
        config=XGBTimeSeriesConfig(
            num_boost_round=5,
            minimum_training_samples=300,
            decision_step_sessions=10,
            refit_step_sessions=20,
            label_horizon_sessions=10,
        ),
    )
    assert not result.predictions.empty
    for row in result.predictions.itertuples():
        prediction_position = dataset.index.get_loc(row.Index)
        training_end_position = dataset.index.get_loc(row.training_end)
        assert training_end_position <= prediction_position - 11
    assert result.fit_manifest["embargo_sessions"].eq(10).all()


def test_factor_selection_uses_development_only() -> None:
    dataset, features = build_momentum_dataset(_synthetic_ohlcv(1700))
    windows = {
        "development_start": "2012-01-01",
        "development_end": "2014-12-31",
        "validation_start": "2015-01-01",
        "validation_end": "2015-12-31",
        "retrospective_holdout_start": "2016-01-01",
        "retrospective_holdout_end": dataset.index[-12].strftime("%Y-%m-%d"),
    }
    _, selection_a, _ = factor_diagnostics(dataset, features, windows)
    changed = dataset.copy()
    changed.loc["2015-01-01":, TARGET_COLUMN] *= -7.0
    _, selection_b, _ = factor_diagnostics(changed, features, windows)
    assert selection_a == selection_b
