"""Stable signal blending helpers for fixed-ten-day research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class BlendWeight:
    """One two-signal blend weight definition."""

    ranker_weight: float
    momentum_weight: float

    @property
    def name(self) -> str:
        return f"ranker{self.ranker_weight:g}_momentum{self.momentum_weight:g}"

    def to_dict(self) -> dict[str, float]:
        return {"ranker_weight": self.ranker_weight, "momentum_weight": self.momentum_weight}


def daily_cross_sectional_zscore(score: pd.DataFrame) -> pd.DataFrame:
    """Normalize scores within each date to reduce scale mismatch before blending."""

    if "datetime" not in score.index.names:
        raise ValueError("score index must include a datetime level")
    frame = score.copy()
    if list(frame.columns) != ["score"]:
        if len(frame.columns) != 1:
            raise ValueError("score frame must have exactly one column")
        frame.columns = ["score"]

    def _z(day: pd.Series) -> pd.Series:
        std = day.std(ddof=0)
        if std == 0 or pd.isna(std):
            return day * 0.0
        return (day - day.mean()) / std

    values = frame["score"].astype(float).groupby(level="datetime", group_keys=False).apply(_z)
    result = values.to_frame("score")
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
