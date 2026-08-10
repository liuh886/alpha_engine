"""Daily ranker wrappers for fixed-ten-day research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.research.xgb_native_calibration import XGBNativeCalibration

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DailyRankerResult:
    """Fitted ranker plus training metadata."""

    model: Any
    feature_names: list[str]
    groups: list[int]
    n_gain_bins: int
    target_type: str = "percentile_gain"
    calibration_identity: dict[str, object] | None = None
    target_top_k: int | None = None
    lambdarank_truncation_level: int | None = None


def percentile_rank_to_gain(
    rank_target: pd.Series,
    *,
    n_bins: int = 5,
) -> pd.Series:
    """Convert valid percentile ranks into integer LambdaRank gain labels."""

    if n_bins < 2:
        raise ValueError("n_bins must be at least 2")
    if rank_target.empty:
        raise ValueError("rank_target must not be empty")

    values = rank_target.astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError(
            "rank_target contains missing or non-finite values; invalid rows "
            "must be removed before gain conversion"
        )
    clipped = values.clip(0.0, 1.0)
    gains = np.floor(clipped * n_bins).clip(0, n_bins - 1).astype(int)
    gains.name = "rank_gain"
    gains.attrs["provenance"] = "processed_daily_rank_gain_target"
    gains.attrs["source"] = rank_target.attrs.get("provenance", "unknown")
    gains.attrs["n_bins"] = n_bins
    return gains


def _validate_ranker_fit_inputs(
    features: pd.DataFrame,
    rank_target: pd.Series,
    groups: list[int],
) -> None:
    """Validate finite, index-aligned ranker inputs before LightGBM import."""
    if features.empty:
        raise ValueError("features must not be empty")
    if not features.index.equals(rank_target.index):
        raise ValueError("features and rank_target must have identical indices")
    if not groups:
        raise ValueError("groups must not be empty")
    if any(size < 2 for size in groups):
        raise ValueError("each ranker group must contain at least two rows")
    if sum(groups) != len(features):
        raise ValueError("sum(groups) must equal the number of training rows")
    feature_values = features.astype(float).to_numpy()
    if not np.isfinite(feature_values).all():
        raise ValueError(
            "features contain missing or non-finite values; invalid rows must "
            "be removed before model fitting"
        )


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

    _validate_ranker_fit_inputs(features, rank_target, groups)

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

    dataset = lgb.Dataset(
        features,
        label=gains.loc[features.index],
        group=groups,
    )
    model = lgb.train(
        model_params,
        dataset,
        num_boost_round=num_boost_round,
    )
    return DailyRankerResult(
        model=model,
        feature_names=[str(item) for item in features.columns],
        groups=list(groups),
        n_gain_bins=n_gain_bins,
    )


def fit_lgbm_daily_topk_ranker(
    features: pd.DataFrame,
    relevance_target: pd.Series,
    groups: list[int],
    *,
    top_k: int = 3,
    params: dict[str, Any] | None = None,
    num_boost_round: int = 100,
) -> DailyRankerResult:
    """Fit one predeclared Top-K-aligned LambdaRank objective.

    The relevance target must contain exactly ``top_k`` binary positives per
    daily group. The objective cutoff is frozen to ``top_k + 3`` so the model
    focuses on the portfolio tail while retaining a small number of additional
    ranking pairs. Structural parameters cannot be overridden through
    ``params``; callers may still provide ordinary tree/calibration settings.
    """

    if top_k < 1:
        raise ValueError("top_k must be positive")
    _validate_ranker_fit_inputs(features, relevance_target, groups)
    if relevance_target.attrs.get("provenance") != "processed_daily_topk_relevance_target":
        raise ValueError(
            "relevance_target provenance must be processed_daily_topk_relevance_target"
        )
    if relevance_target.attrs.get("top_k") != top_k:
        raise ValueError("relevance_target top_k does not match requested top_k")

    values = relevance_target.astype(float).to_numpy()
    if not np.isfinite(values).all() or not np.isin(values, [0.0, 1.0]).all():
        raise ValueError("relevance_target must contain only finite binary labels")
    offset = 0
    for group_size in groups:
        group_values = values[offset : offset + group_size]
        if int(group_values.sum()) != top_k:
            raise ValueError("each daily relevance group must contain exactly top_k positives")
        offset += group_size

    protected = {
        "objective",
        "metric",
        "eval_at",
        "lambdarank_truncation_level",
        "label_gain",
    }
    conflicts = sorted(protected.intersection(params or {}))
    if conflicts:
        raise ValueError(f"Top-K structural ranker parameters cannot be overridden: {conflicts}")

    import lightgbm as lgb

    truncation_level = top_k + 3
    model_params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "eval_at": [top_k],
        "lambdarank_truncation_level": truncation_level,
        "label_gain": [0, 1],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 10,
        "seed": 42,
        "verbosity": -1,
    }
    if params:
        model_params.update(params)

    dataset = lgb.Dataset(
        features,
        label=relevance_target.loc[features.index].astype(int),
        group=groups,
    )
    model = lgb.train(
        model_params,
        dataset,
        num_boost_round=num_boost_round,
    )
    return DailyRankerResult(
        model=model,
        feature_names=[str(item) for item in features.columns],
        groups=list(groups),
        n_gain_bins=2,
        target_type="topk_binary_relevance",
        target_top_k=top_k,
        lambdarank_truncation_level=truncation_level,
    )


def predict_lgbm_daily_ranker(
    result: DailyRankerResult,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Predict ranker scores as a one-column candidate frame."""

    matrix = features.loc[:, result.feature_names]
    scores = pd.DataFrame(
        result.model.predict(matrix),
        index=matrix.index,
        columns=["score"],
    )
    scores.attrs["provenance"] = "out_of_sample_daily_ranker_prediction"
    scores.attrs["model_type"] = "lgbm_lambdarank"
    scores.attrs["n_gain_bins"] = result.n_gain_bins
    scores.attrs["target_type"] = result.target_type
    scores.attrs["target_top_k"] = result.target_top_k
    scores.attrs["lambdarank_truncation_level"] = result.lambdarank_truncation_level
    return scores


