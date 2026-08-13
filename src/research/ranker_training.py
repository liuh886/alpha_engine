"""Canonical train-and-score primitive for maintained cross-sectional XGBoost rankers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from src.research.daily_ranker import prepare_ranker_frame
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)


def fit_predict_ranker_scores(
    *,
    expressions: Sequence[str],
    expression_columns: Mapping[str, str],
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test: pd.DataFrame,
    calibration: XGBNativeCalibration,
    context: str,
) -> pd.DataFrame:
    """Fit one declared native ranker and emit its score trace without evaluation logic."""

    columns = [expression_columns[expression] for expression in expressions]
    train = features_train.loc[:, columns]
    valid, reason = validate_no_nan_inputs(train, context=context)
    if not valid:
        raise ValueError(reason)

    x_rank, y_rank, groups = prepare_ranker_frame(train, returns_train)
    fitted = fit_xgb_native_daily_ranker(
        x_rank,
        y_rank,
        groups,
        calibration=calibration,
    )
    return predict_xgb_native_daily_ranker(
        fitted,
        features_test.loc[:, columns],
    )
