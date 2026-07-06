"""Daily cross-sectional ranking helpers for fixed-ten-day research."""

from __future__ import annotations

import pandas as pd


def make_daily_rank_target(
    raw_returns: pd.DataFrame,
    *,
    higher_is_better: bool = True,
) -> pd.Series:
    """Convert raw forward returns into same-date percentile ranks.

    The input must be indexed by (datetime, instrument). The returned target is
    suitable for training a rank-style model, but economic evaluation must still
    use raw ten-day returns.
    """

    target = raw_returns.iloc[:, 0].astype(float)
    ascending = not higher_is_better
    ranks = target.groupby(level="datetime").rank(method="average", pct=True, ascending=ascending)
    ranks.name = "rank_target"
    ranks.attrs["provenance"] = "processed_daily_rank_target"
    ranks.attrs["source"] = raw_returns.attrs.get("provenance", "unknown")
    ranks.attrs["horizon"] = raw_returns.attrs.get("horizon")
    return ranks


def make_daily_rank_groups(index: pd.MultiIndex) -> list[int]:
    """Return group sizes in date order for ranker training."""

    if "datetime" not in index.names:
        raise ValueError("index must include a datetime level")
    return [int(size) for size in index.to_frame(index=False).groupby("datetime", sort=True).size()]


def prepare_ranker_frame(
    features: pd.DataFrame,
    raw_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, list[int]]:
    """Align features with raw returns and build daily ranking groups."""

    target = make_daily_rank_target(raw_returns)
    common = features.index.intersection(target.index)
    frame_x = features.loc[common].sort_index().fillna(0.0)
    frame_y = target.loc[common].sort_index().fillna(0.5)
    groups = make_daily_rank_groups(frame_x.index)
    return frame_x, frame_y, groups
