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

    Invalid feature or target values are removed; they are never replaced with
    synthetic zero or neutral-rank values. Dates retaining fewer than two valid
    instruments are also removed because they cannot form a meaningful ranking
    group.
    """

    if not isinstance(features.index, pd.MultiIndex):
        raise ValueError("features must use a MultiIndex")
    if "datetime" not in features.index.names:
        raise ValueError("features index must include a datetime level")
    if features.shape[1] == 0:
        raise ValueError("features must contain at least one column")

    target = make_daily_rank_target(raw_returns)
    target_attrs = dict(target.attrs)
    common = features.index.intersection(target.index)
    frame_x = (
        features.loc[common]
        .sort_index()
        .replace([np.inf, -np.inf], np.nan)
    )
    frame_y = (
        target.loc[common]
        .sort_index()
        .replace([np.inf, -np.inf], np.nan)
    )

    valid_rows = frame_x.notna().all(axis=1) & frame_y.notna()
    frame_x = frame_x.loc[valid_rows]
    frame_y = frame_y.loc[valid_rows]

    if not frame_x.empty:
        group_sizes = frame_x.groupby(level="datetime", sort=True).size()
        valid_dates = group_sizes[group_sizes >= 2].index
        date_mask = frame_x.index.get_level_values("datetime").isin(valid_dates)
        frame_x = frame_x.loc[date_mask]
        frame_y = frame_y.loc[date_mask]

    if frame_x.empty:
        raise ValueError(
            "no valid ranker training rows remain after removing missing or "
            "non-finite values and single-instrument dates"
        )

    frame_y.attrs.update(target_attrs)
    groups = make_daily_rank_groups(frame_x.index)
    if not groups or any(size < 2 for size in groups):
        raise ValueError("ranker groups must contain at least two instruments")
    if sum(groups) != len(frame_x):
        raise ValueError("ranker group sizes do not match the prepared frame")
    return frame_x, frame_y, groups
