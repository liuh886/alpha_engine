"""Prospective evidence helpers for the frozen v4.1 VXN leverage veto."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult

STATE_LABELS = {0: "defensive", 1: "attack", 2: "partial_leverage"}


def prospective_return_metrics(
    result: StrategyResult,
    start_date: str | pd.Timestamp,
) -> dict[str, Any]:
    """Calculate metrics only from economic returns on or after the frozen start."""

    start = pd.Timestamp(start_date).tz_localize(None).normalize()
    sample = result.daily.loc[result.daily.index >= start].copy()
    returns = sample["net_return"].dropna()
    if returns.empty:
        return {
            "strategy": str(result.metrics["strategy"]),
            "status": "awaiting_first_prospective_return",
            "start_date": start.date().isoformat(),
            "end_date": None,
            "observations": 0,
            "total_return": 0.0,
            "cagr": None,
            "annual_volatility": None,
            "sharpe": None,
            "sortino": None,
            "max_drawdown": 0.0,
            "calmar": None,
            "switch_count": 0,
            "turnover_units": 0.0,
            "transaction_cost_paid": 0.0,
            "state_counts": {
                "defensive": 0,
                "attack": 0,
                "partial_leverage": 0,
            },
        }

    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    observations = int(len(returns))
    cagr = float(equity.iloc[-1] ** (252.0 / observations) - 1.0)
    volatility = float(returns.std(ddof=1) * np.sqrt(252.0)) if observations > 1 else 0.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * np.sqrt(252.0))
        if observations > 1 and returns.std(ddof=1) > 0
        else None
    )
    downside = returns[returns.lt(0.0)]
    downside_deviation = (
        float(downside.std(ddof=1) * np.sqrt(252.0)) if len(downside) > 1 else 0.0
    )
    sortino = (
        float(returns.mean() * 252.0 / downside_deviation)
        if downside_deviation > 0
        else None
    )
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0 else None

    state_counts = (
        sample.loc[returns.index, "position_state"]
        .value_counts()
        .reindex([0, 1, 2], fill_value=0)
    )
    state_series = sample.loc[returns.index, "position_state"]
    switches = int(max(state_series.ne(state_series.shift()).sum() - 1, 0))
    return {
        "strategy": str(result.metrics["strategy"]),
        "status": "prospective_observations_available",
        "start_date": returns.index.min().date().isoformat(),
        "end_date": returns.index.max().date().isoformat(),
        "observations": observations,
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "switch_count": switches,
        "turnover_units": float(sample.loc[returns.index, "turnover_units"].sum()),
        "transaction_cost_paid": float(
            sample.loc[returns.index, "transaction_cost"].sum()
        ),
        "state_counts": {
            STATE_LABELS[state]: int(state_counts.loc[state]) for state in (0, 1, 2)
        },
    }


def prospective_state_differences(
    prepared: pd.DataFrame,
    baseline_decisions: pd.DataFrame,
    overlay_decisions: pd.DataFrame,
    *,
    start_date: str | pd.Timestamp,
    horizons: Sequence[int] = (5, 10, 20, 40),
) -> pd.DataFrame:
    """Record prospective closes where VXN changes the next-session state."""

    start = pd.Timestamp(start_date).tz_localize(None).normalize()
    changed = baseline_decisions["decision_state"].ne(
        overlay_decisions["decision_state"]
    )
    changed &= baseline_decisions.index >= start
    rows: list[dict[str, Any]] = []
    for location in np.flatnonzero(changed.to_numpy(dtype=bool)):
        date = prepared.index[int(location)]
        baseline_state = int(baseline_decisions.iloc[int(location)]["decision_state"])
        overlay_state = int(overlay_decisions.iloc[int(location)]["decision_state"])
        if baseline_state == 2 and overlay_state == 1:
            event_type = "vxn_blocks_or_exits_leverage"
        elif baseline_state != overlay_state:
            event_type = "vxn_state_difference"
        else:
            event_type = "none"
        row: dict[str, Any] = {
            "signal_date": date,
            "event_type": event_type,
            "baseline_decision_state": baseline_state,
            "overlay_decision_state": overlay_state,
            "baseline_decision_label": STATE_LABELS[baseline_state],
            "overlay_decision_label": STATE_LABELS[overlay_state],
            "baseline_reason": str(
                baseline_decisions.iloc[int(location)]["decision_reason"]
            ),
            "overlay_reason": str(
                overlay_decisions.iloc[int(location)]["decision_reason"]
            ),
            "vix_close": float(prepared.iloc[int(location)]["vix_close"]),
            "vxn_close": float(prepared.iloc[int(location)]["vxn_close"]),
            "vix_stress": bool(prepared.iloc[int(location)]["vix_stress"]),
            "vxn_stress": bool(prepared.iloc[int(location)]["vxn_stress"]),
        }
        for horizon in horizons:
            window = prepared.iloc[int(location) + 1 : int(location) + 1 + int(horizon)]
            values = window["TQQQ_next_open_return"].dropna()
            row[f"TQQQ_return_{int(horizon)}d"] = (
                float((1.0 + values).prod() - 1.0)
                if len(values) == int(horizon)
                else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def latest_monitor_snapshot(
    prepared: pd.DataFrame,
    overlay: StrategyResult,
    overlay_decisions: pd.DataFrame,
) -> dict[str, Any]:
    """Report the latest executed position and latest close-derived next decision."""

    if prepared.empty:
        raise ValueError("prepared data is empty")
    if overlay_decisions.empty:
        raise ValueError("overlay decisions are empty")
    latest_signal_date = prepared.index[-1]
    latest_decision = overlay_decisions.iloc[-1]
    latest_prepared = prepared.iloc[-1]

    executed: dict[str, Any] | None = None
    if not overlay.daily.empty:
        latest_economic_date = overlay.daily.index[-1]
        latest_daily = overlay.daily.iloc[-1]
        executed = {
            "economic_date": latest_economic_date.date().isoformat(),
            "position_state": int(latest_daily["position_state"]),
            "position_label": str(latest_daily["position_label"]),
            "executed_reason": str(latest_daily["executed_reason"]),
            "weights": {
                "QQQI": float(latest_daily["weight_QQQI"]),
                "QQQ": float(latest_daily["weight_QQQ"]),
                "TQQQ": float(latest_daily["weight_TQQQ"]),
            },
        }

    decision_state = int(latest_decision["decision_state"])
    return {
        "latest_executed_position": executed,
        "latest_close_signal": {
            "signal_date": latest_signal_date.date().isoformat(),
            "decision_state": decision_state,
            "decision_label": STATE_LABELS[decision_state],
            "decision_reason": str(latest_decision["decision_reason"]),
            "vix_close": float(latest_prepared["vix_close"]),
            "vxn_close": float(latest_prepared["vxn_close"]),
            "vix_stress": bool(latest_prepared["vix_stress"]),
            "vix_easing": bool(latest_prepared["vix_easing"]),
            "vix_normalized": bool(latest_prepared["vix_normalized"]),
            "vxn_stress": bool(latest_prepared["vxn_stress"]),
        },
    }


def monitoring_status(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    """Return one conservative overall monitoring status."""

    observations = [int(item.get("observations", 0)) for item in metrics.values()]
    if not observations or max(observations) == 0:
        return "awaiting_first_prospective_return"
    return "prospective_monitoring_active"
