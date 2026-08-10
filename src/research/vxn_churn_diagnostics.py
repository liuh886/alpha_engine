"""Diagnostics for churn and dwell time in the frozen v4.1 VXN attack layer."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult


def state_dwell_table(result: StrategyResult) -> pd.DataFrame:
    """Return contiguous state runs with duration and realised return."""

    daily = result.daily.copy()
    groups = daily["position_state"].ne(daily["position_state"].shift()).cumsum()
    rows: list[dict[str, Any]] = []
    for _, group in daily.groupby(groups):
        returns = group["net_return"].dropna()
        rows.append(
            {
                "strategy": str(result.metrics["strategy"]),
                "state": int(group["position_state"].iloc[0]),
                "start_date": group.index.min(),
                "end_date": group.index.max(),
                "sessions": int(len(group)),
                "cumulative_net_return": float((1.0 + returns).prod() - 1.0),
                "worst_daily_net_return": float(returns.min()),
                "positive_session_rate": float(returns.gt(0).mean()),
            }
        )
    return pd.DataFrame(rows)


def round_trip_summary(dwell: pd.DataFrame, thresholds: Sequence[int]) -> pd.DataFrame:
    """Count short leveraged episodes at predeclared session thresholds."""

    leveraged = dwell[dwell["state"].eq(1)].copy()
    rows: list[dict[str, Any]] = []
    for strategy, group in leveraged.groupby("strategy"):
        for threshold in thresholds:
            selected = group[group["sessions"].le(int(threshold))]
            rows.append(
                {
                    "strategy": strategy,
                    "threshold_sessions": int(threshold),
                    "episode_count": int(len(selected)),
                    "share_of_leverage_episodes": (
                        float(len(selected) / len(group)) if len(group) else 0.0
                    ),
                    "aggregate_compounded_return": (
                        float((1.0 + selected["cumulative_net_return"]).prod() - 1.0)
                        if len(selected)
                        else 0.0
                    ),
                    "negative_episode_rate": (
                        float(selected["cumulative_net_return"].lt(0).mean())
                        if len(selected)
                        else 0.0
                    ),
                }
            )
    return pd.DataFrame(rows)


def reentry_cycles(dwell: pd.DataFrame, daily_index: pd.Index) -> pd.DataFrame:
    """Measure the gap from each leverage exit to the next leverage entry."""

    positions = {pd.Timestamp(date): idx for idx, date in enumerate(daily_index)}
    rows: list[dict[str, Any]] = []
    for strategy, group in dwell.groupby("strategy"):
        ordered = group.sort_values("start_date").reset_index(drop=True)
        leveraged_locations = list(ordered.index[ordered["state"].eq(1)])
        for location in leveraged_locations:
            current = ordered.loc[location]
            future = ordered.loc[(ordered.index > location) & ordered["state"].eq(1)]
            if future.empty:
                continue
            next_run = future.iloc[0]
            exit_date = pd.Timestamp(current["end_date"])
            reentry_date = pd.Timestamp(next_run["start_date"])
            rows.append(
                {
                    "strategy": strategy,
                    "exit_date": exit_date,
                    "reentry_date": reentry_date,
                    "gap_sessions": int(positions[reentry_date] - positions[exit_date]),
                    "same_calendar_month": bool(
                        exit_date.to_period("M") == reentry_date.to_period("M")
                    ),
                }
            )
    return pd.DataFrame(rows)


def transition_cost_by_reason(result: StrategyResult) -> pd.DataFrame:
    """Aggregate turnover and explicit costs by executed transition reason."""

    trades = result.trades.copy()
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "strategy",
                "executed_reason",
                "events",
                "turnover_units",
                "transaction_cost",
            ]
        )
    grouped = (
        trades.groupby("executed_reason", dropna=False)
        .agg(
            events=("executed_reason", "size"),
            turnover_units=("turnover_units", "sum"),
            transaction_cost=("transaction_cost", "sum"),
        )
        .reset_index()
    )
    grouped.insert(0, "strategy", str(result.metrics["strategy"]))
    return grouped


def _future_compounded_return(
    prepared: pd.DataFrame, location: int, column: str, horizon: int
) -> float:
    window = prepared.iloc[location : location + int(horizon)]
    values = window[column].dropna()
    if len(values) != int(horizon):
        return np.nan
    return float((1.0 + values).prod() - 1.0)


def vxn_only_exit_events(
    prepared: pd.DataFrame,
    baseline: StrategyResult,
    overlay: StrategyResult,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Attribute exits where VXN alone removed leverage while VIX stayed leveraged."""

    baseline_daily = baseline.daily
    overlay_daily = overlay.daily
    previous_overlay = overlay_daily["position_state"].shift(1)
    mask = (
        previous_overlay.eq(1)
        & overlay_daily["position_state"].eq(0)
        & baseline_daily["position_state"].eq(1)
    )
    rows: list[dict[str, Any]] = []
    for date in overlay_daily.index[mask.fillna(False)]:
        location = int(prepared.index.get_loc(date))
        signal_location = max(location - 1, 0)
        future_overlay = overlay_daily.iloc[location + 1 :]
        reentries = future_overlay.index[future_overlay["position_state"].eq(1)]
        reentry_date = reentries[0] if len(reentries) else pd.NaT
        reentry_gap = (
            int(overlay_daily.index.get_loc(reentry_date) - overlay_daily.index.get_loc(date))
            if pd.notna(reentry_date)
            else np.nan
        )
        future_equal = overlay_daily.iloc[location + 1 :][
            overlay_daily.iloc[location + 1 :]["position_state"].eq(
                baseline_daily.iloc[location + 1 :]["position_state"]
            )
        ]
        end_location = (
            int(overlay_daily.index.get_loc(future_equal.index[0]) - 1)
            if not future_equal.empty
            else len(overlay_daily) - 1
        )
        baseline_segment = baseline_daily.iloc[location : end_location + 1]["net_return"]
        overlay_segment = overlay_daily.iloc[location : end_location + 1]["net_return"]
        row: dict[str, Any] = {
            "exit_date": date,
            "signal_date": prepared.index[signal_location],
            "reentry_date": reentry_date,
            "reentry_gap_sessions": reentry_gap,
            "different_position_sessions": int(end_location - location + 1),
            "signal_vix_stress": bool(prepared.iloc[signal_location]["vix_stress"]),
            "signal_vxn_stress": bool(prepared.iloc[signal_location]["vxn_stress"]),
            "signal_below_ma_short_n": bool(prepared.iloc[signal_location]["below_ma_short_n"]),
            "baseline_return_while_different": float((1.0 + baseline_segment).prod() - 1.0),
            "overlay_return_while_different": float((1.0 + overlay_segment).prod() - 1.0),
        }
        row["overlay_minus_baseline_while_different"] = (
            row["overlay_return_while_different"] - row["baseline_return_while_different"]
        )
        for horizon in horizons:
            row[f"QQQ_return_{int(horizon)}d"] = _future_compounded_return(
                prepared, location, "QQQ_next_open_return", int(horizon)
            )
            row[f"TQQQ_return_{int(horizon)}d"] = _future_compounded_return(
                prepared, location, "TQQQ_next_open_return", int(horizon)
            )
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_churn(
    baseline: StrategyResult,
    overlay: StrategyResult,
    dwell: pd.DataFrame,
    cycles: pd.DataFrame,
    exit_events: pd.DataFrame,
    *,
    quick_reentry_sessions: int,
) -> dict[str, Any]:
    """Summarise whether VXN creates a recurring short-exit churn pattern."""

    summary: dict[str, Any] = {
        "baseline_switch_count": int(baseline.metrics["switch_count"]),
        "overlay_switch_count": int(overlay.metrics["switch_count"]),
        "incremental_switches": int(
            overlay.metrics["switch_count"] - baseline.metrics["switch_count"]
        ),
        "baseline_turnover_units": float(baseline.metrics["turnover_units"]),
        "overlay_turnover_units": float(overlay.metrics["turnover_units"]),
        "incremental_turnover_units": float(
            overlay.metrics["turnover_units"] - baseline.metrics["turnover_units"]
        ),
    }
    leverage_dwell = dwell[dwell["state"].eq(1)]
    for strategy in (
        str(baseline.metrics["strategy"]),
        str(overlay.metrics["strategy"]),
    ):
        group = leverage_dwell[leverage_dwell["strategy"].eq(strategy)]
        summary[f"{strategy}_leverage_episode_count"] = int(len(group))
        summary[f"{strategy}_median_leverage_dwell"] = (
            float(group["sessions"].median()) if len(group) else np.nan
        )
    overlay_cycles = cycles[cycles["strategy"].eq(str(overlay.metrics["strategy"]))]
    summary["overlay_same_month_reentries"] = int(overlay_cycles["same_calendar_month"].sum())
    summary["overlay_reentries_within_quick_window"] = int(
        overlay_cycles["gap_sessions"].le(int(quick_reentry_sessions)).sum()
    )
    summary["vxn_only_exit_count"] = int(len(exit_events))
    quick = exit_events[exit_events["reentry_gap_sessions"].le(int(quick_reentry_sessions))]
    slow = exit_events[exit_events["reentry_gap_sessions"].gt(int(quick_reentry_sessions))]
    summary["vxn_only_quick_exit_count"] = int(len(quick))
    summary["vxn_only_quick_exit_positive_rate"] = (
        float(quick["overlay_minus_baseline_while_different"].gt(0).mean())
        if len(quick)
        else np.nan
    )
    summary["vxn_only_quick_exit_aggregate_delta"] = (
        float(quick["overlay_minus_baseline_while_different"].sum()) if len(quick) else 0.0
    )
    summary["vxn_only_slow_exit_aggregate_delta"] = (
        float(slow["overlay_minus_baseline_while_different"].sum()) if len(slow) else 0.0
    )
    summary["diagnostic_only"] = True
    summary["strategy_rule_changed"] = False
    return summary
