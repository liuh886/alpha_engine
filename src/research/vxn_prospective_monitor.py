"""Prospective evidence helpers for the frozen v4.1/v4.2 VXN state machine."""

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
            "state_counts": None,
        }

    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    observations = int(len(returns))
    cagr = float(equity.iloc[-1] ** (252.0 / observations) - 1.0)
    volatility = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252.0))
        if returns.std(ddof=0) > 1e-12
        else None
    )
    downside = np.minimum(returns.to_numpy(dtype=float), 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    sortino = (
        float(returns.mean() / downside_deviation * np.sqrt(252.0))
        if downside_deviation > 1e-12
        else None
    )
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < -1e-12 else None

    state_counts: dict[str, int] | None = None
    switches = 0
    if "position_state" in sample.columns:
        state_series = sample.loc[returns.index, "position_state"].astype(int)
        counts = state_series.value_counts().reindex([0, 1, 2], fill_value=0)
        state_counts = {STATE_LABELS[state]: int(counts.loc[state]) for state in (0, 1, 2)}
        switches = int(max(state_series.ne(state_series.shift()).sum() - 1, 0))

    turnover_units = (
        float(sample.loc[returns.index, "turnover_units"].sum())
        if "turnover_units" in sample.columns
        else 0.0
    )
    transaction_cost_paid = (
        float(sample.loc[returns.index, "transaction_cost"].sum())
        if "transaction_cost" in sample.columns
        else 0.0
    )
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
        "turnover_units": turnover_units,
        "transaction_cost_paid": transaction_cost_paid,
        "state_counts": state_counts,
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
    changed = baseline_decisions["decision_state"].ne(overlay_decisions["decision_state"])
    changed &= baseline_decisions.index >= start
    rows: list[dict[str, Any]] = []
    for location in np.flatnonzero(changed.to_numpy(dtype=bool)):
        date = prepared.index[int(location)]
        baseline_state = int(baseline_decisions.iloc[int(location)]["decision_state"])
        overlay_state = int(overlay_decisions.iloc[int(location)]["decision_state"])
        if baseline_state == 2 and overlay_state == 1:
            event_type = "vxn_blocks_or_exits_leverage"
        else:
            event_type = "vxn_state_difference"
        row: dict[str, Any] = {
            "signal_date": date,
            "event_type": event_type,
            "baseline_decision_state": baseline_state,
            "overlay_decision_state": overlay_state,
            "baseline_decision_label": STATE_LABELS[baseline_state],
            "overlay_decision_label": STATE_LABELS[overlay_state],
            "baseline_reason": str(baseline_decisions.iloc[int(location)]["decision_reason"]),
            "overlay_reason": str(overlay_decisions.iloc[int(location)]["decision_reason"]),
            "vix_close": float(prepared.iloc[int(location)]["vix_close"]),
            "vxn_close": float(prepared.iloc[int(location)]["vxn_close"]),
            "vix_stress": bool(prepared.iloc[int(location)]["vix_stress"]),
            "vxn_stress": bool(prepared.iloc[int(location)]["vxn_stress"]),
        }
        for horizon in horizons:
            window = prepared.iloc[int(location) + 1 : int(location) + 1 + int(horizon)]
            values = window["TQQQ_next_open_return"].dropna()
            row[f"TQQQ_return_{int(horizon)}d"] = (
                float((1.0 + values).prod() - 1.0) if len(values) == int(horizon) else np.nan
            )
        rows.append(row)
    columns = [
        "signal_date",
        "event_type",
        "baseline_decision_state",
        "overlay_decision_state",
        "baseline_decision_label",
        "overlay_decision_label",
        "baseline_reason",
        "overlay_reason",
        "vix_close",
        "vxn_close",
        "vix_stress",
        "vxn_stress",
        *[f"TQQQ_return_{int(horizon)}d" for horizon in horizons],
    ]
    return pd.DataFrame(rows, columns=columns)


def _optional_float(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _relative_distance(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or abs(reference) <= 1e-12:
        return None
    return value / reference - 1.0


def _latest_state_interval(daily: pd.DataFrame) -> tuple[str | None, int | None]:
    if daily.empty or "position_state" not in daily.columns:
        return None, None
    states = daily["position_state"].astype(int)
    current_state = int(states.iloc[-1])
    change_positions = np.flatnonzero(states.ne(states.shift()).to_numpy(dtype=bool))
    start_position = int(change_positions[-1]) if len(change_positions) else 0
    if int(states.iloc[start_position]) != current_state:
        raise AssertionError("latest state interval could not be resolved")
    return (
        states.index[start_position].date().isoformat(),
        int(len(states) - start_position),
    )


def latest_monitor_snapshot(
    prepared: pd.DataFrame,
    overlay: StrategyResult,
    overlay_decisions: pd.DataFrame,
) -> dict[str, Any]:
    """Report the executed position and a decision-grade latest close snapshot."""

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
        state_entry_date, state_age_sessions = _latest_state_interval(overlay.daily)
        executed = {
            "economic_date": latest_economic_date.date().isoformat(),
            "position_state": int(latest_daily["position_state"]),
            "position_label": str(latest_daily["position_label"]),
            "executed_reason": str(latest_daily["executed_reason"]),
            "state_entry_date": state_entry_date,
            "state_age_sessions": state_age_sessions,
            "weights": {
                "QQQI": float(latest_daily["weight_QQQI"]),
                "QQQ": float(latest_daily["weight_QQQ"]),
                "TQQQ": float(latest_daily["weight_TQQQ"]),
            },
        }

    qqq_close = _optional_float(latest_prepared, "qqq_close")
    ma_short = _optional_float(latest_prepared, "ma_short")
    ma_medium = _optional_float(latest_prepared, "ma_medium")
    ma_long = _optional_float(latest_prepared, "ma_long")
    price_context = {
        "qqq_close": qqq_close,
        "ma20": ma_short,
        "ma50": ma_medium,
        "ma200": ma_long,
        "qqq_vs_ma20": _relative_distance(qqq_close, ma_short),
        "qqq_vs_ma50": _relative_distance(qqq_close, ma_medium),
        "qqq_vs_ma200": _relative_distance(qqq_close, ma_long),
        "shock_drawdown_now": _optional_float(latest_prepared, "shock_drawdown_now"),
        "shock_memory": bool(latest_prepared.get("shock_memory", False)),
        "early_repair": bool(latest_prepared.get("early_repair", False)),
        "medium_repair": bool(latest_prepared.get("medium_repair", False)),
        "secondary_confirmation": bool(latest_prepared.get("secondary_confirmation", False)),
        "below_ma_short_n": bool(latest_prepared.get("below_ma_short_n", False)),
        "long_break": bool(latest_prepared.get("long_break", False)),
        "stress_price_failure": bool(latest_prepared.get("stress_price_failure", False)),
    }
    volatility_context = {
        "vix_close": _optional_float(latest_prepared, "vix_close"),
        "vix_q_stress": _optional_float(latest_prepared, "vix_q_stress"),
        "vix_q_normal": _optional_float(latest_prepared, "vix_q_normal"),
        "vix_return_1d": _optional_float(latest_prepared, "vix_return_1d"),
        "vix_return_5d": _optional_float(latest_prepared, "vix_return_5d"),
        "vix_retreat_from_peak": _optional_float(latest_prepared, "vix_retreat_from_peak"),
        "vix_regime": str(latest_prepared.get("vix_regime", "unavailable")),
        "vix_stress": bool(latest_prepared.get("vix_stress", False)),
        "vix_easing": bool(latest_prepared.get("vix_easing", False)),
        "vix_normalized": bool(latest_prepared.get("vix_normalized", False)),
        "vxn_close": _optional_float(latest_prepared, "vxn_close"),
        "vxn_q_stress": _optional_float(latest_prepared, "vxn_q_stress"),
        "vxn_q_normal": _optional_float(latest_prepared, "vxn_q_normal"),
        "vxn_return_1d": _optional_float(latest_prepared, "vxn_return_1d"),
        "vxn_return_5d": _optional_float(latest_prepared, "vxn_return_5d"),
        "vxn_retreat_from_peak": _optional_float(latest_prepared, "vxn_retreat_from_peak"),
        "vxn_regime": str(latest_prepared.get("vxn_regime", "unavailable")),
        "vxn_stress": bool(latest_prepared.get("vxn_stress", False)),
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
            "price_context": price_context,
            "volatility_context": volatility_context,
        },
    }


def monitoring_status(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    """Return one conservative overall monitoring status."""

    observations = [int(item.get("observations", 0)) for item in metrics.values()]
    if not observations or max(observations) == 0:
        return "awaiting_first_prospective_return"
    return "prospective_monitoring_active"
