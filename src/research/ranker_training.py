"""Canonical train-and-score primitive for maintained cross-sectional XGBoost rankers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from src.research.daily_ranker import prepare_ranker_frame
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    XGBNativeRankerResult,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)


@dataclass(frozen=True)
class RankerTrainingOutput:
    """One fitted native ranker and its exact governed score trace."""

    fitted: XGBNativeRankerResult
    scores: pd.DataFrame


class RankerTrainingInputError(ValueError):
    """Raised when declared ranker inputs fail pre-fit validation."""


def fit_predict_ranker(
    *,
    expressions: Sequence[str],
    expression_columns: Mapping[str, str],
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test: pd.DataFrame,
    calibration: XGBNativeCalibration,
    context: str,
) -> RankerTrainingOutput:
    """Fit one declared native ranker and emit its model plus score trace."""

    columns = [expression_columns[expression] for expression in expressions]
    train = features_train.loc[:, columns]
    valid, reason = validate_no_nan_inputs(train, context=context)
    if not valid:
        raise RankerTrainingInputError(reason)

    x_rank, y_rank, groups = prepare_ranker_frame(train, returns_train)
    fitted = fit_xgb_native_daily_ranker(
        x_rank,
        y_rank,
        groups,
        calibration=calibration,
    )
    return RankerTrainingOutput(
        fitted=fitted,
        scores=predict_xgb_native_daily_ranker(
            fitted,
            features_test.loc[:, columns],
        ),
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
    """Fit one declared native ranker and return only its governed score trace."""

    return fit_predict_ranker(
        expressions=expressions,
        expression_columns=expression_columns,
        features_train=features_train,
        returns_train=returns_train,
        features_test=features_test,
        calibration=calibration,
        context=context,
    ).scores
