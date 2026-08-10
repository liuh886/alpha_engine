"""Data and path-utility labels for the governed v4.24 XGBoost study."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import _normalise_bars
from src.research.v4_16_action_advantage_runtime import build_action_advantage_frame
from src.research.v4_17_state_conditioned_action_advantage import _state_features
from src.research.v4_19_incremental_market_internals import (
    build_market_internal_feature_blocks,
)

STATE_ORDER = ("defense", "bridge", "core", "leveraged")
EDGE_ORDER = ("defense_vs_bridge", "bridge_vs_core", "core_vs_leveraged")
STATE_FEATURES = (
    "next_open_state_0",
    "next_open_state_1",
    "next_open_state_2",
    "next_open_weight_QQQI",
    "next_open_weight_QQQ",
    "next_open_weight_TQQQ",
)


def _normalised_weights(contract: Mapping[str, Any]) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for state in STATE_ORDER:
        raw = contract["states"]["weights"][state]
        weights = np.asarray(
            [float(raw["cash"]), float(raw["QQQ"]), float(raw["TQQQ"])],
            dtype=float,
        )
        if not np.isclose(weights.sum(), 1.0):
            raise AssertionError(f"{state} weights must sum to one")
        if (weights < 0.0).any():
            raise AssertionError(f"{state} weights must be non-negative")
        result[state] = weights
    return result


def _open_return(
    bars: Mapping[str, pd.DataFrame], symbol: str, index: pd.DatetimeIndex
) -> pd.Series:
    frame = _normalise_bars(bars[symbol], symbol)
    return frame["open"].shift(-1).div(frame["open"]).sub(1.0).reindex(index)


def _asset_returns(
    bars: Mapping[str, pd.DataFrame],
    index: pd.DatetimeIndex,
    *,
    cash_symbol: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cash": _open_return(bars, cash_symbol, index),
            "QQQ": _open_return(bars, "QQQ", index),
            "TQQQ": _open_return(bars, "TQQQ", index),
        },
        index=index,
    )


def _proxy_weights(row: pd.Series) -> np.ndarray:
    return np.asarray(
        [
            0.0,
            float(row["next_open_weight_QQQI"]) + float(row["next_open_weight_QQQ"]),
            float(row["next_open_weight_TQQQ"]),
        ],
        dtype=float,
    )


def _path_statistics(
    daily_returns: pd.Series,
    *,
    entry_turnover: float,
    exit_turnover: float,
    cost_rate: float,
    mae_penalty: float,
) -> dict[str, float]:
    values = pd.to_numeric(daily_returns, errors="coerce").to_numpy(dtype=float)
    if len(values) == 0 or not np.isfinite(values).all():
        return {"terminal_return": np.nan, "mae": np.nan, "path_utility": np.nan}
    net = values.copy()
    net[0] -= entry_turnover * cost_rate
    net[-1] -= exit_turnover * cost_rate
    cumulative = np.cumprod(1.0 + net) - 1.0
    terminal = float(cumulative[-1])
    mae = float(min(0.0, float(np.min(cumulative))))
    return {
        "terminal_return": terminal,
        "mae": mae,
        "path_utility": float(terminal + mae_penalty * mae),
    }


def _feature_schema(
    contract: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    market = tuple(str(value) for value in contract["features"]["market"])
    credit = tuple(str(value) for value in contract["features"]["credit_duration"])
    context = tuple(str(value) for value in contract["features"]["state_context"])
    features = market + credit + context
    if context != STATE_FEATURES:
        raise AssertionError("unexpected v4.2 context schema")
    if len(features) != int(contract["features"]["total_inputs"]):
        raise AssertionError("unexpected v4.24 input count")
    return market, credit, features


def _utility_ranks(values: Mapping[str, float]) -> dict[str, int]:
    ordered = sorted(
        STATE_ORDER,
        key=lambda state: (float(values[state]), STATE_ORDER.index(state)),
    )
    return {state: rank for rank, state in enumerate(ordered, start=1)}


def build_path_utility_frame(
    bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
    *,
    actual: bool,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Build one non-overlapping decision row with all four path utilities."""

    base, _, _ = build_action_advantage_frame(bars, baseline_daily, v416_contract)
    market, credit, feature_names = _feature_schema(contract)
    blocks = build_market_internal_feature_blocks(bars, base.index)
    credit_block = blocks.get("credit_duration_risk_appetite")
    if credit_block is None:
        raise ValueError("credit/duration block unavailable")
    missing_credit = sorted(set(credit) - set(credit_block.columns))
    if missing_credit:
        raise ValueError(f"credit/duration features missing: {missing_credit}")

    state_frame = _state_features(baseline_daily, base.index)
    frame = base.loc[:, list(market)].join(credit_block[list(credit)]).join(state_frame)
    frame["global_training_sample"] = base["global_training_sample"].astype(bool)
    returns = _asset_returns(
        bars,
        frame.index,
        cash_symbol="SGOV" if actual else "BIL",
    )
    baseline_returns = pd.to_numeric(baseline_daily["net_return"], errors="coerce").reindex(
        frame.index
    )
    state_weights = _normalised_weights(contract)
    sessions = int(contract["decision"]["holding_sessions"])
    cost_rate = float(contract["decision"]["transaction_cost_bps_per_turnover_unit"]) / 10_000.0
    mae_penalty = float(contract["decision"]["mae_penalty"])

    rows: list[dict[str, Any]] = []
    locations = np.flatnonzero(frame["global_training_sample"].to_numpy(dtype=bool))
    required_state = ["next_open_position_state", *STATE_FEATURES]
    for location in locations:
        start = location + 1
        stop = start + sessions
        if stop > len(frame):
            continue
        market_row = frame.iloc[location]
        end_state = state_frame.iloc[location + sessions]
        if market_row[required_state].isna().any() or end_state[required_state].isna().any():
            continue
        if market_row[list(feature_names)].isna().all():
            continue

        start_weights = _proxy_weights(market_row)
        end_weights = _proxy_weights(end_state)
        state_stats: dict[str, dict[str, float]] = {}
        for state in STATE_ORDER:
            weights = state_weights[state]
            daily = returns.iloc[start:stop].mul(weights, axis=1).sum(axis=1)
            state_stats[state] = _path_statistics(
                daily,
                entry_turnover=float(np.abs(weights - start_weights).sum()),
                exit_turnover=float(np.abs(end_weights - weights).sum()),
                cost_rate=cost_rate,
                mae_penalty=mae_penalty,
            )
        baseline_stats = _path_statistics(
            baseline_returns.iloc[start:stop],
            entry_turnover=0.0,
            exit_turnover=0.0,
            cost_rate=0.0,
            mae_penalty=mae_penalty,
        )
        all_values = [
            *(state_stats[state]["path_utility"] for state in STATE_ORDER),
            baseline_stats["path_utility"],
        ]
        if not np.isfinite(np.asarray(all_values, dtype=float)).all():
            continue
        ranks = _utility_ranks({state: state_stats[state]["path_utility"] for state in STATE_ORDER})
        row: dict[str, Any] = {
            "decision_date": pd.Timestamp(frame.index[location]),
            "execution_date": pd.Timestamp(frame.index[start]),
            "block_end_decision_date": pd.Timestamp(frame.index[location + sessions]),
            "sample": "actual_2024_plus" if actual else "proxy_oof",
            "baseline_terminal_return": baseline_stats["terminal_return"],
            "baseline_mae": baseline_stats["mae"],
            "baseline_path_utility": baseline_stats["path_utility"],
        }
        for feature in feature_names:
            row[feature] = market_row[feature]
        for state in STATE_ORDER:
            stats = state_stats[state]
            row[f"{state}_terminal_return"] = stats["terminal_return"]
            row[f"{state}_mae"] = stats["mae"]
            row[f"{state}_path_utility"] = stats["path_utility"]
            row[f"{state}_utility_rank"] = ranks[state]
            row[f"{state}_utility_advantage_vs_v4_2"] = (
                stats["path_utility"] - baseline_stats["path_utility"]
            )
        for edge_spec in contract["states"]["edges"]:
            edge = str(edge_spec["edge"])
            lower = str(edge_spec["lower"])
            higher = str(edge_spec["higher"])
            row[f"label_{edge}"] = int(
                state_stats[higher]["path_utility"] > state_stats[lower]["path_utility"]
            )
            row[f"utility_delta_{edge}"] = (
                state_stats[higher]["path_utility"] - state_stats[lower]["path_utility"]
            )
        rows.append(row)

    output = pd.DataFrame(rows).sort_values("decision_date").reset_index(drop=True)
    if output.empty:
        raise ValueError("no complete v4.24 path-utility decision rows")
    if output["decision_date"].duplicated().any():
        raise AssertionError("decision dates must be unique")
    expected_edges = tuple(str(item["edge"]) for item in contract["states"]["edges"])
    if expected_edges != EDGE_ORDER:
        raise AssertionError("unexpected adjacent-edge order")
    return output, feature_names
