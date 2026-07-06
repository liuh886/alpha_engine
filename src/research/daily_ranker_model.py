"""LightGBM daily ranker wrapper for fixed-ten-day research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DailyRankerResult:
    """Fitted ranker plus training metadata."""

    model: Any
    feature_names: list[str]
    groups: list[int]
    n_gain_bins: int


def percentile_rank_to_gain(rank_target: pd.Series, *, n_bins: int = 5) -> pd.Series:
    """Convert percentile ranks into integer gain labels for ranking objectives."""

    if n_bins < 2:
        raise ValueError("n_bins must be at least 2")
    clipped = rank_target.astype(float).clip(0.0, 1.0).fillna(0.5)
    gains = np.floor(clipped * n_bins).clip(0, n_bins - 1).astype(int)
    gains.name = "rank_gain"
    gains.attrs["provenance"] = "processed_daily_rank_gain_target"
    gains.attrs["source"] = rank_target.attrs.get("provenance", "unknown")
    gains.attrs["n_bins"] = n_bins
    return gains


def fit_lgbm_daily_ranker(
    features: pd.DataFrame,
    rank_target: pd.Series,
    groups: list[int],
    *,
    n_gain_bins: int = 5,
    params: dict[str, Any] | None = None,
    num_boost_round: int = 200,
) -> DailyRankerResult:
    """Fit a LightGBM LambdaRank model with explicit daily groups."""

    if sum(groups) != len(features):
        raise ValueError("sum(groups) must equal the number of training rows")

    import lightgbm as lgb

    gains = percentile_rank_to_gain(rank_target, n_bins=n_gain_bins)
    model_params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 10,
        "seed": 42,
        "verbosity": -1,
    }
    if params:
        model_params.update(params)

    dataset = lgb.Dataset(features, label=gains.loc[features.index], group=groups)
    model = lgb.train(model_params, dataset, num_boost_round=num_boost_round)
    return DailyRankerResult(
        model=model,
        feature_names=[str(item) for item in features.columns],
        groups=list(groups),
        n_gain_bins=n_gain_bins,
    )


def predict_lgbm_daily_ranker(result: DailyRankerResult, features: pd.DataFrame) -> pd.DataFrame:
    """Predict ranker scores as a one-column candidate frame."""

    matrix = features.loc[:, result.feature_names]
    scores = pd.DataFrame(result.model.predict(matrix), index=matrix.index, columns=["score"])
    scores.attrs["provenance"] = "out_of_sample_daily_ranker_prediction"
    scores.attrs["model_type"] = "lgbm_lambdarank"
    scores.attrs["n_gain_bins"] = result.n_gain_bins
    return scores
