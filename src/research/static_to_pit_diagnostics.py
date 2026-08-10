"""Pure score, label, selection and contribution diagnostics."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.daily_ranker import make_daily_rank_target
from src.research.daily_ranker_model import percentile_rank_to_gain


def _series(
    frame: pd.DataFrame | pd.Series,
    *,
    kind: str,
) -> pd.Series:
    if isinstance(frame, pd.Series):
        series = frame.astype(float)
    else:
        if frame.shape[1] != 1:
            raise ValueError(f"{kind} frame must contain exactly one column")
        series = frame.iloc[:, 0].astype(float)
    if not isinstance(series.index, pd.MultiIndex):
        raise ValueError(f"{kind} data must use a MultiIndex")
    if {"datetime", "instrument"} - set(series.index.names):
        raise ValueError(f"{kind} index must include datetime and instrument")
    return series.replace([np.inf, -np.inf], np.nan).dropna().sort_index()


def topk_selections(
    scores: pd.DataFrame | pd.Series,
    *,
    top_n: int,
    rebalance_days: int,
    allowed_symbols: Sequence[str] | None = None,
) -> dict[str, list[str]]:
    """Build deterministic Top-N selections at every frozen rebalance date."""

    if top_n < 1 or rebalance_days < 1:
        raise ValueError("top_n and rebalance_days must be positive")
    series = _series(scores, kind="score")
    allowed = None if allowed_symbols is None else set(map(str, allowed_symbols))
    dates = sorted(
        pd.Timestamp(item) for item in series.index.get_level_values("datetime").unique()
    )
    result: dict[str, list[str]] = {}
    for date in dates[::rebalance_days]:
        group = series.xs(date, level="datetime").dropna()
        if allowed is not None:
            group = group[group.index.astype(str).isin(allowed)]
        ordered = sorted(
            ((str(symbol), float(score)) for symbol, score in group.items()),
            key=lambda item: (-item[1], item[0]),
        )
        result[date.strftime("%Y-%m-%d")] = [symbol for symbol, _ in ordered[:top_n]]
    return result


def selection_overlap(
    left: Mapping[str, Sequence[str]],
    right: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    """Compare two selection maps date by date."""

    rows: list[dict[str, Any]] = []
    for date in sorted(set(left).intersection(right)):
        left_set = set(map(str, left[date]))
        right_set = set(map(str, right[date]))
        union = left_set | right_set
        common = left_set & right_set
        denominator = max(len(left_set), len(right_set), 1)
        rows.append(
            {
                "date": date,
                "left_count": len(left_set),
                "right_count": len(right_set),
                "intersection_count": len(common),
                "overlap_ratio": len(common) / denominator,
                "jaccard": len(common) / max(len(union), 1),
                "left_only": sorted(left_set - right_set),
                "right_only": sorted(right_set - left_set),
                "common": sorted(common),
            }
        )
    return rows


def score_rank_migration(
    static_scores: pd.DataFrame | pd.Series,
    pit_scores: pd.DataFrame | pd.Series,
) -> dict[str, Any]:
    """Measure common-name score rank migration by date."""

    left = _series(static_scores, kind="score").rename("static_score")
    right = _series(pit_scores, kind="score").rename("pit_score")
    common = left.index.intersection(right.index)
    frame = pd.concat([left.loc[common], right.loc[common]], axis=1).dropna()

    rows: list[dict[str, Any]] = []
    shifts: list[float] = []
    correlations: list[float] = []
    for date, group in frame.groupby(level="datetime", sort=True):
        if len(group) < 2:
            continue
        static_rank = group["static_score"].rank(method="average", ascending=False, pct=True)
        pit_rank = group["pit_score"].rank(method="average", ascending=False, pct=True)
        corr = static_rank.corr(pit_rank, method="spearman")
        shift = (pit_rank - static_rank).abs()
        if np.isfinite(corr):
            correlations.append(float(corr))
        shifts.extend(float(item) for item in shift.to_numpy())
        rows.append(
            {
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                "common_count": len(group),
                "spearman_rank_correlation": (None if not np.isfinite(corr) else float(corr)),
                "mean_absolute_percentile_shift": float(shift.mean()),
                "max_absolute_percentile_shift": float(shift.max()),
            }
        )
    return {
        "dates": rows,
        "common_rows": int(len(frame)),
        "mean_spearman_rank_correlation": (
            None if not correlations else float(np.mean(correlations))
        ),
        "mean_absolute_percentile_shift": (None if not shifts else float(np.mean(shifts))),
    }


def label_bin_migration(
    static_returns: pd.DataFrame,
    pit_returns: pd.DataFrame,
    *,
    n_bins: int,
) -> dict[str, Any]:
    """Compare processed daily rank-gain labels on common training rows."""

    static_target = make_daily_rank_target(static_returns)
    pit_target = make_daily_rank_target(pit_returns)
    common = static_target.index.intersection(pit_target.index)
    left = percentile_rank_to_gain(static_target.loc[common], n_bins=n_bins)
    right = percentile_rank_to_gain(pit_target.loc[common], n_bins=n_bins)
    frame = pd.DataFrame({"static_gain": left, "pit_gain": right}).dropna()
    matrix = (
        frame.groupby(["static_gain", "pit_gain"], sort=True).size().rename("count").reset_index()
    )
    changed = frame["static_gain"] != frame["pit_gain"]
    return {
        "common_rows": int(len(frame)),
        "changed_rows": int(changed.sum()),
        "changed_ratio": float(changed.mean()) if len(frame) else None,
        "mean_absolute_gain_shift": (
            float((frame["pit_gain"] - frame["static_gain"]).abs().mean()) if len(frame) else None
        ),
        "confusion": [
            {
                "static_gain": int(row.static_gain),
                "pit_gain": int(row.pit_gain),
                "count": int(row.count),
            }
            for row in matrix.itertuples(index=False)
        ],
    }


def symbol_membership_categories(
    *,
    static_symbols: Sequence[str],
    pit_symbols: Sequence[str],
    latest_snapshot_symbols: Sequence[str],
    first_snapshot_by_symbol: Mapping[str, str],
    window_snapshot_date: str,
) -> dict[str, str]:
    """Classify common, static-only, future-entrant and exit symbols."""

    static_set = set(map(str, static_symbols))
    pit_set = set(map(str, pit_symbols))
    latest_set = set(map(str, latest_snapshot_symbols))
    result: dict[str, str] = {}
    for symbol in sorted(static_set | pit_set):
        if symbol in static_set and symbol in pit_set:
            result[symbol] = "common"
        elif symbol in static_set:
            first_date = first_snapshot_by_symbol.get(symbol)
            if first_date is not None and first_date > window_snapshot_date:
                result[symbol] = "static_only/future_entrant"
            else:
                result[symbol] = "static_only/non_ndx_or_not_yet_classified"
        elif symbol not in latest_set:
            result[symbol] = "pit_only/historical_exit"
        else:
            result[symbol] = "pit_only/current_member_missing_from_static"
    return result


def selected_return_contributions(
    scores: pd.DataFrame | pd.Series,
    raw_returns: pd.DataFrame | pd.Series,
    *,
    categories: Mapping[str, str],
    top_n: int,
    rebalance_days: int,
    allowed_symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Attribute gross equal-weight selected returns by symbol and category."""

    returns = _series(raw_returns, kind="return")
    selections = topk_selections(
        scores,
        top_n=top_n,
        rebalance_days=rebalance_days,
        allowed_symbols=allowed_symbols,
    )
    by_symbol: dict[str, float] = {}
    by_category: dict[str, float] = {}
    periods: list[dict[str, Any]] = []
    for date, symbols in selections.items():
        valid: list[tuple[str, float]] = []
        for symbol in symbols:
            key = (pd.Timestamp(date), symbol)
            if key in returns.index and np.isfinite(float(returns.loc[key])):
                valid.append((symbol, float(returns.loc[key])))
        denominator = max(len(valid), 1)
        contributions = [(symbol, value / denominator) for symbol, value in valid]
        for symbol, contribution in contributions:
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + contribution
            category = categories.get(symbol, "unclassified")
            by_category[category] = by_category.get(category, 0.0) + contribution
            rollup = category.split("/", 1)[0]
            if rollup != category:
                by_category[rollup] = by_category.get(rollup, 0.0) + contribution
        periods.append(
            {
                "date": date,
                "selected": list(symbols),
                "gross_period_return": float(sum(value for _, value in contributions)),
                "contributions": [
                    {
                        "symbol": symbol,
                        "category": categories.get(symbol, "unclassified"),
                        "contribution": contribution,
                    }
                    for symbol, contribution in contributions
                ],
            }
        )

    ordered = sorted(by_symbol.items(), key=lambda item: abs(item[1]), reverse=True)
    total_abs = sum(abs(value) for _, value in ordered)
    return {
        "periods": periods,
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_category": dict(sorted(by_category.items())),
        "top_contributors_by_absolute_value": [
            {"symbol": symbol, "contribution": value} for symbol, value in ordered[:20]
        ],
        "top5_absolute_concentration": (
            None if total_abs == 0 else sum(abs(value) for _, value in ordered[:5]) / total_abs
        ),
    }


