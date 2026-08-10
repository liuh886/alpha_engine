"""Allocation-only challenger for the frozen v4.1 VXN state machine.

The v4.1 decision trace is preserved exactly. Only state 1 changes from 100%
QQQ to a neutral 50% QQQI / 50% QQQ bridge. State 0 remains 100% QQQI and
state 2 remains 25% QQQ / 75% TQQQ.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.vix_rotation_experiment import STATE_TO_LABEL, VixRotationConfig
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
    run_vxn_leverage_overlay_comparison,
)

ASSETS = ("QQQI", "QQQ", "TQQQ")


def _state_weights(contract: Mapping[str, Any]) -> dict[int, dict[str, float]]:
    portfolio = contract["portfolio"]
    raw = {
        0: portfolio["state_0"],
        1: portfolio["state_1_bridge"],
        2: portfolio["state_2"],
    }
    output: dict[int, dict[str, float]] = {}
    for state, weights in raw.items():
        normalized = {asset: float(weights.get(asset, 0.0)) for asset in ASSETS}
        if any(value < 0.0 for value in normalized.values()):
            raise ValueError(f"state {state} contains a negative weight")
        if not np.isclose(sum(normalized.values()), 1.0):
            raise ValueError(f"state {state} weights must sum to one")
        output[state] = normalized
    return output


def bridge_weights_for_states(states: pd.Series, contract: Mapping[str, Any]) -> pd.DataFrame:
    """Map executed state labels to the frozen bridge allocation."""

    mapping = _state_weights(contract)
    unknown = sorted(
        set(pd.to_numeric(states, errors="coerce").dropna().astype(int)) - set(mapping)
    )
    if unknown:
        raise ValueError(f"unknown position states: {unknown}")
    weights = pd.DataFrame(0.0, index=states.index, columns=list(ASSETS))
    for state, state_weights in mapping.items():
        mask = states.eq(state)
        for asset, value in state_weights.items():
            weights.loc[mask, asset] = value
    return weights


def run_bridge_state_backtest(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
    decisions: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    strategy_key: str = "rotation_vxn_bridge_v4_2_50_50",
    display_name: str = "v4.1 states with 50% QQQI / 50% QQQ bridge",
) -> StrategyResult:
    """Execute the unchanged v4.1 decisions with bridge-state weights."""

    daily = prepared.join(decisions)
    daily["position_state"] = daily["decision_state"].shift(1).fillna(0).astype(int)
    daily["position_label"] = daily["position_state"].map(STATE_TO_LABEL)
    daily["executed_reason"] = daily["decision_reason"].shift(1).fillna("initial_entry")

    weights = bridge_weights_for_states(daily["position_state"], contract)
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]
    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"] for asset in ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if config.charge_initial_entry and not turnover.empty:
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    else:
        turnover.iloc[0] = 0.0
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * config.transaction_cost_bps_per_turnover_unit / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(
        daily["net_return"], annual_risk_free_rate=config.annual_risk_free_rate
    )
    switches = daily["position_state"].ne(daily["position_state"].shift()).sum() - 1
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(switches, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "pct_time_qqqi": float(daily["position_state"].eq(0).mean()),
            "pct_time_qqq_bridge": float(daily["position_state"].eq(1).mean()),
            "pct_time_partial_tqqq": float(daily["position_state"].eq(2).mean()),
            "average_qqqi_weight": float(daily["weight_QQQI"].mean()),
            "average_qqq_weight": float(daily["weight_QQQ"].mean()),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
        }
    )
    trade_mask = daily["position_state"].ne(daily["position_state"].shift())
    trade_columns = [
        "executed_reason",
        "position_state",
        "position_label",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "turnover_units",
        "transaction_cost",
        "vix_close",
        "vix_regime",
        "vxn_close",
        "vxn_regime",
    ]
    trades = daily.loc[trade_mask, trade_columns].reset_index(names="date")
    return StrategyResult(display_name, daily, trades, metrics)


def _capture_state(result: StrategyResult, state: int) -> dict[str, float | int]:
    sample = result.daily.loc[result.daily["position_state"].eq(state), "net_return"].dropna()
    if sample.empty:
        return {
            "sessions": 0,
            "cumulative_net_return": 0.0,
            "mean_daily_net_return": 0.0,
            "positive_session_rate": 0.0,
            "worst_daily_net_return": 0.0,
        }
    return {
        "sessions": int(len(sample)),
        "cumulative_net_return": float((1.0 + sample).prod() - 1.0),
        "mean_daily_net_return": float(sample.mean()),
        "positive_session_rate": float(sample.gt(0.0).mean()),
        "worst_daily_net_return": float(sample.min()),
    }


def _transition_costs(result: StrategyResult) -> list[dict[str, Any]]:
    daily = result.daily
    previous = daily["position_state"].shift(1)
    mask = daily["position_state"].ne(previous) & previous.notna()
    rows: list[dict[str, Any]] = []
    for date, row in daily.loc[mask].iterrows():
        old_state = int(previous.loc[date])
        new_state = int(row["position_state"])
        rows.append(
            {
                "date": date,
                "transition": f"{old_state}->{new_state}",
                "turnover_units": float(row["turnover_units"]),
                "transaction_cost": float(row["transaction_cost"]),
            }
        )
    return rows


def _bridge_entry_event_study(
    prepared: pd.DataFrame,
    baseline: StrategyResult,
    horizons: Sequence[int],
) -> list[dict[str, Any]]:
    """Compare 50/50 bridge with 100% QQQ after each executed 0->1 transition."""

    position = baseline.daily["position_state"]
    previous = position.shift(1)
    entries = position.eq(1) & previous.eq(0)
    rows: list[dict[str, Any]] = []
    for execution_date in position.index[entries]:
        location = prepared.index.get_loc(execution_date)
        row: dict[str, Any] = {"execution_date": execution_date}
        for horizon in horizons:
            window = prepared.iloc[location : location + int(horizon)]
            qqq = window["QQQ_next_open_return"].dropna()
            qqqi = window["QQQI_next_open_return"].dropna()
            if len(qqq) != int(horizon) or len(qqqi) != int(horizon):
                row[f"bridge_minus_qqq_{horizon}d"] = np.nan
                continue
            baseline_return = float((1.0 + qqq).prod() - 1.0)
            bridge_daily = 0.5 * qqqi + 0.5 * qqq
            bridge_return = float((1.0 + bridge_daily).prod() - 1.0)
            row[f"bridge_minus_qqq_{horizon}d"] = bridge_return - baseline_return
        rows.append(row)
    return rows


def run_bridge_allocation_comparison(
    bars: Mapping[str, pd.DataFrame], contract: Mapping[str, Any]
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame, dict[str, Any]]:
    """Compare frozen v4.1 with the one predeclared bridge allocation."""

    _, base_results, prepared, base_diagnostics = run_vxn_leverage_overlay_comparison(
        bars, contract
    )
    baseline = base_results["rotation_vxn_leverage_v4_1_75"]
    decisions = generate_vxn_leverage_veto_states(prepared, config=_config(contract))
    bridge = run_bridge_state_backtest(
        prepared,
        _config(contract),
        decisions,
        contract,
    )
    buy_hold = base_results["buy_hold_QQQ"]
    results = {
        "buy_hold_QQQ": buy_hold,
        "rotation_vxn_leverage_v4_1_75": baseline,
        "rotation_vxn_bridge_v4_2_50_50": bridge,
    }
    metrics = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    same_trace = baseline.daily["position_state"].equals(bridge.daily["position_state"])
    if (
        contract["validation"].get("require_same_decision_state_every_session", False)
        and not same_trace
    ):
        raise AssertionError("bridge allocation changed the v4.1 state trace")
    horizons = [int(value) for value in contract["validation"]["event_horizons"]]
    diagnostics = {
        "post_result_hypothesis": True,
        "allocation_only_change": True,
        "same_decision_state_every_session": same_trace,
        "same_partial_leverage_sessions": bool(
            baseline.daily["position_state"].eq(2).equals(bridge.daily["position_state"].eq(2))
        ),
        "state_1_capture": {
            "baseline_100_percent_qqq": _capture_state(baseline, 1),
            "bridge_50_qqqi_50_qqq": _capture_state(bridge, 1),
        },
        "state_2_capture": {
            "baseline": _capture_state(baseline, 2),
            "bridge": _capture_state(bridge, 2),
        },
        "transition_costs": {
            "baseline": _transition_costs(baseline),
            "bridge": _transition_costs(bridge),
        },
        "bridge_entry_event_study": _bridge_entry_event_study(prepared, baseline, horizons),
        "inherited_v4_1_diagnostics": base_diagnostics,
    }
    return metrics.sort_index(), results, prepared, diagnostics


def _config(contract: Mapping[str, Any]) -> VixRotationConfig:
    from src.research.vix_rotation_experiment import config_from_contract

    return config_from_contract(contract)
