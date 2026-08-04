"""Exact-calendar runtime for the v4.12 cross-asset transfer experiment.

The research model and frozen strategy definitions live in
``v4_2_cross_asset_sgov_tqqq_transfer``.  This module performs target execution
on an explicit intersection of the SGOV/TQQQ and v4.2 trading calendars so every
reported comparator uses exactly the same economic dates within its scope.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_cross_asset_sgov_tqqq_transfer import (
    BASELINE_KEY,
    ClusterTransferModel,
    _donor_gate,
    _strategy_gate,
    _target_weight_schedules,
    build_donor_event_panel,
    build_target_events,
    fit_cluster_transfer_model,
    target_event_attribution,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS as V4_2_ASSETS,
    run_bridge_allocation_comparison,
)


def _target_result_on_index(
    frame: pd.DataFrame,
    tqqq_weight: pd.Series,
    index: pd.DatetimeIndex,
    contract: Mapping[str, Any],
    strategy: str,
) -> StrategyResult:
    daily = frame.reindex(index)[
        ["cash_next_open_return", "leveraged_next_open_return"]
    ].copy()
    daily["weight_TQQQ"] = tqqq_weight.reindex(index).astype(float)
    daily["weight_SGOV"] = 1.0 - daily["weight_TQQQ"]
    if daily[
        [
            "cash_next_open_return",
            "leveraged_next_open_return",
            "weight_TQQQ",
        ]
    ].isna().any().any():
        raise AssertionError(f"{strategy} target calendar contains missing values")
    weights = daily[["weight_SGOV", "weight_TQQQ"]]
    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("target SGOV/TQQQ weights must sum to one")
    if (weights < -1e-12).any().any() or (
        weights > 1.0 + 1e-12
    ).any().any():
        raise AssertionError("target weights must stay in [0, 1]")

    daily["gross_return"] = (
        daily["weight_SGOV"] * daily["cash_next_open_return"]
        + daily["weight_TQQQ"] * daily["leveraged_next_open_return"]
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(
        contract["boundaries"]["transaction_cost_bps_per_turnover_unit"]
    )
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    changed = weights.ne(weights.shift()).any(axis=1)

    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(
            contract["boundaries"]["annual_risk_free_rate"]
        ),
    )
    metrics.update(
        {
            "strategy": strategy,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "switch_count": int(max(int(changed.sum()) - 1, 0)),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
            "pct_time_sgov": float(daily["weight_TQQQ"].eq(0.0).mean()),
            "pct_time_full_tqqq": float(
                daily["weight_TQQQ"].eq(1.0).mean()
            ),
        }
    )
    trades = daily.loc[
        changed,
        [
            "weight_SGOV",
            "weight_TQQQ",
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(strategy, daily, trades, metrics)


def _v4_2_result_on_index(
    result: StrategyResult,
    index: pd.DatetimeIndex,
    contract: Mapping[str, Any],
    strategy: str,
) -> StrategyResult:
    daily = result.daily.reindex(index).copy()
    required = [
        *[f"weight_{asset}" for asset in V4_2_ASSETS],
        *[f"{asset}_next_open_return" for asset in V4_2_ASSETS],
    ]
    if daily[required].isna().any().any():
        raise AssertionError(f"{strategy} v4.2 calendar contains missing values")
    weights = daily[[f"weight_{asset}" for asset in V4_2_ASSETS]].copy()
    daily["gross_return"] = sum(
        weights[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in V4_2_ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(
        contract["boundaries"]["transaction_cost_bps_per_turnover_unit"]
    )
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    changed = weights.ne(weights.shift()).any(axis=1)

    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(
            contract["boundaries"]["annual_risk_free_rate"]
        ),
    )
    metrics.update(
        {
            "strategy": strategy,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "switch_count": int(max(int(changed.sum()) - 1, 0)),
        }
    )
    trades = daily.loc[
        changed,
        [
            *[f"weight_{asset}" for asset in V4_2_ASSETS],
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(strategy, daily, trades, metrics)


def _comparison_index(
    target_frame: pd.DataFrame,
    baseline: StrategyResult,
    common_end: pd.Timestamp,
) -> pd.DatetimeIndex:
    target_available = target_frame.dropna(
        subset=["cash_next_open_return", "leveraged_next_open_return"]
    ).index
    index = target_available.intersection(baseline.daily.index).sort_values()
    index = index[index <= common_end]
    if len(index) < 40:
        raise ValueError("exact target comparison calendar is too short")
    return pd.DatetimeIndex(index)


def run_cross_asset_sgov_tqqq_transfer(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[
    ClusterTransferModel,
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, dict[str, StrategyResult]],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run donor learning and exact-calendar actual/proxy target comparisons."""

    required = {str(value) for value in contract["data"]["required_symbols"]}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    donor_events, donor_frames = build_donor_event_panel(bars, contract)
    model = fit_cluster_transfer_model(donor_events, contract)
    target_events, target_frame = build_target_events(
        bars, donor_frames, model, contract
    )
    schedules = _target_weight_schedules(target_frame, target_events, contract)

    _, actual_base_results, _, _ = run_bridge_allocation_comparison(
        bars, bridge_contract
    )
    _, proxy_base_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    actual_base_full = actual_base_results[BASELINE_KEY]
    proxy_base_full = proxy_base_results[BASELINE_KEY]

    target_end = target_frame.dropna(
        subset=["cash_next_open_return", "leveraged_next_open_return"]
    ).index.max()
    common_end = min(
        target_end,
        actual_base_full.daily.index.max(),
        proxy_base_full.daily.index.max(),
    )
    actual_index = _comparison_index(
        target_frame, actual_base_full, common_end
    )
    proxy_index = _comparison_index(target_frame, proxy_base_full, common_end)

    actual_baseline = _v4_2_result_on_index(
        actual_base_full, actual_index, contract, "current_v4_2"
    )
    proxy_baseline = _v4_2_result_on_index(
        proxy_base_full, proxy_index, contract, "qqq_proxy_v4_2"
    )
    results_by_scope: dict[str, dict[str, StrategyResult]] = {
        "actual": {"current_v4_2": actual_baseline},
        "qqq_proxy": {"qqq_proxy_v4_2": proxy_baseline},
    }
    for strategy, weights in schedules.items():
        results_by_scope["actual"][strategy] = _target_result_on_index(
            target_frame, weights, actual_index, contract, strategy
        )
        results_by_scope["qqq_proxy"][strategy] = _target_result_on_index(
            target_frame, weights, proxy_index, contract, strategy
        )

    for scope, results in results_by_scope.items():
        indices = [result.daily.index for result in results.values()]
        if not all(indices[0].equals(index) for index in indices[1:]):
            raise AssertionError(f"{scope} comparator indices diverged")

    headlines = {
        scope: pd.DataFrame(
            [dict(result.metrics) for result in results.values()]
        ).set_index("strategy")
        for scope, results in results_by_scope.items()
    }
    event_attribution = {
        "actual": target_event_attribution(
            target_events,
            results_by_scope["actual"]["joint_structural_event"],
            actual_baseline,
        ),
        "qqq_proxy": target_event_attribution(
            target_events,
            results_by_scope["qqq_proxy"]["joint_structural_event"],
            proxy_baseline,
        ),
    }
    donor_gate = _donor_gate(model, contract)
    strategy_gate = _strategy_gate(
        results_by_scope["actual"],
        results_by_scope["qqq_proxy"],
        event_attribution["actual"],
        contract,
    )
    shadow = bool(donor_gate["passed"] and strategy_gate["passed"])
    if not donor_gate["passed"]:
        decision = "cross_asset_donor_signal_not_stable"
    elif not strategy_gate["passed"]:
        decision = "sgov_tqqq_transfer_does_not_stably_beat_v4_2"
    else:
        decision = "cross_asset_sgov_tqqq_shadow_supported"

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "target_excluded_from_training": True,
        "training_assets": model.aggregate_metrics["training_assets"],
        "donor_gate": donor_gate,
        "strategy_gate": strategy_gate,
        "actual_sample_start": actual_index.min(),
        "actual_observations": int(len(actual_index)),
        "proxy_sample_start": proxy_index.min(),
        "proxy_observations": int(len(proxy_index)),
        "sample_end": common_end,
        "target_event_count": int(len(target_events)),
        "target_bucket_counts": target_events[
            "probability_bucket"
        ].value_counts().to_dict(),
        "tail_risk": {
            scope: {
                key: tail_risk_metrics(result)
                for key, result in results.items()
            }
            for scope, results in results_by_scope.items()
        },
        "decision": decision,
        "shadow_candidate_authorized": shadow,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return (
        model,
        target_events,
        headlines,
        results_by_scope,
        event_attribution,
        diagnostics,
    )
