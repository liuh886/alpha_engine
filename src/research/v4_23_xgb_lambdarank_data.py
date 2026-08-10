"""Data and label construction for the governed v4.23 LambdaRank study."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import _normalise_bars
from src.research.v4_16_action_advantage_runtime import build_action_advantage_frame
from src.research.v4_17_state_conditioned_action_advantage import _state_features
from src.research.v4_19_incremental_market_internals import build_market_internal_feature_blocks

ACTION_ORDER = ("defense", "balanced", "core", "leveraged", "accelerated")
ACTION_WEIGHTS = {
    "defense": (1.00, 0.00, 0.00),
    "balanced": (0.50, 0.50, 0.00),
    "core": (0.00, 1.00, 0.00),
    "leveraged": (0.00, 0.25, 0.75),
    "accelerated": (0.00, 0.00, 1.00),
}
STATE_FEATURES = (
    "next_open_state_0",
    "next_open_state_1",
    "next_open_state_2",
    "next_open_weight_QQQI",
    "next_open_weight_QQQ",
    "next_open_weight_TQQQ",
)
ACTION_FEATURES = (
    "candidate_cash_weight",
    "candidate_qqq_weight",
    "candidate_tqqq_weight",
    "candidate_l1_from_v4_2_proxy",
)


def open_return(
    bars: Mapping[str, pd.DataFrame], symbol: str, index: pd.DatetimeIndex
) -> pd.Series:
    frame = _normalise_bars(bars[symbol], symbol)
    return frame["open"].shift(-1).div(frame["open"]).sub(1.0).reindex(index)


def action_asset_returns(
    bars: Mapping[str, pd.DataFrame],
    index: pd.DatetimeIndex,
    *,
    cash_symbol: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cash_return": open_return(bars, cash_symbol, index),
            "qqq_return": open_return(bars, "QQQ", index),
            "tqqq_return": open_return(bars, "TQQQ", index),
        },
        index=index,
    )


def forward_product(series: pd.Series, location: int, sessions: int) -> float:
    window = pd.to_numeric(series.iloc[location + 1 : location + 1 + sessions], errors="coerce")
    if len(window) != sessions or window.isna().any():
        return np.nan
    return float((1.0 + window).prod() - 1.0)


def baseline_proxy_weights(row: pd.Series) -> np.ndarray:
    return np.asarray(
        [
            0.0,
            float(row["next_open_weight_QQQI"]) + float(row["next_open_weight_QQQ"]),
            float(row["next_open_weight_TQQQ"]),
        ]
    )


def action_rank_labels(action_returns: pd.Series) -> pd.Series:
    ordered = action_returns.reindex(ACTION_ORDER)
    if ordered.isna().any():
        return pd.Series(np.nan, index=ACTION_ORDER, dtype=float)
    order = sorted(
        ACTION_ORDER,
        key=lambda action: (float(ordered[action]), ACTION_ORDER.index(action)),
    )
    labels = pd.Series(index=ACTION_ORDER, dtype=float)
    for relevance, action in enumerate(order):
        labels[action] = float(relevance)
    return labels


def _comparator_action(row: pd.Series) -> str:
    state = int(round(float(row["next_open_position_state"])))
    return "leveraged" if state == 2 else "core"


def _feature_schema(
    contract: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    market = tuple(str(value) for value in contract["features"]["market"])
    credit = tuple(str(value) for value in contract["features"]["credit_duration"])
    model = market + credit + STATE_FEATURES + ACTION_FEATURES
    if len(model) != int(contract["features"]["total_inputs"]):
        raise AssertionError("unexpected XGBoost input count")
    return market, credit, model


def build_group_frame(
    bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
    *,
    actual: bool,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    base, _, _ = build_action_advantage_frame(bars, baseline_daily, v416_contract)
    market, credit, feature_names = _feature_schema(contract)
    blocks = build_market_internal_feature_blocks(bars, base.index)
    credit_block = blocks.get("credit_duration_risk_appetite")
    if credit_block is None:
        raise ValueError("credit/duration block unavailable")
    missing = sorted(set(credit) - set(credit_block.columns))
    if missing:
        raise ValueError(f"credit/duration features missing: {missing}")
    states = _state_features(baseline_daily, base.index)
    frame = base.loc[:, list(market)].join(credit_block[list(credit)]).join(states)
    frame["global_training_sample"] = base["global_training_sample"].astype(bool)
    state_frame = _state_features(baseline_daily, frame.index)
    returns = action_asset_returns(bars, frame.index, cash_symbol="SGOV" if actual else "BIL")
    baseline_returns = pd.to_numeric(baseline_daily["net_return"], errors="coerce").reindex(
        frame.index
    )
    sessions = int(contract["decision"]["holding_sessions"])
    cost_rate = float(contract["decision"]["transaction_cost_bps_per_turnover_unit"]) / 10_000.0
    rows: list[dict[str, Any]] = []
    locations = np.flatnonzero(frame["global_training_sample"].to_numpy(dtype=bool))
    for location in locations:
        if location + 1 + sessions > len(frame):
            continue
        market_row = frame.iloc[location]
        end_state = state_frame.iloc[location + sessions]
        required_state = ["next_open_position_state", *STATE_FEATURES]
        if market_row[required_state].isna().any() or end_state[required_state].isna().any():
            continue
        start_weights = baseline_proxy_weights(market_row)
        end_weights = baseline_proxy_weights(end_state)
        baseline_block = forward_product(baseline_returns, location, sessions)
        action_returns: dict[str, float] = {}
        for action, raw_weights in ACTION_WEIGHTS.items():
            weights = np.asarray(raw_weights, dtype=float)
            daily = (
                weights[0] * returns["cash_return"]
                + weights[1] * returns["qqq_return"]
                + weights[2] * returns["tqqq_return"]
            )
            gross = forward_product(daily, location, sessions)
            turnover = float(np.abs(weights - start_weights).sum())
            turnover += float(np.abs(end_weights - weights).sum())
            action_returns[action] = gross - turnover * cost_rate if np.isfinite(gross) else np.nan
        labels = action_rank_labels(pd.Series(action_returns))
        if labels.isna().any() or not np.isfinite(baseline_block):
            continue
        for action, raw_weights in ACTION_WEIGHTS.items():
            weights = np.asarray(raw_weights, dtype=float)
            row: dict[str, Any] = {
                "decision_date": pd.Timestamp(frame.index[location]),
                "execution_date": pd.Timestamp(frame.index[location + 1]),
                "block_end_date": pd.Timestamp(frame.index[location + sessions]),
                "action": action,
                "action_order": ACTION_ORDER.index(action),
                "realized_action_return": float(action_returns[action]),
                "relevance": int(labels[action]),
                "baseline_block_return_10d": baseline_block,
                "realized_advantage_vs_v4_2": float(action_returns[action] - baseline_block),
                "v4_2_comparator_action": _comparator_action(market_row),
                "candidate_cash_weight": weights[0],
                "candidate_qqq_weight": weights[1],
                "candidate_tqqq_weight": weights[2],
                "candidate_l1_from_v4_2_proxy": float(np.abs(weights - start_weights).sum()),
                "sample": "actual_2024_plus" if actual else "proxy_oof",
            }
            for feature in market + credit + STATE_FEATURES:
                row[feature] = market_row[feature]
            rows.append(row)
    output = (
        pd.DataFrame(rows).sort_values(["decision_date", "action_order"]).reset_index(drop=True)
    )
    if output.empty:
        raise ValueError("no complete ten-session action-ranking groups")
    if not output.groupby("decision_date").size().eq(len(ACTION_ORDER)).all():
        raise AssertionError("every ranking group must contain five actions")
    return output, feature_names
