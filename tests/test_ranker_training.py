from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.daily_ranker import prepare_ranker_frame
from src.research.ranker_training import (
    RankerTrainingInputError,
    fit_predict_ranker,
    fit_predict_ranker_scores,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)


def test_shared_ranker_training_reproduces_direct_native_sequence() -> None:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    instruments = ["AAA", "BBB", "CCC", "DDD"]
    index = pd.MultiIndex.from_product(
        [dates, instruments],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame(
        {
            "feature_0": np.linspace(-1.0, 1.0, len(index)),
            "feature_1": np.tile([0.4, -0.2, 0.8, -0.6], len(dates)),
            "unused": np.arange(len(index), dtype=float),
        },
        index=index,
    )
    returns = pd.DataFrame(
        {
            "return": np.tile([0.03, -0.01, 0.02, -0.02], len(dates))
            + np.repeat([0.0, 0.005, -0.003], len(instruments)),
        },
        index=index,
    )
    calibration = XGBNativeCalibration(
        n_gain_bins=3,
        num_boost_round=5,
        max_leaves=7,
        learning_rate=0.05,
        seed=42,
    )
    selected = ["feature_0", "feature_1"]

    x_rank, y_rank, groups = prepare_ranker_frame(features.loc[:, selected], returns)
    direct_model = fit_xgb_native_daily_ranker(
        x_rank,
        y_rank,
        groups,
        calibration=calibration,
    )
    direct = predict_xgb_native_daily_ranker(
        direct_model,
        features.loc[:, selected],
    )

    shared = fit_predict_ranker_scores(
        expressions=["expr0", "expr1"],
        expression_columns={"expr0": "feature_0", "expr1": "feature_1"},
        features_train=features,
        returns_train=returns,
        features_test=features,
        calibration=calibration,
        context="ranker-training-equivalence",
    )

    pd.testing.assert_frame_equal(shared, direct, check_exact=True)
    assert shared.attrs == direct.attrs

    output = fit_predict_ranker(
        expressions=["expr0", "expr1"],
        expression_columns={"expr0": "feature_0", "expr1": "feature_1"},
        features_train=features,
        returns_train=returns,
        features_test=features,
        calibration=calibration,
        context="ranker-training-output-equivalence",
    )
    pd.testing.assert_frame_equal(output.scores, direct, check_exact=True)
    assert output.scores.attrs == direct.attrs
    assert output.fitted.identity_manifest == direct_model.identity_manifest
    assert output.fitted.feature_names == direct_model.feature_names


def test_shared_ranker_training_uses_narrow_input_validation_error() -> None:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAA")],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"feature_0": [np.nan]}, index=index)
    returns = pd.DataFrame({"return": [0.01]}, index=index)

    with pytest.raises(RankerTrainingInputError, match="ranker-input"):
        fit_predict_ranker(
            expressions=["expr0"],
            expression_columns={"expr0": "feature_0"},
            features_train=features,
            returns_train=returns,
            features_test=features,
            calibration=XGBNativeCalibration(n_gain_bins=2, num_boost_round=1),
            context="ranker-input",
        )


def test_shared_ranker_training_preserves_downstream_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "AAA"),
            (pd.Timestamp("2025-01-02"), "BBB"),
        ],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"feature_0": [1.0, 2.0]}, index=index)
    returns = pd.DataFrame({"return": [0.01, -0.01]}, index=index)

    def fail_fit(*args: object, **kwargs: object) -> None:
        raise ValueError("fit failed")

    monkeypatch.setattr("src.research.ranker_training.fit_xgb_native_daily_ranker", fail_fit)

    with pytest.raises(ValueError, match="fit failed") as error:
        fit_predict_ranker(
            expressions=["expr0"],
            expression_columns={"expr0": "feature_0"},
            features_train=features,
            returns_train=returns,
            features_test=features,
            calibration=XGBNativeCalibration(n_gain_bins=2, num_boost_round=1),
            context="ranker-fit",
        )
    assert not isinstance(error.value, RankerTrainingInputError)