def contribution_gap(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Subtract P/P contribution from S/S contribution."""

    left_symbol = {str(key): float(value) for key, value in dict(left.get("by_symbol", {})).items()}
    right_symbol = {
        str(key): float(value) for key, value in dict(right.get("by_symbol", {})).items()
    }
    by_symbol = {
        symbol: left_symbol.get(symbol, 0.0) - right_symbol.get(symbol, 0.0)
        for symbol in sorted(set(left_symbol) | set(right_symbol))
    }
    left_category = {
        str(key): float(value) for key, value in dict(left.get("by_category", {})).items()
    }
    right_category = {
        str(key): float(value) for key, value in dict(right.get("by_category", {})).items()
    }
    by_category = {
        category: left_category.get(category, 0.0) - right_category.get(category, 0.0)
        for category in sorted(set(left_category) | set(right_category))
    }
    ordered = sorted(by_symbol.items(), key=lambda item: abs(item[1]), reverse=True)
    total_abs = sum(abs(value) for _, value in ordered)
    return {
        "definition": "S/S gross contribution minus P/P gross contribution",
        "by_symbol": by_symbol,
        "by_category": by_category,
        "top_gap_contributors_by_absolute_value": [
            {"symbol": symbol, "gap_contribution": value} for symbol, value in ordered[:20]
        ],
        "top5_absolute_gap_concentration": (
            None if total_abs == 0.0 else sum(abs(value) for _, value in ordered[:5]) / total_abs
        ),
    }
