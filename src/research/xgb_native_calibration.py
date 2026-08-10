"""Explicit, identity-bound XGBoost ranker calibration support.

This module is the first implementation slice for Issue #357. It separates
XGBoost-native parameters from the historical LightGBM-oriented calibration
schema and exposes a deterministic declared/effective parameter manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.research.daily_ranker_model import percentile_rank_to_gain


STRUCTURAL_PARAMETERS: dict[str, object] = {
    "objective": "rank:ndcg",
    "tree_method": "hist",
    "grow_policy": "lossguide",
    "verbosity": 0,
}
NATIVE_PARAMETER_FIELDS: tuple[str, ...] = (
    "max_leaves",
    "max_depth",
    "min_child_weight",
    "learning_rate",
    "subsample",
    "colsample_bytree",
    "reg_alpha",
    "reg_lambda",
    "seed",
)


@dataclass(frozen=True)
class XGBNativeCalibration:
    """One explicit XGBoost ``rank:ndcg`` calibration contract."""

    n_gain_bins: int
    num_boost_round: int
    max_leaves: int = 31
    max_depth: int = 0
    min_child_weight: float = 1.0
    learning_rate: float = 0.05
    subsample: float = 1.0
    colsample_bytree: float = 1.0
    reg_alpha: float = 0.0
    reg_lambda: float = 1.0
    seed: int = 42

    def __post_init__(self) -> None:
        if self.n_gain_bins < 2:
            raise ValueError("n_gain_bins must be at least 2")
        if self.num_boost_round <= 0:
            raise ValueError("num_boost_round must be positive")
        if self.max_leaves <= 1:
            raise ValueError("max_leaves must be greater than 1")
        if self.max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if self.min_child_weight < 0:
            raise ValueError("min_child_weight must be non-negative")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if not 0 < self.subsample <= 1:
            raise ValueError("subsample must be in (0, 1]")
        if not 0 < self.colsample_bytree <= 1:
            raise ValueError("colsample_bytree must be in (0, 1]")
        if self.reg_alpha < 0 or self.reg_lambda < 0:
            raise ValueError("regularization values must be non-negative")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "XGBNativeCalibration":
        """Build a contract while rejecting ignored or unknown fields."""

        allowed = {"n_gain_bins", "num_boost_round", *NATIVE_PARAMETER_FIELDS}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"unknown XGBoost calibration fields: {unknown}")
        missing = [field for field in ("n_gain_bins", "num_boost_round") if field not in raw]
        if missing:
            raise ValueError(f"missing XGBoost calibration fields: {missing}")
        return cls(
            n_gain_bins=int(raw["n_gain_bins"]),
            num_boost_round=int(raw["num_boost_round"]),
            max_leaves=int(raw.get("max_leaves", 31)),
            max_depth=int(raw.get("max_depth", 0)),
            min_child_weight=float(raw.get("min_child_weight", 1.0)),
            learning_rate=float(raw.get("learning_rate", 0.05)),
            subsample=float(raw.get("subsample", 1.0)),
            colsample_bytree=float(raw.get("colsample_bytree", 1.0)),
            reg_alpha=float(raw.get("reg_alpha", 0.0)),
            reg_lambda=float(raw.get("reg_lambda", 1.0)),
            seed=int(raw.get("seed", 42)),
        )

    @property
    def name(self) -> str:
        """Return a candidate identity containing every effective native field."""

        return (
            f"gain{self.n_gain_bins}_round{self.num_boost_round}_"
            f"leaves{self.max_leaves}_depth{self.max_depth}_"
            f"child{self.min_child_weight:g}_lr{self.learning_rate:g}_"
            f"sub{self.subsample:g}_col{self.colsample_bytree:g}_"
            f"alpha{self.reg_alpha:g}_lambda{self.reg_lambda:g}_seed{self.seed}"
        )

    def declared_parameters(self) -> dict[str, int | float]:
        """Return exactly the user-declared model and training parameters."""

        return {
            "n_gain_bins": self.n_gain_bins,
            "num_boost_round": self.num_boost_round,
            "max_leaves": self.max_leaves,
            "max_depth": self.max_depth,
            "min_child_weight": self.min_child_weight,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "seed": self.seed,
        }

    def effective_model_parameters(self) -> dict[str, object]:
        """Return the exact parameter mapping passed to ``xgboost.train``."""

        return {
            **STRUCTURAL_PARAMETERS,
            "max_leaves": self.max_leaves,
            "max_depth": self.max_depth,
            "min_child_weight": self.min_child_weight,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "seed": self.seed,
        }

    def identity_manifest(self) -> dict[str, object]:
        """Return a hash-bound declared/effective identity manifest."""

        declared = self.declared_parameters()
        effective = self.effective_model_parameters()
        payload = {
            "schema_version": "1.0",
            "calibration_name": self.name,
            "declared_parameters": declared,
            "effective_model_parameters": effective,
            "num_boost_round": self.num_boost_round,
            "identity_tie": "declared_native_fields_equal_effective_runtime",
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["identity_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload


@dataclass(frozen=True)
class XGBNativeRankerResult:
    """Fitted ranker and the exact effective runtime contract."""

    model: Any
    feature_names: tuple[str, ...]
    groups: tuple[int, ...]
    calibration: XGBNativeCalibration
    identity_manifest: dict[str, object]


def _validate_fit_inputs(
    features: pd.DataFrame,
    rank_target: pd.Series,
    groups: list[int],
) -> None:
    if features.empty:
        raise ValueError("features must not be empty")
    if not features.index.equals(rank_target.index):
        raise ValueError("features and rank_target must have identical indices")
    if not groups or any(size < 2 for size in groups):
        raise ValueError("every XGBoost query group must contain at least two rows")
    if sum(groups) != len(features):
        raise ValueError("sum(groups) must equal the number of training rows")
    if not np.isfinite(features.astype(float).to_numpy()).all():
        raise ValueError("features contain missing or non-finite values")


def fit_xgb_native_daily_ranker(
    features: pd.DataFrame,
    rank_target: pd.Series,
    groups: list[int],
    *,
    calibration: XGBNativeCalibration,
) -> XGBNativeRankerResult:
    """Fit one ranker using only the explicit native calibration contract."""

    _validate_fit_inputs(features, rank_target, groups)

    import xgboost as xgb

    gains = percentile_rank_to_gain(
        rank_target,
        n_bins=calibration.n_gain_bins,
    )
    dtrain = xgb.DMatrix(features, label=gains.loc[features.index])
    dtrain.set_group(groups)
    model = xgb.train(
        calibration.effective_model_parameters(),
        dtrain,
        num_boost_round=calibration.num_boost_round,
    )
    return XGBNativeRankerResult(
        model=model,
        feature_names=tuple(str(item) for item in features.columns),
        groups=tuple(groups),
        calibration=calibration,
        identity_manifest=calibration.identity_manifest(),
    )


def predict_xgb_native_daily_ranker(
    result: XGBNativeRankerResult,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Predict scores while carrying the effective parameter identity."""

    import xgboost as xgb

    matrix = features.loc[:, list(result.feature_names)]
    scores = pd.DataFrame(
        result.model.predict(xgb.DMatrix(matrix)),
        index=matrix.index,
        columns=["score"],
    )
    scores.attrs["provenance"] = "out_of_sample_daily_ranker_prediction"
    scores.attrs["model_type"] = "xgb_rank_ndcg_native_contract"
    scores.attrs["n_gain_bins"] = result.calibration.n_gain_bins
    scores.attrs["num_boost_round"] = result.calibration.num_boost_round
    scores.attrs["effective_runtime_parameters"] = result.calibration.effective_model_parameters()
    scores.attrs["parameter_identity_sha256"] = result.identity_manifest["identity_sha256"]
    return scores
