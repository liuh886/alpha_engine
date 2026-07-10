"""Daily cross-sectional ranking helpers for fixed-ten-day research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_daily_rank_target(
    raw_returns: pd.DataFrame,
    *,
    higher_is_better: bool = True,
) -> pd.Series:
    """Convert raw forward returns into same-date percentile ranks.

    The input must be indexed by ``(datetime, instrument)``. Missing raw returns
    remain missing so callers can drop invalid training rows explicitly. The
    returned target is suitable for training a rank-style model, but economic
    evaluation must still use raw ten-day returns.
    """

    if not isinstance(raw_returns.index, pd.MultiIndex):
        raise ValueError("raw_returns must use a MultiIndex")
    if "datetime" not in raw_returns.index.names:
        raise ValueError("raw_returns index must include a datetime level")
    if raw_returns.shape[1] != 1:
        raise ValueError("raw_returns must contain exactly one return column")

    target = raw_returns.iloc[:, 0].astype(float)
    ranks = target.groupby(level="datetime").rank(
        method="average",
        pct=True,
        ascending=higher_is_better,
    )
    ranks.name = "rank_target"
    ranks.attrs["provenance"] = "processed_daily_rank_target"
    ranks.attrs["source"] = raw_returns.attrs.get("provenance", "unknown")
    ranks.attrs["horizon"] = raw_returns.attrs.get("horizon")
    return ranks


def make_daily_rank_groups(index: pd.MultiIndex) -> list[int]:
    """Return group sizes in date order for ranker training."""

    if "datetime" not in index.names:
        raise ValueError("index must include a datetime level")
    return [
        int(size)
        for size in index.to_frame(index=False)
        .groupby("datetime", sort=True)
        .size()
    ]


def prepare_ranker_frame(
    features: pd.DataFrame,
    raw_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, list[int]]:
    """Align valid observations and build cross-sectional ranking groups.

    Invalid feature or return values are removed; they are never replaced with
    synthetic zero or neutral-rank values. Dates retaining fewer than two valid
    instruments are also removed because they cannot form a meaningful ranking
    group. Percentile targets are calculated only after this filtering, so each
    target is ranked within the exact cross-section used for training.
    """

    if not isinstance(features.index, pd.MultiIndex):
        raise ValueError("features must use a MultiIndex")
    if "datetime" not in features.index.names:
        raise ValueError("features index must include a datetime level")
    if features.shape[1] == 0:
        raise ValueError("features must contain at least one column")
    if not isinstance(raw_returns.index, pd.MultiIndex):
        raise ValueError("raw_returns must use a MultiIndex")
    if "datetime" not in raw_returns.index.names:
        raise ValueError("raw_returns index must include a datetime level")
    if raw_returns.shape[1] != 1:
        raise ValueError("raw_returns must contain exactly one return column")

    common = features.index.intersection(raw_returns.index)
    frame_x = (
        features.loc[common]
        .sort_index()
        .replace([np.inf, -np.inf], np.nan)
    )
    frame_returns = (
        raw_returns.loc[common]
        .sort_index()
        .astype(float)
        .replace([np.inf, -np.inf], np.nan)
    )

    valid_rows = frame_x.notna().all(axis=1) & frame_returns.iloc[:, 0].notna()
    frame_x = frame_x.loc[valid_rows]
    frame_returns = frame_returns.loc[valid_rows]

    if not frame_x.empty:
        group_sizes = frame_x.groupby(level="datetime", sort=True).size()
        valid_dates = group_sizes[group_sizes >= 2].index
        date_mask = frame_x.index.get_level_values("datetime").isin(valid_dates)
        frame_x = frame_x.loc[date_mask]
        frame_returns = frame_returns.loc[date_mask]

    if frame_x.empty:
        raise ValueError(
            "no valid ranker training rows remain after removing missing or "
            "non-finite values and single-instrument dates"
        )

    frame_y = make_daily_rank_target(frame_returns)
    groups = make_daily_rank_groups(frame_x.index)
    if not frame_x.index.equals(frame_y.index):
        raise ValueError("prepared feature and target indices do not match")
    if not groups or any(size < 2 for size in groups):
        raise ValueError("ranker groups must contain at least two instruments")
    if sum(groups) != len(frame_x):
        raise ValueError("ranker group sizes do not match the prepared frame")
    return frame_x, frame_y, groups
