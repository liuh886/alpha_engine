"""Single-rule test of two-close VXN persistence for existing leverage exits."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vix_rotation_experiment import VixRotationConfig
from src.research.vxn_attack_layer_long_history import (
    _run_attack_backtest,
    leverage_episodes,
    period_metrics,
    prepare_attack_layer_data,
    rolling_metrics,
)
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
)


def generate_vxn_exit_persistence_states(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
    *,
    persistence_closes: int = 2,
) -> pd.DataFrame:
    """Require persistent VXN stress only for exiting existing leverage."""

    if persistence_closes != 2:
        raise ValueError("this frozen experiment permits exactly two closes")
    persistent_vxn_stress = (
        prepared["vxn_stress"]
        .astype(bool)
        .rolling(persistence_closes, min_periods=persistence_closes)
        .sum()
        .eq(persistence_closes)
    )
    state = 0
    states: list[int] = []
    reasons: list[str] = []
    for location, row in enumerate(prepared.itertuples()):
        next_state = state
        reason = "hold"
        severe_defense = bool(row.long_break) or (
            bool(row.vix_stress) and bool(row.stress_price_failure)
        )
        if severe_defense:
            next_state = 0
            reason = "defensive_price_or_vix_stress"
        elif state == 0:
            if bool(row.shock_memory) and bool(row.early_repair) and bool(row.vix_easing):
                next_state = 1
                reason = "enter_qqq_early_repair_vix_easing"
        elif state == 1:
            leverage_ready = (
                bool(row.shock_memory)
                and bool(row.medium_repair)
                and bool(row.secondary_confirmation)
                and bool(row.vix_normalized)
                and not bool(row.vxn_stress)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_vix_normalized_vxn_not_stressed"
        else:
            if bool(row.vix_stress) or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_or_ma20"
            elif bool(persistent_vxn_stress.iloc[location]):
                next_state = 1
                reason = "exit_partial_tqqq_vxn_stress_two_closes"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons},
        index=prepared.index,
    )


def position_difference_table(
    baseline: StrategyResult, challenger: StrategyResult
) -> pd.DataFrame:
    """Report every economic session changed by the persistence rule."""

    joined = pd.DataFrame(
        {
            "baseline_state": baseline.daily["position_state"],
            "challenger_state": challenger.daily["position_state"],
            "baseline_return": baseline.daily["net_return"],
            "challenger_return": challenger.daily["net_return"],
        }
    )
    changed = joined[joined["baseline_state"].ne(joined["challenger_state"])].copy()
    changed["challenger_minus_baseline"] = (
        changed["challenger_return"] - changed["baseline_return"]
    )
    return changed.reset_index(names="date")


def run_vxn_exit_persistence_comparison(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
]:
    """Compare immediate v4.1 exits with the single two-close challenger."""

    base_contract_path = contract.get("base_contract")
    if not base_contract_path:
        raise ValueError("contract must declare base_contract")
    base_contract = contract["resolved_base_contract"]
    prepared, config = prepare_attack_layer_data(bars, base_contract)
    baseline_decisions = generate_vxn_leverage_veto_states(prepared, config)
    challenger_decisions = generate_vxn_exit_persistence_states(prepared, config)

    baseline = _run_attack_backtest(
        prepared,
        baseline_decisions,
        config,
        strategy_key="attack_vxn_v4_1_75",
        display_name="VXN immediate-exit v4.1",
    )
    challenger = _run_attack_backtest(
        prepared,
        challenger_decisions,
        config,
        strategy_key="attack_vxn_exit_persistence_v4_2_75",
        display_name="VXN two-close exit persistence v4.2",
    )
    results = {
        "attack_vxn_v4_1_75": baseline,
        "attack_vxn_exit_persistence_v4_2_75": challenger,
    }
    metrics = pd.DataFrame(
        [dict(result.metrics) for result in results.values()]
    ).set_index("strategy")

    validation = contract["validation"]
    periods = period_metrics(results, validation["chronological_periods"])
    regimes = period_metrics(results, validation["regime_windows"])
    rolling = rolling_metrics(results, validation["rolling_windows_sessions"])
    episodes = pd.concat(
        [leverage_episodes(result) for result in results.values()],
        ignore_index=True,
    )
    differences = position_difference_table(baseline, challenger)

    cost_rows: list[dict[str, Any]] = []
    for cost_bps in validation["cost_sensitivity_bps"]:
        cost_config = replace(
            config, transaction_cost_bps_per_turnover_unit=float(cost_bps)
        )
        for key, decisions in (
            ("attack_vxn_v4_1_75", baseline_decisions),
            (
                "attack_vxn_exit_persistence_v4_2_75",
                challenger_decisions,
            ),
        ):
            result = _run_attack_backtest(
                prepared,
                decisions,
                cost_config,
                strategy_key=key,
                display_name=key,
            )
            cost_rows.append(
                {
                    "cost_bps_per_turnover_unit": float(cost_bps),
                    **dict(result.metrics),
                }
            )
    cost_sensitivity = pd.DataFrame(cost_rows)

    diagnostics = {
        "post_result_hypothesis": True,
        "only_allowed_change": "vxn_existing_leverage_exit_persistence_closes",
        "baseline_persistence_closes": 1,
        "challenger_persistence_closes": 2,
        "immediate_entry_veto_frozen": True,
        "immediate_vix_exit_frozen": True,
        "immediate_price_exit_frozen": True,
        "changed_economic_sessions": int(len(differences)),
        "changed_session_return_delta_sum": float(
            differences["challenger_minus_baseline"].sum()
        ),
        "no_parameter_grid": True,
    }
    tables = {
        "chronological_periods": periods,
        "regime_windows": regimes,
        "rolling_metrics": rolling,
        "leverage_episodes": episodes,
        "position_differences": differences,
        "cost_sensitivity": cost_sensitivity,
        "baseline_decisions": baseline_decisions,
        "challenger_decisions": challenger_decisions,
    }
    return metrics.sort_index(), results, prepared, diagnostics, tables