# ---------------------------------------------------------------------------
# XGBoost rank:ndcg adapter  (fixed 100-estimator research configuration)
# ---------------------------------------------------------------------------


def fit_xgb_daily_ranker(
    features: pd.DataFrame,
    rank_target: pd.Series,
    groups: list[int],
    *,
    n_gain_bins: int = 5,
    params: dict[str, Any] | None = None,
    num_boost_round: int = 100,
) -> DailyRankerResult:
    """Fit an XGBoost ``rank:ndcg`` model with explicit daily query groups.

    This adapter mirrors the ``fit_lgbm_daily_ranker`` contract: input
    validation, gain conversion, and the returned ``DailyRankerResult``
    shape are identical. The model uses XGBoost's built-in ranking
    objective with group-level NDCG.

    **Structural parameters** that ensure a fair comparison against the
    LightGBM LambdaRank baseline are **protected** — callers cannot
    override ``objective``, ``tree_method``, ``grow_policy``,
    ``max_leaves``, ``max_depth``, ``learning_rate``, or ``seed`` via
    ``params``. The caller supplies ``num_boost_round`` explicitly
    (research convention passes 100).
    """

    protected_fields = {
        "objective",
        "tree_method",
        "grow_policy",
        "max_leaves",
        "max_depth",
        "learning_rate",
        "seed",
    }
    conflicts = sorted(protected_fields.intersection(params or {}))
    if conflicts:
        raise ValueError(f"XGBoost ranker structural parameters cannot be overridden: {conflicts}")

    _validate_ranker_fit_inputs(features, rank_target, groups)

    import xgboost as xgb

    gains = percentile_rank_to_gain(rank_target, n_bins=n_gain_bins)
    model_params: dict[str, Any] = {
        "objective": "rank:ndcg",
        "tree_method": "hist",
        "grow_policy": "lossguide",
        "max_leaves": 31,
        "max_depth": 0,
        "learning_rate": 0.05,
        "seed": 42,
        "verbosity": 0,
    }
    if params:
        model_params.update(params)

    dtrain = xgb.DMatrix(features, label=gains.loc[features.index])
    dtrain.set_group(groups)
    model = xgb.train(
        model_params,
        dtrain,
        num_boost_round=num_boost_round,
    )
    return DailyRankerResult(
        model=model,
        feature_names=[str(item) for item in features.columns],
        groups=list(groups),
        n_gain_bins=n_gain_bins,
    )


def predict_xgb_daily_ranker(
    result: DailyRankerResult,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Predict ranker scores as a one-column candidate frame (XGBoost)."""

    import xgboost as xgb

    matrix = features.loc[:, result.feature_names]
    scores = pd.DataFrame(
        result.model.predict(xgb.DMatrix(matrix)),
        index=matrix.index,
        columns=["score"],
    )
    scores.attrs["provenance"] = "out_of_sample_daily_ranker_prediction"
    scores.attrs["model_type"] = "xgb_rank_ndcg"
    scores.attrs["n_gain_bins"] = result.n_gain_bins
    scores.attrs["target_type"] = result.target_type
    scores.attrs["target_top_k"] = result.target_top_k
    scores.attrs["lambdarank_truncation_level"] = result.lambdarank_truncation_level
    return scores


def fit_xgb_daily_ranker_with_calibration(
    features: pd.DataFrame,
    rank_target: pd.Series,
    groups: list[int],
    *,
    calibration: "XGBNativeCalibration",  # type: ignore[name-defined]
) -> DailyRankerResult:
    """Fit an XGBoost ranker using the explicit native calibration contract.

    This is the #357-compliant path. Every effective parameter is
    declared, identity-bound, and traceable via identity_manifest.
    """
    from src.research.xgb_native_calibration import _validate_fit_inputs

    _validate_fit_inputs(features, rank_target, groups)

    import xgboost as xgb

    gains = percentile_rank_to_gain(rank_target, n_bins=calibration.n_gain_bins)
    dtrain = xgb.DMatrix(features, label=gains.loc[features.index])
    dtrain.set_group(groups)
    model = xgb.train(
        calibration.effective_model_parameters(),
        dtrain,
        num_boost_round=calibration.num_boost_round,
    )
    return DailyRankerResult(
        model=model,
        feature_names=[str(item) for item in features.columns],
        groups=list(groups),
        n_gain_bins=calibration.n_gain_bins,
        calibration_identity=calibration.identity_manifest(),
    )
