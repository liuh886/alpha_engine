"""Fail-closed cross-sectional score diagnostics for raw forward returns.

The helpers in this module are intentionally model-agnostic.  They measure
whether a score that looks useful across the broad cross-section still orders
the exact Top-K and Bottom-K tails used by a concentrated portfolio.

Selections are made from the score frame before raw-return availability is
checked.  This prevents a future label from deciding which symbols enter a
diagnostic tail.  The module is research-only and does not promote an
orientation or candidate for trading.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Sequence[float]) -> float | None:
    return _finite(np.mean(values)) if values else None


def _std(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return _finite(np.std(values, ddof=0))


def _ratio(values: Sequence[bool]) -> float | None:
    return _finite(np.mean(values)) if values else None


def _icir(values: Sequence[float]) -> float | None:
    mean = _mean(values)
    std = _std(values)
    if mean is None or std is None or std <= 0.0:
        return None
    return _finite(mean / std)


def _validate_frame(
    frame: pd.DataFrame,
    *,
    expected_column: str,
    frame_name: str,
) -> None:
    if list(frame.columns) != [expected_column]:
        raise ValueError(f"{frame_name} must contain exactly one {expected_column!r} column")
    if not isinstance(frame.index, pd.MultiIndex):
        raise ValueError(f"{frame_name} must use a MultiIndex")
    if set(frame.index.names) != {"datetime", "instrument"}:
        raise ValueError(f"{frame_name} index levels must be datetime and instrument")
    if not frame.index.is_unique:
        raise ValueError(f"{frame_name} index must be unique")
    if frame.empty:
        raise ValueError(f"{frame_name} must not be empty")


def _validate_inputs(scores: pd.DataFrame, raw_returns: pd.DataFrame) -> None:
    _validate_frame(scores, expected_column="score", frame_name="scores")
    _validate_frame(
        raw_returns,
        expected_column="return",
        frame_name="raw_returns",
    )
    if raw_returns.attrs.get("provenance") != "raw_forward_return":
        raise ValueError("raw_returns provenance must be raw_forward_return")
    if raw_returns.attrs.get("horizon") != 10:
        raise ValueError("raw_returns horizon must be 10")
    if not raw_returns.attrs.get("expression"):
        raise ValueError("raw_returns expression provenance is required")


def _date_series(
    frame: pd.DataFrame,
    date: pd.Timestamp,
    column: str,
) -> pd.Series:
    try:
        values = frame.xs(date, level="datetime")[column]
    except KeyError:
        return pd.Series(dtype=float, name=column)
    return values.astype(float).replace([np.inf, -np.inf], np.nan).dropna().sort_index()


def _selected_tail_metrics(
    scores: pd.Series,
    returns: pd.Series,
    *,
    top_n: int,
    date: pd.Timestamp,
    strict: bool,
) -> dict[str, Any] | None:
    if top_n < 1:
        raise ValueError("tail sizes must be positive")
    if len(scores) < 2 * top_n:
        if strict:
            raise ValueError(
                f"{date.date()} has {len(scores)} finite scores; "
                f"need at least {2 * top_n} for Top-{top_n}/Bottom-{top_n}"
            )
        return None

    # Select from scores alone.  Raw-return availability is checked only after
    # the tails are frozen so that a future label cannot change membership.
    top_index = scores.nlargest(top_n, keep="first").index
    bottom_index = scores.nsmallest(top_n, keep="first").index
    selected_index = top_index.append(bottom_index).unique()
    missing = sorted(str(symbol) for symbol in selected_index if symbol not in returns.index)
    if missing:
        if strict:
            raise ValueError(f"{date.date()} selected tails lack finite raw returns: {missing}")
        return None

    common = scores.index.intersection(returns.index)
    if len(common) < 2:
        if strict:
            raise ValueError(f"{date.date()} has too few score/return pairs")
        return None
    return_ranks = returns.loc[common].rank(method="average", pct=True)

    top_return = float(returns.loc[top_index].mean())
    bottom_return = float(returns.loc[bottom_index].mean())
    return {
        "top_n": top_n,
        "top_mean_return": top_return,
        "bottom_mean_return": bottom_return,
        "spread": top_return - bottom_return,
        "top_mean_realized_percentile": float(return_ranks.loc[top_index].mean()),
        "bottom_mean_realized_percentile": float(return_ranks.loc[bottom_index].mean()),
    }


def _date_row(
    scores: pd.DataFrame,
    raw_returns: pd.DataFrame,
    date: pd.Timestamp,
    *,
    tail_sizes: Sequence[int],
    strict_tails: bool,
) -> dict[str, Any] | None:
    score_values = _date_series(scores, date, "score")
    return_values = _date_series(raw_returns, date, "return")
    common = score_values.index.intersection(return_values.index)
    if len(common) < 5 or score_values.loc[common].nunique() < 2:
        if strict_tails:
            raise ValueError(f"{date.date()} has insufficient finite cross-sectional pairs")
        return None

    common_scores = score_values.loc[common]
    common_returns = return_values.loc[common]
    pearson = _finite(common_scores.corr(common_returns, method="pearson"))
    rank_ic = _finite(common_scores.corr(common_returns, method="spearman"))
    if pearson is None or rank_ic is None:
        if strict_tails:
            raise ValueError(f"{date.date()} has undefined IC metrics")
        return None

    quintile_size = max(1, len(score_values) // 5)
    quintile = _selected_tail_metrics(
        score_values,
        return_values,
        top_n=quintile_size,
        date=date,
        strict=strict_tails,
    )
    if quintile is None:
        return None

    tails: dict[str, Any] = {}
    for tail_size in tail_sizes:
        result = _selected_tail_metrics(
            score_values,
            return_values,
            top_n=tail_size,
            date=date,
            strict=strict_tails,
        )
        if result is not None:
            tails[str(tail_size)] = result

    return {
        "date": date.strftime("%Y-%m-%d"),
        "n_scored": int(len(score_values)),
        "n_finite_returns": int(len(return_values)),
        "n_common": int(len(common)),
        "pearson_ic": pearson,
        "rank_ic": rank_ic,
        "quintile": quintile,
        "tails": tails,
    }


def _summarize_tail(
    rows: Sequence[dict[str, Any]],
    *,
    tail_key: str,
    multiplier: float,
) -> dict[str, Any]:
    tails = [
        row["quintile"] if tail_key == "quintile" else row["tails"].get(tail_key) for row in rows
    ]
    valid = [tail for tail in tails if isinstance(tail, dict)]
    spreads = [float(tail["spread"]) * multiplier for tail in valid]
    if multiplier > 0:
        selected_percentiles = [float(tail["top_mean_realized_percentile"]) for tail in valid]
        selected_returns = [float(tail["top_mean_return"]) for tail in valid]
    else:
        selected_percentiles = [float(tail["bottom_mean_realized_percentile"]) for tail in valid]
        selected_returns = [float(tail["bottom_mean_return"]) for tail in valid]
    return {
        "n_dates": len(valid),
        "mean_spread": _mean(spreads),
        "positive_spread_ratio": _ratio([value > 0.0 for value in spreads]),
        "mean_selected_return": _mean(selected_returns),
        "mean_selected_realized_percentile": _mean(selected_percentiles),
        "selected_above_median_ratio": _ratio([value > 0.5 for value in selected_percentiles]),
    }


def _summarize_rows(
    rows: Sequence[dict[str, Any]],
    *,
    tail_sizes: Sequence[int],
    multiplier: float,
) -> dict[str, Any]:
    pearson = [float(row["pearson_ic"]) * multiplier for row in rows]
    rank_ic = [float(row["rank_ic"]) * multiplier for row in rows]
    return {
        "n_dates": len(rows),
        "mean_cross_section_size": _mean([float(row["n_common"]) for row in rows]),
        "mean_pearson_ic": _mean(pearson),
        "pearson_icir": _icir(pearson),
        "positive_pearson_ic_ratio": _ratio([value > 0.0 for value in pearson]),
        "mean_rank_ic": _mean(rank_ic),
        "rank_icir": _icir(rank_ic),
        "positive_rank_ic_ratio": _ratio([value > 0.0 for value in rank_ic]),
        "quintile": _summarize_tail(
            rows,
            tail_key="quintile",
            multiplier=multiplier,
        ),
        "fixed_tails": {
            str(size): _summarize_tail(
                rows,
                tail_key=str(size),
                multiplier=multiplier,
            )
            for size in tail_sizes
        },
    }


def _normalized_dates(values: Iterable[str | pd.Timestamp]) -> tuple[pd.Timestamp, ...]:
    dates = tuple(sorted({pd.Timestamp(value).normalize() for value in values}))
    if not dates:
        raise ValueError("rebalance_dates must not be empty")
    return dates


def diagnose_cross_sectional_score(
    scores: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    rebalance_dates: Iterable[str | pd.Timestamp],
    tail_sizes: Sequence[int] = (3, 10, 20),
) -> dict[str, Any]:
    """Diagnose broad IC and concentrated tails for one OOS score frame.

    Daily summaries use every score/return date with at least five finite
    cross-sectional pairs.  Rebalance summaries use the exact caller-supplied
    dates and fail closed if a requested Top-K or Bottom-K return is missing.
    Both orientations are descriptive views of the same OOS observations;
    choosing one from these results would be an OOS-selected decision and is
    explicitly not a deployable model change.
    """

    _validate_inputs(scores, raw_returns)
    normalized_tail_sizes = tuple(sorted({int(size) for size in tail_sizes}))
    if not normalized_tail_sizes or normalized_tail_sizes[0] < 1:
        raise ValueError("tail_sizes must contain positive integers")

    requested_rebalance_dates = _normalized_dates(rebalance_dates)
    rebalance_rows = [
        _date_row(
            scores,
            raw_returns,
            date,
            tail_sizes=normalized_tail_sizes,
            strict_tails=True,
        )
        for date in requested_rebalance_dates
    ]
    if any(row is None for row in rebalance_rows):
        raise ValueError("one or more rebalance dates could not be evaluated")
    strict_rows = [row for row in rebalance_rows if row is not None]

    score_dates = {
        pd.Timestamp(value).normalize() for value in scores.index.get_level_values("datetime")
    }
    return_dates = {
        pd.Timestamp(value).normalize() for value in raw_returns.index.get_level_values("datetime")
    }
    daily_dates = sorted(score_dates & return_dates)
    daily_rows = [
        row
        for date in daily_dates
        if (
            row := _date_row(
                scores,
                raw_returns,
                date,
                tail_sizes=normalized_tail_sizes,
                strict_tails=False,
            )
        )
        is not None
    ]
    if not daily_rows:
        raise ValueError("no valid daily cross-sectional diagnostic dates")

    return {
        "research_only": True,
        "trade_ready": False,
        "oos_selected_orientation_not_deployable": True,
        "raw_return_provenance": {
            "provenance": raw_returns.attrs["provenance"],
            "horizon": raw_returns.attrs["horizon"],
            "expression": raw_returns.attrs["expression"],
        },
        "tail_sizes": list(normalized_tail_sizes),
        "n_score_rows": int(np.isfinite(scores["score"].astype(float).to_numpy()).sum()),
        "n_rebalance_dates_requested": len(requested_rebalance_dates),
        "orientations": {
            "original": {
                "daily": _summarize_rows(
                    daily_rows,
                    tail_sizes=normalized_tail_sizes,
                    multiplier=1.0,
                ),
                "rebalance": _summarize_rows(
                    strict_rows,
                    tail_sizes=normalized_tail_sizes,
                    multiplier=1.0,
                ),
            },
            "inverted": {
                "daily": _summarize_rows(
                    daily_rows,
                    tail_sizes=normalized_tail_sizes,
                    multiplier=-1.0,
                ),
                "rebalance": _summarize_rows(
                    strict_rows,
                    tail_sizes=normalized_tail_sizes,
                    multiplier=-1.0,
                ),
            },
        },
        "rebalance_rows_original": strict_rows,
    }
