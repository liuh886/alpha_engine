"""Runtime wrapper for the v4.16 regularized action-advantage experiment."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

import src.research.v4_16_action_advantage_model as core
from src.research.v4_14_multifactor_event_discovery import (
    _forward_total_return,
    build_multifactor_feature_frame,
)

_EVENT_COLUMNS = (
    "sample",
    "fold",
    "event_family",
    "action",
    "event_id",
    "rule_id",
    "signal_close_date",
    "execution_date",
    "event_end_date",
    "holding_sessions",
    "predicted_advantage",
    "second_best_advantage",
    "predicted_margin",
    "realized_advantage",
    "win",
)


def build_action_advantage_frame(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    """Build factors, interactions, labels and the global non-overlap sample mask."""

    frame = build_multifactor_feature_frame(bars, proxy_baseline_daily).copy()
    frame["qqq_rsi20_centered"] = (frame["qqq_rsi20"] - 50.0) / 50.0
    feature_names = [str(value) for value in contract["base_features"]]
    for raw in contract["interactions"]:
        name = str(raw["name"])
        left = str(raw["left"])
        right = str(raw["right"])
        frame[name] = pd.to_numeric(frame[left], errors="coerce") * pd.to_numeric(
            frame[right], errors="coerce"
        )
        feature_names.append(name)

    baseline_return = proxy_baseline_daily["net_return"].reindex(frame.index)
    baseline_10d = _forward_total_return(baseline_return, 10)
    baseline_5d = _forward_total_return(baseline_return, 5)
    acceleration_daily = (
        0.25 * frame["qqq_next_open_return"]
        + 0.75 * frame["tqqq_next_open_return"]
    )
    acceleration_5d = _forward_total_return(acceleration_daily, 5)
    label_cost = float(contract["boundaries"]["label_round_trip_cost_bps"]) / 10_000.0
    frame["cash_defense_advantage_10d"] = (
        frame["forward_bil_10d"] - baseline_10d - label_cost
    )
    frame["broad_equity_advantage_10d"] = (
        frame["forward_voo_10d"] - baseline_10d - label_cost
    )
    frame["nasdaq_core_advantage_10d"] = (
        frame["forward_qqq_10d"] - baseline_10d - label_cost
    )
    frame["nasdaq_acceleration_advantage_5d"] = (
        acceleration_5d - baseline_5d - label_cost
    )
    target_names = tuple(
        str(contract["actions"][action]["target"])
        for action in core.ACTION_KEYS
    )
    positions = np.arange(len(frame), dtype=int)
    sample_every = int(contract["training"]["sample_every_sessions"])
    anchor = int(contract["training"]["global_anchor_position"])
    frame["global_training_sample"] = ((positions - anchor) % sample_every) == 0
    return frame, tuple(feature_names), target_names


_ORIGINAL_SELECT_ADVANTAGE_EVENTS = core.select_advantage_events


def select_advantage_events(
    predictions: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    sample: str,
) -> pd.DataFrame:
    """Run the frozen selector and preserve stable schema and model provenance."""

    events = _ORIGINAL_SELECT_ADVANTAGE_EVENTS(
        predictions, contract, sample=sample
    )
    if events.empty:
        return pd.DataFrame(columns=list(_EVENT_COLUMNS))
    events = events.copy()
    events["rule_id"] = "ridge_action_advantage_v4_16"
    missing = [column for column in _EVENT_COLUMNS if column not in events.columns]
    if missing:
        raise AssertionError(f"action event ledger missing columns: {missing}")
    return events.loc[:, list(_EVENT_COLUMNS)].copy()


def run_action_advantage_model(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> core.AdvantageModelResult:
    """Run the core experiment with deterministic frame and event contracts."""

    original_frame = core.build_action_advantage_frame
    original_select = core.select_advantage_events
    core.build_action_advantage_frame = build_action_advantage_frame
    core.select_advantage_events = select_advantage_events
    try:
        return core.run_action_advantage_model(
            bars, proxy_baseline_daily, contract
        )
    finally:
        core.build_action_advantage_frame = original_frame
        core.select_advantage_events = original_select


run_action_advantage_policy = core.run_action_advantage_policy
