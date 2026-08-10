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
    return [int(size) for size in index.to_frame(index=False).groupby("datetime", sort=True).size()]


def make_daily_topk_relevance_target(
    raw_returns: pd.DataFrame,
    *,
    top_k: int = 3,
) -> pd.Series:
    """Build exact daily Top-K binary relevance labels.

    The target is aligned with a long-only Top-K portfolio: exactly ``top_k``
    finite-return instruments per date receive relevance ``1`` and all
    remaining instruments receive ``0``. Ties are broken deterministically by
    instrument name after sorting by raw forward return descending.

    This is a processed training target only. Economic evaluation must continue
    to use the canonical raw 10D forward returns.
    """

    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not isinstance(raw_returns.index, pd.MultiIndex):
        raise ValueError("raw_returns must use a MultiIndex")
    if "datetime" not in raw_returns.index.names:
        raise ValueError("raw_returns index must include a datetime level")
    if "instrument" not in raw_returns.index.names:
        raise ValueError("raw_returns index must include an instrument level")
    if raw_returns.shape[1] != 1:
        raise ValueError("raw_returns must contain exactly one return column")
    if raw_returns.attrs.get("provenance") != "raw_forward_return":
        raise ValueError("raw_returns provenance must be raw_forward_return")
    if raw_returns.attrs.get("horizon") != 10:
        raise ValueError("raw_returns horizon must be 10")

    values = raw_returns.iloc[:, 0].astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError(
            "raw_returns contains missing or non-finite values; invalid rows "
            "must be removed before Top-K target construction"
        )

    target = pd.Series(0, index=values.index, dtype=int, name="topk_relevance")
    instrument_level = values.index.names.index("instrument")
    for _, group in values.groupby(level="datetime", sort=True):
        if len(group) <= top_k:
            raise ValueError("each Top-K ranker group must contain more rows than top_k")
        ordered = sorted(
            group.items(),
            key=lambda item: (
                -float(item[1]),
                str(item[0][instrument_level]),
            ),
        )
        selected = [index for index, _ in ordered[:top_k]]
        target.loc[selected] = 1

    target.attrs["provenance"] = "processed_daily_topk_relevance_target"
    target.attrs["source"] = raw_returns.attrs.get("provenance")
    target.attrs["horizon"] = raw_returns.attrs.get("horizon")
    target.attrs["top_k"] = top_k
    return target


def _prepare_valid_ranker_inputs(
    features: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    minimum_group_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align finite feature/return observations and remove undersized dates."""

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
    if minimum_group_size < 2:
        raise ValueError("minimum_group_size must be at least two")

    common = features.index.intersection(raw_returns.index)
    frame_x = features.loc[common].sort_index().replace([np.inf, -np.inf], np.nan)
    frame_returns = (
        raw_returns.loc[common].sort_index().astype(float).replace([np.inf, -np.inf], np.nan)
    )

    valid_rows = frame_x.notna().all(axis=1) & frame_returns.iloc[:, 0].notna()
    frame_x = frame_x.loc[valid_rows]
    frame_returns = frame_returns.loc[valid_rows]

    if not frame_x.empty:
        group_sizes = frame_x.groupby(level="datetime", sort=True).size()
        valid_dates = group_sizes[group_sizes >= minimum_group_size].index
        date_mask = frame_x.index.get_level_values("datetime").isin(valid_dates)
        frame_x = frame_x.loc[date_mask]
        frame_returns = frame_returns.loc[date_mask]

    if frame_x.empty:
        raise ValueError(
            "no valid ranker training rows remain after removing missing or "
            "non-finite values and single-instrument dates"
        )
    return frame_x, frame_returns


def prepare_ranker_frame(
    features: pd.DataFrame,
    raw_returns: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, list[int]]:
    """Align valid observations and build percentile-rank training groups.

    Invalid feature or return values are removed; they are never replaced with
    synthetic zero or neutral-rank values. Dates retaining fewer than two valid
    instruments are also removed because they cannot form a meaningful ranking
    group. Percentile targets are calculated only after this filtering, so each
    target is ranked within the exact cross-section used for training.
    """

    frame_x, frame_returns = _prepare_valid_ranker_inputs(
        features,
        raw_returns,
        minimum_group_size=2,
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


def prepare_topk_ranker_frame(
    features: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    top_k: int = 3,
) -> tuple[pd.DataFrame, pd.Series, list[int]]:
    """Align finite inputs and build an exact daily Top-K relevance target."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    frame_x, frame_returns = _prepare_valid_ranker_inputs(
        features,
        raw_returns,
        minimum_group_size=top_k + 1,
    )
    frame_y = make_daily_topk_relevance_target(
        frame_returns,
        top_k=top_k,
    )
    groups = make_daily_rank_groups(frame_x.index)
    if not frame_x.index.equals(frame_y.index):
        raise ValueError("prepared feature and target indices do not match")
    if not groups or any(size <= top_k for size in groups):
        raise ValueError("Top-K ranker groups must contain more rows than top_k")
    if sum(groups) != len(frame_x):
        raise ValueError("ranker group sizes do not match the prepared frame")
    return frame_x, frame_y, groups
