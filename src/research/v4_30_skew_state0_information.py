"""Frozen Cboe SKEW information audit inside formal QQQ v4.2 state 0.

This module does not construct a portfolio. It tests whether point-in-time high
SKEW separates persistently worse forward QQQ paths inside the already-defined
defensive state 0 before any allocation experiment is authorized.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

SKEW_WINDOW = 252
SKEW_HIGH_QUANTILE = 0.80
HORIZONS = (20, 60)


def _normalise_skew(skew: pd.DataFrame) -> pd.Series:
    if "close" not in skew.columns:
        raise ValueError("SKEW history missing close")
    frame = skew.copy()
    frame.index = pd.to_datetime(frame.index, errors="raise").tz_localize(None).normalize()
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ValueError("SKEW history contains duplicate dates")
    close = pd.to_numeric(frame["close"], errors="coerce")
    if bool(close.dropna().le(0.0).any()):
        raise ValueError("SKEW contains non-positive close values")
    return close.rename("skew_close")


def build_skew_trace(daily: pd.DataFrame, skew: pd.DataFrame) -> pd.DataFrame:
    """Build a point-in-time 252-session rolling 80th-percentile SKEW flag."""
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")
    close = _normalise_skew(skew).reindex(daily.index)
    threshold = close.rolling(SKEW_WINDOW, min_periods=SKEW_WINDOW).quantile(SKEW_HIGH_QUANTILE)
    high = close.notna() & threshold.notna() & close.ge(threshold)
    return pd.DataFrame(
        {
            "skew_close": close,
            "skew_high_threshold": threshold,
            "skew_high_at_close": high.astype(bool),
        },
        index=daily.index,
    )


def _forward_path_metrics(returns: pd.Series) -> tuple[float, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if len(values) != len(returns):
        raise ValueError("forward path contains missing returns")
    wealth = (1.0 + values).cumprod()
    path = pd.concat([pd.Series([1.0]), wealth.reset_index(drop=True)], ignore_index=True)
    drawdown = path / path.cummax() - 1.0
    return float(wealth.iloc[-1] - 1.0), float(drawdown.min())


def build_state0_forward_paths(
    daily: pd.DataFrame,
    trace: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Measure next-open-executable forward QQQ paths after state-0 signal closes."""
    required = {"position_state", "QQQ_next_open_return"}
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"daily trace missing columns: {missing}")
    if tuple(int(value) for value in horizons) != HORIZONS:
        raise ValueError(f"frozen horizons must equal {HORIZONS}")

    index = daily.index
    eligible = daily["position_state"].astype(int).eq(0) & trace["skew_high_threshold"].notna()
    rows: list[dict[str, Any]] = []
    max_horizon = max(HORIZONS)
    for date in index[eligible]:
        location = int(index.get_loc(date))
        first = location + 1
        if first + max_horizon > len(index):
            continue
        row: dict[str, Any] = {
            "signal_date": date,
            "year": int(date.year),
            "skew_close": float(trace.loc[date, "skew_close"]),
            "skew_high_threshold": float(trace.loc[date, "skew_high_threshold"]),
            "skew_high": bool(trace.loc[date, "skew_high_at_close"]),
        }
        valid = True
        for horizon in HORIZONS:
            sample = daily["QQQ_next_open_return"].iloc[first : first + horizon]
            if len(sample) != horizon or sample.isna().any():
                valid = False
                break
            forward_return, max_drawdown = _forward_path_metrics(sample)
            row[f"forward_return_{horizon}d"] = forward_return
            row[f"forward_max_drawdown_{horizon}d"] = max_drawdown
        if valid:
            rows.append(row)
    if not rows:
        raise ValueError("no complete state-0 forward paths")
    return pd.DataFrame(rows).sort_values("signal_date").reset_index(drop=True)


