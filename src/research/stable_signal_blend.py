"""Stable signal blending helpers for fixed-ten-day research."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BlendWeight:
    """One two-signal blend weight definition."""

    ranker_weight: float
    momentum_weight: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.ranker_weight <= 1.0 or not 0.0 <= self.momentum_weight <= 1.0:
            raise ValueError("blend weights must be between 0 and 1")
        if not isclose(self.ranker_weight + self.momentum_weight, 1.0, abs_tol=1e-9):
            raise ValueError("blend weights must sum to 1")

    @property
    def name(self) -> str:
        return f"ranker{self.ranker_weight:g}_momentum{self.momentum_weight:g}"

    def to_dict(self) -> dict[str, float]:
        return {
            "ranker_weight": self.ranker_weight,
            "momentum_weight": self.momentum_weight,
        }


def daily_cross_sectional_zscore(score: pd.DataFrame) -> pd.DataFrame:
    """Normalize valid scores within each date without manufacturing values.

    Missing/non-finite rows and dates with fewer than two valid instruments are
    removed. A valid constant cross-section has no relative signal and is
    represented by explicit zeros.
    """

    if "datetime" not in score.index.names:
        raise ValueError("score index must include a datetime level")
    frame = score.copy()
    if list(frame.columns) != ["score"]:
        if len(frame.columns) != 1:
            raise ValueError("score frame must have exactly one column")
        frame.columns = ["score"]

    values = (
        frame["score"]
        .astype(float)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .sort_index()
    )
    if values.empty:
        result = values.to_frame("score")
        result.attrs.update(frame.attrs)
        result.attrs["transform"] = "daily_cross_sectional_zscore"
        return result

    sizes = values.groupby(level="datetime", sort=True).size()
    valid_dates = sizes[sizes >= 2].index
    values = values.loc[
        values.index.get_level_values("datetime").isin(valid_dates)
    ]

    normalized_parts: list[pd.Series] = []
    for _, day in values.groupby(level="datetime", sort=True):
        standard_deviation = float(day.std(ddof=0))
        if standard_deviation == 0.0:
            normalized = pd.Series(0.0, index=day.index, name="score")
        else:
            normalized = ((day - float(day.mean())) / standard_deviation).rename(
                "score"
            )
        normalized_parts.append(normalized)

    if normalized_parts:
        normalized_values = pd.concat(normalized_parts).sort_index()
    else:
        normalized_values = values.iloc[0:0].rename("score")
    if not np.isfinite(normalized_values.to_numpy()).all():
        raise ValueError("cross-sectional z-score produced non-finite values")

    result = normalized_values.to_frame("score")
    result.attrs.update(frame.attrs)
    result.attrs["transform"] = "daily_cross_sectional_zscore"
    return result


def invert_score(score: pd.DataFrame) -> pd.DataFrame:
    """Return an inverted score frame while preserving metadata."""

    frame = score.copy()
    if list(frame.columns) != ["score"]:
        if len(frame.columns) != 1:
            raise ValueError("score frame must have exactly one column")
        frame.columns = ["score"]
    frame["score"] = -frame["score"].astype(float)
    frame.attrs.update(score.attrs)
    frame.attrs["inverted"] = True
    return frame


def build_two_signal_blend(
    ranker_score: pd.DataFrame,
    momentum_score: pd.DataFrame,
    *,
    weight: BlendWeight,
    invert_momentum: bool = True,
) -> pd.DataFrame:
    """Blend ranker score with inverted historical momentum on common rows."""

    ranker = daily_cross_sectional_zscore(ranker_score)
    momentum_input = invert_score(momentum_score) if invert_momentum else momentum_score
    momentum = daily_cross_sectional_zscore(momentum_input)
    common = ranker.index.intersection(momentum.index)
    blended = (
        weight.ranker_weight * ranker.loc[common, "score"]
        + weight.momentum_weight * momentum.loc[common, "score"]
    ).to_frame("score")
    blended.attrs["provenance"] = "stable_signal_blend"
    blended.attrs["ranker_weight"] = weight.ranker_weight
    blended.attrs["momentum_weight"] = weight.momentum_weight
    blended.attrs["momentum_inverted"] = invert_momentum
    return blended


def default_blend_weights() -> list[BlendWeight]:
    """Return compact ranker/momentum blend weights for the next evidence pass."""

    return [
        BlendWeight(ranker_weight=0.25, momentum_weight=0.75),
        BlendWeight(ranker_weight=0.50, momentum_weight=0.50),
        BlendWeight(ranker_weight=0.75, momentum_weight=0.25),
    ]


def build_blend_candidates(
    ranker_scores: dict[str, pd.DataFrame],
    momentum_score: pd.DataFrame,
    *,
    weights: Iterable[BlendWeight] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build named blend candidates from ranker candidates and momentum baseline."""

    selected_weights = list(weights) if weights is not None else default_blend_weights()
    candidates: dict[str, pd.DataFrame] = {}
    for ranker_name, ranker_score in ranker_scores.items():
        short_ranker = ranker_name.replace("lgbm:daily_ranker:", "")
        for weight in selected_weights:
            name = f"blend:ranker_momentum:{short_ranker}:{weight.name}"
            candidates[name] = build_two_signal_blend(
                ranker_score,
                momentum_score,
                weight=weight,
                invert_momentum=True,
            )
    return candidates
