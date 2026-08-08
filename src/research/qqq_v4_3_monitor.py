"""Decision-grade next-open monitor for formal QQQ Rotation v4.3.

The monitor evaluates the frozen v4.3 rules at the latest completed close. It
compares actual target weights, not only the inherited formal-state number, so
Panic Repair and SGOV slow-bear-defense changes cannot be missed.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from src.research.v4_2_panic_repair_boost import (
    TQQQ_BOOST,
    build_panic_repair_trace,
)
from src.research.v4_2_rsi_vix_sgov_experiment import wilder_rsi

ASSETS = ("QQQI", "QQQ", "TQQQ", "SGOV")
STATE_LABELS = {0: "defensive", 1: "bridge", 2: "partial_leverage"}


def _base_weights(state: int) -> dict[str, float]:
    if state == 0:
        return {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0}
    if state == 1:
        return {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0}
    if state == 2:
        return {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75, "SGOV": 0.0}
    raise ValueError(f"unsupported formal v4.3 state: {state}")


def _panic_boost(weights: dict[str, float]) -> dict[str, float]:
    output = dict(weights)
    funding_assets = ("QQQI", "QQQ")
    available = sum(output[asset] for asset in funding_assets)
    if available < TQQQ_BOOST - 1e-12:
        raise ValueError("insufficient non-TQQQ sleeve for v4.3 Panic Repair")
    scale = (available - TQQQ_BOOST) / available
    for asset in funding_assets:
        output[asset] *= scale
    output["TQQQ"] += TQQQ_BOOST
    return output


def _context(row: pd.Series) -> dict[str, Any]:
    def value(column: str) -> float | None:
        raw = row.get(column)
        return None if raw is None or pd.isna(raw) else float(raw)

    return {
        "qqq_close": value("qqq_close"),
        "ma20": value("ma_short"),
        "ma50": value("ma_medium"),
        "ma200": value("ma_long"),
        "vix_close": value("vix_close"),
        "vxn_close": value("vxn_close"),
        "vix_regime": str(row.get("vix_regime", "unavailable")),
        "vxn_regime": str(row.get("vxn_regime", "unavailable")),
        "stress_price_failure": bool(row.get("stress_price_failure", False)),
        "vix_easing": bool(row.get("vix_easing", False)),
        "vix_normalized": bool(row.get("vix_normalized", False)),
        "early_repair": bool(row.get("early_repair", False)),
        "shock_memory": bool(row.get("shock_memory", False)),
    }


def latest_next_open_target(
    prepared: pd.DataFrame,
    decisions: pd.DataFrame,
    fear_greed: pd.DataFrame,
    qqq_close: pd.Series,
) -> dict[str, Any]:
    """Evaluate v4.3 target weights after the latest close in ``prepared``."""
    if len(prepared) < 2:
        raise ValueError("v4.3 monitor requires at least two prepared sessions")
    if not prepared.index.equals(decisions.index):
        raise ValueError("prepared data and decisions must share an exact index")

    daily = prepared.join(decisions[["decision_state", "decision_reason"]], how="left")
    daily["rsi_14"] = wilder_rsi(qqq_close, period=14).reindex(daily.index)
    if bool(daily["rsi_14"].isna().iloc[-1]):
        raise ValueError("latest v4.3 RSI is unavailable")
    panic_trace = build_panic_repair_trace(daily, fear_greed)

    latest = daily.iloc[-1]
    previous = daily.iloc[-2]
    state = int(latest["decision_state"])
    ma200_falling = bool(
        pd.notna(latest["ma_long"])
        and pd.notna(previous["ma_long"])
        and float(latest["ma_long"]) < float(previous["ma_long"])
    )
    price_repaired = not bool(latest["stress_price_failure"])
    volatility_repaired = bool(latest["vix_easing"]) or bool(latest["vix_normalized"])
    fast_price_vol_repair = price_repaired and volatility_repaired
    strong_defense = state == 0 and ma200_falling and not fast_price_vol_repair
    panic_active = bool(panic_trace.iloc[-1]["panic_repair_active_at_close"])

    if strong_defense:
        weights = {"QQQI": 0.5, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.5}
        overlay = "ma200_slow_bear_defense"
    else:
        weights = _base_weights(state)
        if panic_active and state in (0, 1):
            weights = _panic_boost(weights)
            overlay = "panic_repair_risk_budget"
        else:
            overlay = "formal_state_allocation"

    if abs(sum(weights.values()) - 1.0) > 1e-10:
        raise AssertionError("v4.3 target weights must sum to one")
    return {
        "signal_date": prepared.index[-1].date().isoformat(),
        "formal_state": state,
        "formal_state_label": STATE_LABELS[state],
        "formal_decision_reason": str(latest["decision_reason"]),
        "target_weights": weights,
        "overlay": overlay,
        "panic_repair_active": panic_active,
        "ma200_falling": ma200_falling,
        "fast_price_vol_repair": fast_price_vol_repair,
        "strong_defense": strong_defense,
        "fear_greed_score": (
            None
            if pd.isna(panic_trace.iloc[-1]["fear_greed_score"])
            else float(panic_trace.iloc[-1]["fear_greed_score"])
        ),
        "rsi_14": float(daily.iloc[-1]["rsi_14"]),
        "context": _context(latest),
    }


def build_v4_3_monitor_summary(
    prepared: pd.DataFrame,
    decisions: pd.DataFrame,
    fear_greed: pd.DataFrame,
    qqq_close: pd.Series,
    *,
    data_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Build current-open and next-open v4.3 targets from adjacent closes."""
    next_target = latest_next_open_target(prepared, decisions, fear_greed, qqq_close)
    current_target = latest_next_open_target(
        prepared.iloc[:-1].copy(),
        decisions.iloc[:-1].copy(),
        fear_greed,
        qqq_close,
    )
    return {
        "schema_version": "1.0.0",
        "model_id": "qqqi_qqq_tqqq_v4_3",
        "display_name": "QQQ Rotation v4.3",
        "latest_data_date": prepared.index[-1].date().isoformat(),
        "current_open_target": current_target,
        "next_open_target": next_target,
        "data_identity": dict(data_identity),
        "research_only": True,
        "trade_ready": False,
    }