def _group_summary(sample: pd.DataFrame, *, segment: str, group: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "segment": segment,
        "group": group,
        "observations": int(len(sample)),
        "years": int(sample["year"].nunique()) if len(sample) else 0,
    }
    for horizon in HORIZONS:
        returns = sample[f"forward_return_{horizon}d"].astype(float)
        drawdown = sample[f"forward_max_drawdown_{horizon}d"].astype(float)
        row[f"median_return_{horizon}d"] = float(returns.median()) if len(returns) else None
        row[f"return_q10_{horizon}d"] = float(returns.quantile(0.10)) if len(returns) else None
        row[f"median_max_drawdown_{horizon}d"] = float(drawdown.median()) if len(drawdown) else None
        row[f"max_drawdown_q25_{horizon}d"] = (
            float(drawdown.quantile(0.25)) if len(drawdown) else None
        )
    return row


def summarize_state0_information(paths: pd.DataFrame) -> pd.DataFrame:
    """Summarize high vs ordinary SKEW in full, early and late halves."""
    if paths.empty:
        raise ValueError("paths cannot be empty")
    split = max(1, min(len(paths) - 1, len(paths) // 2))
    segments = {
        "full": paths,
        "early": paths.iloc[:split],
        "late": paths.iloc[split:],
    }
    rows: list[dict[str, Any]] = []
    for segment, sample in segments.items():
        rows.append(
            _group_summary(sample.loc[~sample["skew_high"]], segment=segment, group="ordinary")
        )
        rows.append(
            _group_summary(sample.loc[sample["skew_high"]], segment=segment, group="high_skew")
        )
    return pd.DataFrame(rows)


def information_gate(paths: pd.DataFrame, summary: pd.DataFrame) -> dict[str, Any]:
    """Apply the predeclared non-portfolio SKEW information gate."""
    high = paths.loc[paths["skew_high"]].copy()
    year_counts = high["year"].value_counts()
    high_years = int(len(year_counts))
    largest_year_share = float(year_counts.max() / year_counts.sum()) if len(year_counts) else 1.0
    table = summary.set_index(["segment", "group"])

    def metric(segment: str, group: str, name: str) -> float:
        return float(table.loc[(segment, group), name])

    drawdown_checks: dict[str, bool] = {}
    for horizon in HORIZONS:
        for segment in ("early", "late"):
            key = f"dd_{horizon}d_{segment}"
            drawdown_checks[key] = metric(
                segment, "high_skew", f"median_max_drawdown_{horizon}d"
            ) < metric(segment, "ordinary", f"median_max_drawdown_{horizon}d")

    return_check_by_horizon: dict[int, bool] = {}
    for horizon in HORIZONS:
        return_check_by_horizon[horizon] = all(
            metric(segment, "high_skew", f"return_q10_{horizon}d")
            < metric(segment, "ordinary", f"return_q10_{horizon}d")
            for segment in ("early", "late")
        )

    full_sign_agreement = all(
        metric("full", "high_skew", f"median_max_drawdown_{horizon}d")
        < metric("full", "ordinary", f"median_max_drawdown_{horizon}d")
        for horizon in HORIZONS
    )
    checks = {
        "high_skew_years": high_years >= 8,
        "year_concentration": largest_year_share <= 0.35,
        "drawdown_20d_early": drawdown_checks["dd_20d_early"],
        "drawdown_20d_late": drawdown_checks["dd_20d_late"],
        "drawdown_60d_early": drawdown_checks["dd_60d_early"],
        "drawdown_60d_late": drawdown_checks["dd_60d_late"],
        "tail_return_one_horizon": any(return_check_by_horizon.values()),
        "full_sample_sign_agreement": full_sign_agreement,
    }
    return {
        "checks": checks,
        "metrics": {
            "high_skew_observations": int(len(high)),
            "high_skew_years": high_years,
            "largest_high_skew_year_share": largest_year_share,
            "return_tail_checks": return_check_by_horizon,
        },
        "portfolio_experiment_authorized": bool(all(checks.values())),
    }
