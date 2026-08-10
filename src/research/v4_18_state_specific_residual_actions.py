"""State-specific residual action models for v4.18.

Exactly one identically regularized multi-output Ridge model is fit per frozen
v4.2 next-open state.  Each state model predicts only the three actions that are
economically novel relative to that state.  Market factors, labels, sampling,
embargo, score thresholds, actions and costs remain inherited from v4.16/v4.17.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.v4_14_multifactor_event_discovery import _assign_macro_clusters
from src.research.v4_16_action_advantage_model import (
    ACTION_KEYS,
    AdvantageModelResult,
    AdvantagePolicyResult,
    _coefficient_cosine,
    _coefficient_frame,
    _embargo_train_end,
    _fit_model,
    _quintile_spread,
    run_action_advantage_policy,
)
from src.research.v4_17_state_conditioned_action_advantage import (
    StateConditionedResearchResult,
    _market_frame_and_labels,
    _state_features,
    run_state_conditioned_research,
)

_EVENT_COLUMNS = (
    "sample",
    "fold",
    "event_family",
    "action",
    "event_id",
    "rule_id",
    "baseline_state",
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


@dataclass(frozen=True)
class StateSpecificResearchResult:
    state_specific_model: AdvantageModelResult
    state_specific_policy: AdvantagePolicyResult
    state_conditioned_comparator: StateConditionedResearchResult
    action_state_metrics: pd.DataFrame
    state_coefficient_stability: pd.DataFrame
    improvement_gate: dict[str, Any]
    final_gate: dict[str, Any]


def _fit_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(contract)
    training = dict(contract["training"])
    training["minimum_training_samples"] = int(training["minimum_training_samples_per_state"])
    result["training"] = training
    return result


def build_state_partitioned_frames(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    proxy, features, targets = _market_frame_and_labels(
        bars, proxy_baseline_daily, contract, actual=False
    )
    actual, actual_features, actual_targets = _market_frame_and_labels(
        bars, actual_baseline_daily, contract, actual=True
    )
    if features != actual_features or targets != actual_targets:
        raise AssertionError("proxy and actual schemas diverged")
    proxy = proxy.join(_state_features(proxy_baseline_daily, proxy.index))
    actual = actual.join(_state_features(actual_baseline_daily, actual.index))
    return proxy, actual, features, targets


def _state_actions(contract: Mapping[str, Any], state: int) -> tuple[str, ...]:
    raw = contract["state_action_sets"]
    key: Any = state if state in raw else str(state)
    actions = tuple(str(value) for value in raw[key])
    if len(actions) != 3 or len(set(actions)) != 3:
        raise AssertionError("each state must expose exactly three unique actions")
    return actions


def _predict_fold(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    fold_specification: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fold = str(fold_specification["fold"])
    test_start = pd.Timestamp(fold_specification["test_start"])
    test_end = pd.Timestamp(fold_specification["test_end"])
    train_end = _embargo_train_end(
        frame.index,
        test_start,
        pd.Timestamp(fold_specification["train_end"]),
        int(contract["training"]["embargo_sessions"]),
    )
    test = frame.loc[test_start:test_end].copy()
    output = test[[str(contract["actions"][action]["target"]) for action in ACTION_KEYS]].copy()
    for action in ACTION_KEYS:
        output[f"predicted_{action}"] = np.nan
    output["fold"] = fold
    output["next_open_position_state"] = test["next_open_position_state"]
    carry = [
        "qqq_distance_ma20",
        "qqq_distance_ma200",
        "voo_distance_ma200",
        "vol_max_percentile_252",
        "next_open_weight_QQQI",
        "next_open_weight_QQQ",
        "next_open_weight_TQQQ",
    ]
    output[carry] = test[carry]
    coefficient_parts: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    fit_contract = _fit_contract(contract)
    for state in (0, 1, 2):
        actions = _state_actions(contract, state)
        target_names = tuple(str(contract["actions"][action]["target"]) for action in actions)
        training = frame.loc[pd.Timestamp(fold_specification["train_start"]) : train_end].copy()
        training = training.loc[
            training["global_training_sample"].astype(bool)
            & training["next_open_position_state"].eq(state)
        ]
        complete = training.dropna(subset=list(target_names))
        minimum = int(contract["training"]["minimum_training_samples_per_state"])
        test_mask = test["next_open_position_state"].eq(state)
        coverage_rows.append(
            {
                "fold": fold,
                "state": state,
                "training_start": complete.index.min() if len(complete) else pd.NaT,
                "training_end": complete.index.max() if len(complete) else pd.NaT,
                "training_samples": int(len(complete)),
                "test_observations": int(test_mask.sum()),
                "model_fitted": bool(len(complete) >= minimum),
            }
        )
        if len(complete) < minimum or not bool(test_mask.any()):
            continue
        model = _fit_model(training, feature_names, target_names, fit_contract)
        predicted = np.asarray(model.predict(test.loc[test_mask, list(feature_names)]), dtype=float)
        for position, action in enumerate(actions):
            output.loc[test_mask, f"predicted_{action}"] = predicted[:, position]
        coefficient = _coefficient_frame(
            model,
            fold=fold,
            feature_names=feature_names,
            target_names=target_names,
        )
        coefficient["state"] = state
        coefficient_parts.append(coefficient)
    coefficients = (
        pd.concat(coefficient_parts, ignore_index=True)
        if coefficient_parts
        else pd.DataFrame(columns=["fold", "target", "feature", "coefficient", "state"])
    )
    return output, coefficients, pd.DataFrame(coverage_rows)


def _asset_eligible(
    predictions: pd.DataFrame,
    action: str,
    contract: Mapping[str, Any],
) -> pd.Series:
    allowed = pd.Series(False, index=predictions.index)
    for state in (0, 1, 2):
        if action in _state_actions(contract, state):
            allowed |= predictions["next_open_position_state"].eq(state)
    if action == "broad_equity":
        allowed &= predictions["voo_distance_ma200"].ge(0.0)
    elif action == "nasdaq_acceleration":
        allowed &= (
            predictions["qqq_distance_ma200"].gt(0.0)
            & predictions["qqq_distance_ma20"].le(
                float(contract["eligibility"]["acceleration_qqq_distance_ma20_max"])
            )
            & predictions["vol_max_percentile_252"].le(
                float(contract["eligibility"]["acceleration_vol_percentile_max"])
            )
        )
    return allowed.fillna(False).astype(bool)


def select_state_specific_events(
    predictions: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    sample: str,
) -> pd.DataFrame:
    score = pd.DataFrame(
        {action: predictions[f"predicted_{action}"] for action in ACTION_KEYS},
        index=predictions.index,
    )
    for action in ACTION_KEYS:
        score.loc[~_asset_eligible(predictions, action, contract), action] = -np.inf
    score = score.fillna(-np.inf)
    top_action = score.idxmax(axis=1)
    top_score = score.max(axis=1)
    second_score = score.apply(
        lambda row: float(np.partition(row.to_numpy(dtype=float), -2)[-2]), axis=1
    )
    qualifies = (
        top_score.ge(float(contract["training"]["advantage_threshold"]))
        & (top_score - second_score).ge(float(contract["training"]["action_margin_threshold"]))
        & np.isfinite(top_score)
    )
    fresh = qualifies & ~(qualifies.shift(1, fill_value=False) & top_action.eq(top_action.shift(1)))
    rows: list[dict[str, Any]] = []
    next_allowed = 0
    cooldown = int(contract["training"]["cooldown_sessions"])
    index = predictions.index
    for location, active in enumerate(fresh.to_numpy(dtype=bool)):
        if not active or location < next_allowed:
            continue
        action = str(top_action.iloc[location])
        horizon = int(contract["actions"][action]["holding_sessions"])
        if location + 1 + horizon > len(index):
            continue
        target = str(contract["actions"][action]["target"])
        realized = predictions.iloc[location][target]
        if not np.isfinite(realized):
            continue
        rows.append(
            {
                "sample": sample,
                "fold": str(predictions.iloc[location].get("fold", sample)),
                "event_family": action,
                "action": str(contract["actions"][action]["action"]),
                "event_id": f"{sample}_{action}_{len(rows) + 1:03d}",
                "rule_id": "ridge_state_specific_residual_v4_18",
                "baseline_state": int(predictions.iloc[location]["next_open_position_state"]),
                "signal_close_date": index[location],
                "execution_date": index[location + 1],
                "event_end_date": index[location + horizon],
                "holding_sessions": horizon,
                "predicted_advantage": float(top_score.iloc[location]),
                "second_best_advantage": float(second_score.iloc[location]),
                "predicted_margin": float(top_score.iloc[location] - second_score.iloc[location]),
                "realized_advantage": float(realized),
                "win": bool(realized > 0.0),
            }
        )
        next_allowed = location + 1 + horizon + cooldown
    if not rows:
        return pd.DataFrame(columns=list(_EVENT_COLUMNS))
    return pd.DataFrame(rows, columns=list(_EVENT_COLUMNS))


def _action_state_metrics(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for state in (0, 1, 2):
        for action in _state_actions(contract, state):
            target = str(contract["actions"][action]["target"])
            mask = predictions["next_open_position_state"].eq(state)
            mask &= _asset_eligible(predictions, action, contract)
            aligned = (
                predictions.loc[mask, [f"predicted_{action}", target]]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
            )
            cell_events = events.loc[
                events["baseline_state"].eq(state) & events["event_family"].eq(action)
            ]
            rows.append(
                {
                    "state": state,
                    "action": action,
                    "observations": int(len(aligned)),
                    "spearman_ic": float(
                        aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman")
                    )
                    if len(aligned) >= 2
                    else np.nan,
                    "top_bottom_quintile_spread": _quintile_spread(
                        aligned.iloc[:, 0], aligned.iloc[:, 1]
                    ),
                    "unconditional_positive_rate": float(aligned.iloc[:, 1].gt(0.0).mean())
                    if len(aligned)
                    else np.nan,
                    "triggered_events": int(len(cell_events)),
                    "triggered_precision": float(cell_events["win"].mean())
                    if len(cell_events)
                    else np.nan,
                    "median_triggered_advantage": float(cell_events["realized_advantage"].median())
                    if len(cell_events)
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _pooled_action_metrics(
    cell_metrics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for action, group in cell_metrics.groupby("action"):
        weights = group["observations"].to_numpy(dtype=float)
        valid_ic = group["spearman_ic"].notna()
        valid_spread = group["top_bottom_quintile_spread"].notna()
        rows.append(
            {
                "action": action,
                "observations": int(group["observations"].sum()),
                "spearman_ic": float(
                    np.average(
                        group.loc[valid_ic, "spearman_ic"],
                        weights=group.loc[valid_ic, "observations"],
                    )
                )
                if valid_ic.any()
                else np.nan,
                "top_bottom_quintile_spread": float(
                    np.average(
                        group.loc[valid_spread, "top_bottom_quintile_spread"],
                        weights=group.loc[valid_spread, "observations"],
                    )
                )
                if valid_spread.any()
                else np.nan,
                "unconditional_positive_rate": float(
                    np.average(
                        group["unconditional_positive_rate"].fillna(0.0),
                        weights=np.maximum(weights, 1.0),
                    )
                ),
                "mean_realized_advantage": np.nan,
            }
        )
    return pd.DataFrame(rows)


def _state_stability(coefficients: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for state in (0, 1, 2):
        table = coefficients.loc[coefficients["state"].eq(state)]
        pairs, median = _coefficient_cosine(table.drop(columns="state"))
        rows.append(
            {
                "state": state,
                "folds": int(table["fold"].nunique()),
                "pairwise_comparisons": int(len(pairs)),
                "median_cosine": median,
                "minimum_cosine": float(pairs["cosine"].min()) if len(pairs) else np.nan,
                "maximum_cosine": float(pairs["cosine"].max()) if len(pairs) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _model_gate(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    cells: pd.DataFrame,
    stability: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["model_gate"]
    ic_pass = cells["spearman_ic"].ge(float(threshold["action_state_ic_min"]))
    spread_pass = cells["top_bottom_quintile_spread"].gt(0.0)
    joint_pass = ic_pass & spread_pass
    states_with_two = int(joint_pass.groupby(cells["state"]).sum().ge(2).sum())
    large = cells.loc[cells["observations"].ge(int(threshold["large_cell_observations_min"]))]
    eligible_values: list[pd.Series] = []
    for state in (0, 1, 2):
        for action in _state_actions(contract, state):
            target = str(contract["actions"][action]["target"])
            mask = predictions["next_open_position_state"].eq(state)
            mask &= _asset_eligible(predictions, action, contract)
            eligible_values.append(predictions.loc[mask, target])
    base_rate = float(pd.concat(eligible_values, ignore_index=True).dropna().gt(0.0).mean())
    precision = float(events["win"].mean()) if len(events) else np.nan
    median_advantage = float(events["realized_advantage"].median()) if len(events) else np.nan
    clustered = _assign_macro_clusters(
        events,
        int(contract["training"]["macro_cluster_calendar_days"]),
    )
    positive_cluster = (
        clustered.groupby("macro_cluster_id")["realized_advantage"].sum().clip(lower=0.0)
        if len(clustered)
        else pd.Series(dtype=float)
    )
    total_positive = float(positive_cluster.sum())
    cluster_share = float(positive_cluster.max() / total_positive) if total_positive > 0.0 else 1.0
    yearly = (
        events.groupby(pd.to_datetime(events["signal_close_date"]).dt.year)[
            "realized_advantage"
        ].sum()
        if len(events)
        else pd.Series(dtype=float)
    )
    without_best = float(yearly.drop(index=yearly.idxmax()).sum()) if len(yearly) > 1 else np.nan
    checks = {
        "cells_passing_ic": int(ic_pass.sum()) >= int(threshold["eligible_cells_passing_ic_min"]),
        "cells_positive_spread": int(spread_pass.sum())
        >= int(threshold["eligible_cells_positive_quintile_spread_min"]),
        "states_with_two_actions": states_with_two
        >= int(threshold["states_with_two_actions_passing_min"]),
        "large_cell_floor": bool(
            large["spearman_ic"].ge(float(threshold["large_cell_ic_floor"])).all()
        ),
        "coefficient_stability": bool(
            stability["median_cosine"]
            .ge(float(threshold["coefficient_cosine_similarity_median_min"]))
            .all()
        ),
        "precision_lift": np.isfinite(precision)
        and precision - base_rate >= float(threshold["triggered_precision_lift_min"]),
        "median_advantage": np.isfinite(median_advantage)
        and median_advantage > float(threshold["median_triggered_advantage_min"]),
        "macro_clusters": int(clustered["macro_cluster_id"].nunique())
        >= int(threshold["minimum_macro_clusters"]),
        "cluster_concentration": cluster_share
        <= float(threshold["largest_positive_cluster_share_max"]),
        "without_best_year": np.isfinite(without_best) and without_best >= 0.0,
    }
    return {
        "checks": checks,
        "metrics": {
            "eligible_cells_passing_ic": int(ic_pass.sum()),
            "eligible_cells_positive_spread": int(spread_pass.sum()),
            "eligible_cells_passing_both": int(joint_pass.sum()),
            "states_with_two_actions_passing": states_with_two,
            "pooled_eligible_positive_rate": base_rate,
            "triggered_precision": precision,
            "triggered_precision_lift": precision - base_rate if np.isfinite(precision) else np.nan,
            "median_triggered_advantage": median_advantage,
            "macro_clusters": int(clustered["macro_cluster_id"].nunique()),
            "largest_positive_cluster_share": cluster_share,
            "triggered_advantage_without_best_year": without_best,
        },
        "passed": bool(all(checks.values())),
    }


def run_state_specific_model(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[AdvantageModelResult, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    proxy, actual, features, targets = build_state_partitioned_frames(
        bars, proxy_baseline_daily, actual_baseline_daily, contract
    )
    prediction_parts: list[pd.DataFrame] = []
    coefficient_parts: list[pd.DataFrame] = []
    coverage_parts: list[pd.DataFrame] = []
    for fold in contract["outer_folds"]:
        prediction, coefficient, coverage = _predict_fold(proxy, features, contract, fold)
        prediction_parts.append(prediction)
        coefficient_parts.append(coefficient)
        coverage_parts.append(coverage)
    oof = pd.concat(prediction_parts).sort_index()
    coefficients = pd.concat(coefficient_parts, ignore_index=True)
    coverage = pd.concat(coverage_parts, ignore_index=True)
    events = select_state_specific_events(oof, contract, sample="oof")
    cells = _action_state_metrics(oof, events, contract)
    stability = _state_stability(coefficients)
    gate = _model_gate(oof, events, cells, stability, contract)
    action_metrics = _pooled_action_metrics(cells)

    actual_start = max(pd.Timestamp(contract["data"]["actual_product_start"]), actual.index.min())
    train_end = _embargo_train_end(
        proxy.index,
        actual_start,
        pd.Timestamp("2023-12-29"),
        int(contract["training"]["embargo_sessions"]),
    )
    actual_sample = actual.loc[actual_start:].copy()
    actual_output = actual_sample[list(targets)].copy()
    for action in ACTION_KEYS:
        actual_output[f"predicted_{action}"] = np.nan
    actual_output["fold"] = "actual_2024_plus"
    actual_output["next_open_position_state"] = actual_sample["next_open_position_state"]
    carry = [
        "qqq_distance_ma20",
        "qqq_distance_ma200",
        "voo_distance_ma200",
        "vol_max_percentile_252",
        "next_open_weight_QQQI",
        "next_open_weight_QQQ",
        "next_open_weight_TQQQ",
    ]
    actual_output[carry] = actual_sample[carry]
    actual_coefficient_parts: list[pd.DataFrame] = []
    fit_contract = _fit_contract(contract)
    for state in (0, 1, 2):
        actions = _state_actions(contract, state)
        target_names = tuple(str(contract["actions"][action]["target"]) for action in actions)
        training = proxy.loc[pd.Timestamp("2011-01-03") : train_end]
        training = training.loc[
            training["global_training_sample"].astype(bool)
            & training["next_open_position_state"].eq(state)
        ]
        complete = training.dropna(subset=list(target_names))
        if len(complete) < int(contract["training"]["minimum_training_samples_per_state"]):
            continue
        mask = actual_sample["next_open_position_state"].eq(state)
        if not bool(mask.any()):
            continue
        model = _fit_model(training, features, target_names, fit_contract)
        predicted = np.asarray(model.predict(actual_sample.loc[mask, list(features)]), dtype=float)
        for position, action in enumerate(actions):
            actual_output.loc[mask, f"predicted_{action}"] = predicted[:, position]
        coefficient = _coefficient_frame(
            model,
            fold="actual_2024_plus",
            feature_names=features,
            target_names=target_names,
        )
        coefficient["state"] = state
        actual_coefficient_parts.append(coefficient)
    actual_coefficients = (
        pd.concat(actual_coefficient_parts, ignore_index=True)
        if actual_coefficient_parts
        else pd.DataFrame(columns=["fold", "target", "feature", "coefficient", "state"])
    )
    actual_events = select_state_specific_events(actual_output, contract, sample="actual_2024_plus")
    result = AdvantageModelResult(
        frame=proxy,
        feature_names=features,
        target_names=targets,
        oof_predictions=oof,
        fold_coefficients=coefficients,
        action_metrics=action_metrics,
        oof_events=events,
        model_gate=gate,
        actual_predictions=actual_output,
        actual_events=actual_events,
        actual_coefficients=actual_coefficients,
    )
    return result, cells, stability, coverage


def _improvement_gate(
    model: AdvantageModelResult,
    policy: AdvantagePolicyResult,
    comparator: StateConditionedResearchResult,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["v4_17_improvement_gate"]
    current_cells = int(model.model_gate["metrics"]["eligible_cells_passing_both"])
    previous_cells = int(
        comparator.state_model.model_gate["metrics"].get("eligible_cells_passing_ic", 0)
    )
    current_lift = float(model.model_gate["metrics"]["triggered_precision_lift"])
    previous_lift = float(comparator.state_model.model_gate["metrics"]["triggered_precision_lift"])
    current_metrics = policy.oof_results["full_event_policy"].metrics
    previous_metrics = comparator.state_policy.oof_results["full_event_policy"].metrics
    cagr_pp = (float(current_metrics["cagr"]) - float(previous_metrics["cagr"])) * 100.0
    calmar = float(current_metrics["calmar"]) - float(previous_metrics["calmar"])
    checks = {
        "passing_cells": current_cells - previous_cells
        >= int(threshold["passing_cell_improvement_min"]),
        "precision_lift": current_lift - previous_lift
        >= float(threshold["triggered_precision_lift_improvement_min"]),
        "oof_cagr": cagr_pp >= float(threshold["oof_cagr_improvement_pp_min"]),
        "oof_calmar": calmar >= float(threshold["oof_calmar_improvement_min"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "passing_cell_improvement": current_cells - previous_cells,
            "triggered_precision_lift_improvement": current_lift - previous_lift,
            "oof_cagr_improvement_pp": cagr_pp,
            "oof_calmar_improvement": calmar,
        },
        "passed": bool(all(checks.values())),
    }


def run_state_specific_research(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v4_17_contract: Mapping[str, Any],
) -> StateSpecificResearchResult:
    model, cells, stability, coverage = run_state_specific_model(
        bars, proxy_baseline_daily, actual_baseline_daily, contract
    )
    policy = run_action_advantage_policy(
        bars,
        proxy_baseline_daily,
        actual_baseline_daily,
        model,
        contract,
    )
    comparator = run_state_conditioned_research(
        bars,
        proxy_baseline_daily,
        actual_baseline_daily,
        v4_17_contract,
    )
    improvement = _improvement_gate(model, policy, comparator, contract)
    checks = {
        "model_gate": bool(model.model_gate["passed"]),
        "portfolio_gate": bool(policy.portfolio_gate["passed"]),
        "actual_contradiction_gate": bool(policy.contradiction_gate["passed"]),
        "v4_17_improvement_gate": bool(improvement["passed"]),
        "all_state_models_fitted": bool(coverage["model_fitted"].all()),
    }
    final = {"checks": checks, "passed": bool(all(checks.values()))}
    return StateSpecificResearchResult(
        state_specific_model=model,
        state_specific_policy=policy,
        state_conditioned_comparator=comparator,
        action_state_metrics=cells,
        state_coefficient_stability=stability,
        improvement_gate=improvement,
        final_gate=final,
    )
