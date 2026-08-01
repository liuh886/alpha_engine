"""Matched VIX v2 versus higher-TQQQ-weight recovery experiment."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vix_rotation_experiment import config_from_contract
from src.research.vix_rotation_runtime import run_vix_runtime_comparison, state_reachability


def validate_weight_only_change(
    baseline_contract: Mapping[str, Any],
    challenger_contract: Mapping[str, Any],
) -> tuple[float, float]:
    """Fail closed unless TQQQ weight is the only executable contract change."""

    frozen_sections = ("boundaries", "data", "price_logic", "vix_logic", "validation")
    for section in frozen_sections:
        baseline_section = deepcopy(baseline_contract.get(section, {}))
        challenger_section = deepcopy(challenger_contract.get(section, {}))
        if section == "validation":
            # Challenger-only declarations do not alter execution or signal generation.
            for key in (
                "primary_baseline_experiment",
                "primary_metrics",
                "require_identical_state_trace_to_baseline",
            ):
                challenger_section.pop(key, None)
        if baseline_section != challenger_section:
            raise ValueError(f"challenger changed frozen contract section: {section}")

    baseline_portfolio = deepcopy(baseline_contract.get("portfolio", {}))
    challenger_portfolio = deepcopy(challenger_contract.get("portfolio", {}))
    try:
        baseline_weight = float(baseline_portfolio.pop("leveraged_tqqq_weight"))
        challenger_weight = float(challenger_portfolio.pop("leveraged_tqqq_weight"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("both contracts must define leveraged_tqqq_weight") from exc
    if baseline_portfolio != challenger_portfolio:
        raise ValueError("challenger changed portfolio fields other than TQQQ weight")
    if not 0.0 <= baseline_weight < challenger_weight <= 1.0:
        raise ValueError("challenger TQQQ weight must be higher and within [0, 1]")

    declared = challenger_contract.get("change_control", {})
    if declared.get("allowed_change") != "portfolio.leveraged_tqqq_weight":
        raise ValueError("challenger must explicitly declare the sole allowed change")
    if not bool(declared.get("all_signal_rules_frozen")):
        raise ValueError("challenger must freeze all signal rules")
    return baseline_weight, challenger_weight


def _rename_metrics(result: StrategyResult, strategy: str) -> dict[str, Any]:
    metrics = dict(result.metrics)
    metrics["strategy"] = strategy
    return metrics


def _state_capture(result: StrategyResult) -> dict[str, float | int]:
    daily = result.daily
    mask = daily["position_state"].eq(2)
    returns = daily.loc[mask, "net_return"].dropna()
    if returns.empty:
        return {
            "sessions": 0,
            "cumulative_net_return": 0.0,
            "mean_daily_net_return": 0.0,
            "positive_session_rate": 0.0,
            "worst_daily_net_return": 0.0,
        }
    return {
        "sessions": int(len(returns)),
        "cumulative_net_return": float((1.0 + returns).prod() - 1.0),
        "mean_daily_net_return": float(returns.mean()),
        "positive_session_rate": float(returns.gt(0).mean()),
        "worst_daily_net_return": float(returns.min()),
    }


def run_aggressive_tqqq_comparison(
    bars: Mapping[str, pd.DataFrame],
    baseline_contract: Mapping[str, Any],
    challenger_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame, dict[str, Any]]:
    """Run 50% versus 75% TQQQ with identical signals, dates and execution."""

    baseline_weight, challenger_weight = validate_weight_only_change(
        baseline_contract, challenger_contract
    )
    baseline_config = config_from_contract(baseline_contract)
    challenger_config = config_from_contract(challenger_contract)

    _, baseline_results, baseline_prepared = run_vix_runtime_comparison(bars, baseline_config)
    _, challenger_results, challenger_prepared = run_vix_runtime_comparison(
        bars, challenger_config
    )
    pd.testing.assert_index_equal(baseline_prepared.index, challenger_prepared.index)

    baseline = baseline_results["rotation_vix_v2"]
    challenger = challenger_results["rotation_vix_v2"]
    if not baseline.daily["decision_state"].equals(challenger.daily["decision_state"]):
        raise ValueError("challenger changed the close decision-state trace")
    if not baseline.daily["position_state"].equals(challenger.daily["position_state"]):
        raise ValueError("challenger changed the executed position-state trace")

    results = {
        "buy_hold_QQQ": baseline_results["buy_hold_QQQ"],
        "rotation_vix_v2_50": baseline,
        "rotation_vix_v3_75": challenger,
        "rotation_price_repair_v3_75": challenger_results["rotation_price_repair_v2"],
    }
    metrics = pd.DataFrame(
        [
            _rename_metrics(results["buy_hold_QQQ"], "buy_hold_QQQ"),
            _rename_metrics(results["rotation_vix_v2_50"], "rotation_vix_v2_50"),
            _rename_metrics(results["rotation_vix_v3_75"], "rotation_vix_v3_75"),
            _rename_metrics(
                results["rotation_price_repair_v3_75"],
                "rotation_price_repair_v3_75",
            ),
        ]
    ).set_index("strategy")

    base_capture = _state_capture(baseline)
    challenger_capture = _state_capture(challenger)
    diagnostics = {
        "baseline_tqqq_weight": baseline_weight,
        "challenger_tqqq_weight": challenger_weight,
        "identical_decision_state_trace": True,
        "identical_position_state_trace": True,
        "state_reachability": {
            "baseline": state_reachability(baseline),
            "challenger": state_reachability(challenger),
        },
        "partial_leverage_capture": {
            "baseline": base_capture,
            "challenger": challenger_capture,
            "incremental_cumulative_return": float(
                challenger_capture["cumulative_net_return"]
                - base_capture["cumulative_net_return"]
            ),
        },
    }
    return metrics.sort_index(), results, challenger_prepared, diagnostics
