"""Ranker calibration and feature-quality grids for 10D research."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any


@dataclass(frozen=True)
class RankerFeatureGroup:
    """Named feature expression group for daily ranker research."""

    name: str
    expressions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "expressions": list(self.expressions)}


@dataclass(frozen=True)
class RankerCalibration:
    """One LightGBM LambdaRank calibration setting."""

    n_gain_bins: int
    num_boost_round: int
    num_leaves: int
    min_data_in_leaf: int
    learning_rate: float = 0.05

    @property
    def name(self) -> str:
        return (
            f"gain{self.n_gain_bins}_round{self.num_boost_round}_"
            f"leaves{self.num_leaves}_leaf{self.min_data_in_leaf}_lr{self.learning_rate:g}"
        )

    def params(self) -> dict[str, Any]:
        return {
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": self.min_data_in_leaf,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "n_gain_bins": self.n_gain_bins,
            "num_boost_round": self.num_boost_round,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": self.min_data_in_leaf,
            "learning_rate": self.learning_rate,
        }


VALID_MODEL_FAMILIES: tuple[str, ...] = ("lgbm", "xgb")


@dataclass(frozen=True)
class RankerGridCandidate:
    """One feature-group/calibration candidate in the ranker grid."""

    feature_group: RankerFeatureGroup
    calibration: RankerCalibration
    model_family: str = "lgbm"

    def __post_init__(self) -> None:
        if self.model_family not in VALID_MODEL_FAMILIES:
            raise ValueError(
                f"model_family must be one of {VALID_MODEL_FAMILIES}, "
                f"got {self.model_family!r}"
            )

    @property
    def name(self) -> str:
        return (
            f"{self.model_family}:daily_ranker:"
            f"{self.feature_group.name}:{self.calibration.name}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "feature_group": self.feature_group.to_dict(),
            "calibration": self.calibration.to_dict(),
            "model_family": self.model_family,
        }


def default_ranker_feature_groups() -> list[RankerFeatureGroup]:
    """Return compact feature groups for model-quality search."""

    dollar = chr(36)
    momentum = (
        f"{dollar}close/Ref({dollar}close,5)-1",
        f"{dollar}close/Ref({dollar}close,10)-1",
        f"{dollar}close/Ref({dollar}close,20)-1",
    )
    daily_return = f"{dollar}close/Ref({dollar}close,1)-1"
    volatility = (
        f"Std({daily_return},10)",
        f"Std({daily_return},20)",
    )
    volume = (
        f"{dollar}volume/Ref({dollar}volume,10)-1",
        f"{dollar}volume/Mean({dollar}volume,20)-1",
    )
    risk_controlled = (
        f"({dollar}close/Ref({dollar}close,10)-1)/(Std({daily_return},10)+1e-12)",
        f"({dollar}close/Ref({dollar}close,20)-1)/(Std({daily_return},20)+1e-12)",
    )
    return [
        RankerFeatureGroup("momentum", momentum),
        RankerFeatureGroup("momentum_volatility", momentum + volatility),
        RankerFeatureGroup("momentum_volatility_volume", momentum + volatility + volume),
        RankerFeatureGroup("risk_controlled_momentum", momentum + volatility + risk_controlled),
    ]


def default_ranker_calibrations() -> list[RankerCalibration]:
    """Return a deliberately small LambdaRank calibration grid."""

    return [
        RankerCalibration(n_gain_bins=3, num_boost_round=100, num_leaves=15, min_data_in_leaf=5),
        RankerCalibration(n_gain_bins=5, num_boost_round=100, num_leaves=31, min_data_in_leaf=10),
        RankerCalibration(n_gain_bins=7, num_boost_round=200, num_leaves=31, min_data_in_leaf=10),
        RankerCalibration(n_gain_bins=10, num_boost_round=200, num_leaves=63, min_data_in_leaf=20),
    ]


def build_ranker_calibration_grid(
    feature_groups: list[RankerFeatureGroup] | None = None,
    calibrations: list[RankerCalibration] | None = None,
    *,
    model_families: tuple[str, ...] | None = None,
) -> list[RankerGridCandidate]:
    """Build the Cartesian product of feature groups, calibrations, and model families.

    Defaults to ``['lgbm']`` so every existing spec and identity is unchanged.
    """

    groups = feature_groups if feature_groups is not None else default_ranker_feature_groups()
    settings = calibrations if calibrations is not None else default_ranker_calibrations()
    families = model_families if model_families is not None else ("lgbm",)
    for mf in families:
        if mf not in VALID_MODEL_FAMILIES:
            raise ValueError(
                f"model_families must be a subset of {VALID_MODEL_FAMILIES}, "
                f"got {mf!r}"
            )
    candidates: list[RankerGridCandidate] = []
    for group, calibration, mf in product(groups, settings, families):
        candidates.append(
            RankerGridCandidate(group, calibration, model_family=mf)
        )
    return candidates


def grid_manifest(candidates: list[RankerGridCandidate]) -> dict[str, object]:
    """Return a serializable manifest for a ranker calibration grid."""

    names = [candidate.name for candidate in candidates]
    if len(names) != len(set(names)):
        raise ValueError("ranker grid candidate names must be unique")
    return {
        "schema_version": "1.0",
        "n_candidates": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
