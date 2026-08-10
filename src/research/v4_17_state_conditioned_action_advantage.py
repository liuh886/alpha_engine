"""State-conditioned incremental action-advantage research for v4.17.

The experiment changes exactly one structural component from v4.16: the same
multi-output Ridge model additionally observes the close-decided next-open v4.2
state and weights.  Candidate actions whose proxy-economic weights do not differ
materially from the next-open baseline are excluded before score comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars
from src.research.v4_14_multifactor_event_discovery import (
    _assign_macro_clusters,
    _forward_total_return,
    build_multifactor_feature_frame,
)
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
from src.research.v4_16_action_advantage_runtime import (
    run_action_advantage_model as run_unconditioned_v4_16_model,
)

_EVENT_COLUMNS = (
    "sample",
    "fold",
    "event_family",
    "action",
    "event_id",
    "rule_id",
    "baseline_state",
    "novelty_l1",
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
class StateConditionedResearchResult:
    state_model: AdvantageModelResult
    state_policy: AdvantagePolicyResult
    unconditioned_model: AdvantageModelResult
    unconditioned_policy: AdvantagePolicyResult
    action_state_metrics: pd.DataFrame
    improvement_gate: dict[str, Any]
    final_gate: dict[str, Any]


def _v4_16_compatible_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Map inherited fields to the exact v4.16 runtime without changing values."""

    result = dict(contract)
    result["interactions"] = list(contract["market_interactions"])
    return result


def _state_features(
    baseline_daily: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    required = [
        "position_state",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
    ]
    missing = sorted(set(required) - set(baseline_daily.columns))
    if missing:
        raise ValueError(f"baseline daily missing state fields: {missing}")
    next_open = baseline_daily[required].shift(-1).reindex(index)
    output = pd.DataFrame(index=index)
    state = next_open["position_state"]
    output["next_open_position_state"] = state
    for value in (0, 1, 2):
        output[f"next_open_state_{value}"] = state.eq(value).astype(float)
    for asset in ("QQQI", "QQQ", "TQQQ"):
        output[f"next_open_weight_{asset}"] = next_open[f"weight_{asset}"]
    return output


def _add_state_conditioning(
    frame: pd.DataFrame,
    baseline_daily: pd.DataFrame,
    market_feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    output = frame.join(_state_features(baseline_daily, frame.index))
    feature_names = list(market_feature_names)
    state_features = [str(value) for value in contract["state_features"]]
    feature_names.extend(state_features)
    state_interactions: list[str] = []
    for state_feature in contract["state_interactions"]["states"]:
        for market_interaction in contract["state_interactions"]["market_interactions"]:
            name = f"{state_feature}__{market_interaction}"
            output[name] = output[str(state_feature)] * output[str(market_interaction)]
            state_interactions.append(name)
    expected = int(contract["state_interactions"]["expected_count"])
    if len(state_interactions) != expected:
        raise AssertionError("unexpected state interaction count")
    feature_names.extend(state_interactions)
    if len(feature_names) != int(contract["state_interactions"]["total_model_inputs"]):
        raise AssertionError("unexpected total state-conditioned model inputs")
    return output, tuple(feature_names)


def _market_frame_and_labels(
    bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    actual: bool,
) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    """Build inherited market inputs and proxy or actual action labels."""

    frame = build_multifactor_feature_frame(bars, baseline_daily).copy()
    frame["qqq_rsi20_centered"] = (frame["qqq_rsi20"] - 50.0) / 50.0
    feature_names = [str(value) for value in contract["base_features"]]
    for raw in contract["market_interactions"]:
        name = str(raw["name"])
        frame[name] = pd.to_numeric(frame[str(raw["left"])], errors="coerce") * pd.to_numeric(
            frame[str(raw["right"])], errors="coerce"
        )
        feature_names.append(name)

    baseline_return = baseline_daily["net_return"].reindex(frame.index)
    baseline_10d = _forward_total_return(baseline_return, 10)
    baseline_5d = _forward_total_return(baseline_return, 5)
    if actual:
        qqqi = _normalise_bars(bars["QQQI"], "QQQI")
        sgov = _normalise_bars(bars["SGOV"], "SGOV")
        qqqi_daily = qqqi["open"].shift(-1).div(qqqi["open"]).sub(1.0).reindex(frame.index)
        cash_daily = sgov["open"].shift(-1).div(sgov["open"]).sub(1.0).reindex(frame.index)
        cash_10d = _forward_total_return(cash_daily, 10)
        core_10d = _forward_total_return(qqqi_daily, 10)
    else:
        cash_10d = frame["forward_bil_10d"]
        core_10d = frame["forward_qqq_10d"]
    acceleration_daily = (
        0.25 * frame["qqq_next_open_return"] + 0.75 * frame["tqqq_next_open_return"]
    )
    acceleration_5d = _forward_total_return(acceleration_daily, 5)
    label_cost = float(contract["boundaries"]["label_round_trip_cost_bps"]) / 10_000.0
    frame["cash_defense_advantage_10d"] = cash_10d - baseline_10d - label_cost
    frame["broad_equity_advantage_10d"] = frame["forward_voo_10d"] - baseline_10d - label_cost
    frame["nasdaq_core_advantage_10d"] = core_10d - baseline_10d - label_cost
    frame["nasdaq_acceleration_advantage_5d"] = acceleration_5d - baseline_5d - label_cost
    target_names = tuple(str(contract["actions"][action]["target"]) for action in ACTION_KEYS)
    positions = np.arange(len(frame), dtype=int)
    frame["global_training_sample"] = (
        (positions - int(contract["training"]["global_anchor_position"]))
        % int(contract["training"]["sample_every_sessions"])
    ) == 0
    return frame, tuple(feature_names), target_names


def build_state_conditioned_frames(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    tuple[str, ...],
    tuple[str, ...],
]:
    proxy, market_features, targets = _market_frame_and_labels(
        bars, proxy_baseline_daily, contract, actual=False
    )
    actual, actual_market_features, actual_targets = _market_frame_and_labels(
        bars, actual_baseline_daily, contract, actual=True
    )
    if market_features != actual_market_features or targets != actual_targets:
        raise AssertionError("proxy and actual model schemas diverged")
    proxy, feature_names = _add_state_conditioning(
        proxy, proxy_baseline_daily, market_features, contract
    )
    actual, actual_feature_names = _add_state_conditioning(
        actual, actual_baseline_daily, market_features, contract
    )
    if feature_names != actual_feature_names:
        raise AssertionError("proxy and actual state-conditioned inputs diverged")
    return proxy, actual, feature_names, targets


def _predict_fold(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    target_names: Sequence[str],
    contract: Mapping[str, Any],
    fold_specification: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fold = str(fold_specification["fold"])
    test_start = pd.Timestamp(fold_specification["test_start"])
    test_end = pd.Timestamp(fold_specification["test_end"])
    train_start = pd.Timestamp(fold_specification["train_start"])
    train_end = _embargo_train_end(
        frame.index,
        test_start,
        pd.Timestamp(fold_specification["train_end"]),
        int(contract["training"]["embargo_sessions"]),
    )
    training = frame.loc[train_start:train_end]
    training = training.loc[training["global_training_sample"].astype(bool)]
    model = _fit_model(training, feature_names, target_names, contract)
    test = frame.loc[test_start:test_end].copy()
    predicted = np.asarray(model.predict(test[list(feature_names)]), dtype=float)
    output = test[list(target_names)].copy()
    for position, action in enumerate(ACTION_KEYS):
        output[f"predicted_{action}"] = predicted[:, position]
    output["fold"] = fold
    output["training_start"] = training.index.min()
    output["training_end"] = training.index.max()
    output["training_samples"] = int(training.dropna(subset=list(target_names)).shape[0])
    carry = [
        "qqq_distance_ma20",
        "qqq_distance_ma200",
        "voo_distance_ma200",
        "vol_max_percentile_252",
        "next_open_position_state",
        "next_open_weight_QQQI",
        "next_open_weight_QQQ",
        "next_open_weight_TQQQ",
    ]
    output[carry] = test[carry]
    return output, _coefficient_frame(
        model,
        fold=fold,
        feature_names=feature_names,
        target_names=target_names,
    )


def _baseline_economic_vector(predictions: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "NASDAQ_CORE": predictions["next_open_weight_QQQI"]
            + predictions["next_open_weight_QQQ"],
            "TQQQ": predictions["next_open_weight_TQQQ"],
            "VOO": 0.0,
            "cash": 0.0,
        },
        index=predictions.index,
    )


def action_novelty_l1(
    predictions: pd.DataFrame,
    action: str,
    contract: Mapping[str, Any],
) -> pd.Series:
    baseline = _baseline_economic_vector(predictions)
    candidate = np.asarray(contract["actions"][action]["economic_vector"], dtype=float)
    return pd.Series(
        np.abs(baseline.to_numpy(dtype=float) - candidate).sum(axis=1),
        index=predictions.index,
        dtype=float,
    )


def _action_eligible(
    predictions: pd.DataFrame,
    action: str,
    contract: Mapping[str, Any],
) -> pd.Series:
    novelty = action_novelty_l1(predictions, action, contract).ge(
        float(contract["training"]["action_novelty_l1_min"])
    )
    if action == "broad_equity":
        novelty &= predictions["voo_distance_ma200"].ge(0.0)
    elif action == "nasdaq_acceleration":
        novelty &= (
            predictions["qqq_distance_ma200"].gt(0.0)
            & predictions["qqq_distance_ma20"].le(
                float(contract["eligibility"]["acceleration_qqq_distance_ma20_max"])
            )
            & predictions["vol_max_percentile_252"].le(
                float(contract["eligibility"]["acceleration_vol_percentile_max"])
            )
        )
    return novelty.fillna(False).astype(bool)


def select_novel_action_events(
    predictions: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    sample: str,
) -> pd.DataFrame:
    score = pd.DataFrame(
        {action: predictions[f"predicted_{action}"] for action in ACTION_KEYS},
        index=predictions.index,
    )
    novelty = {action: action_novelty_l1(predictions, action, contract) for action in ACTION_KEYS}
    for action in ACTION_KEYS:
        score.loc[~_action_eligible(predictions, action, contract), action] = -np.inf
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
    index = predictions.index
    cooldown = int(contract["training"]["cooldown_sessions"])
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
                "rule_id": "ridge_state_conditioned_action_advantage_v4_17",
                "baseline_state": int(predictions.iloc[location]["next_open_position_state"]),
                "novelty_l1": float(novelty[action].iloc[location]),
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


def _action_metrics(
    predictions: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for action in ACTION_KEYS:
        target = str(contract["actions"][action]["target"])
        aligned = predictions[[f"predicted_{action}", target]].dropna()
        rows.append(
            {
                "action": action,
                "observations": int(len(aligned)),
                "spearman_ic": float(
                    aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman")
                ),
                "top_bottom_quintile_spread": _quintile_spread(
                    aligned.iloc[:, 0], aligned.iloc[:, 1]
                ),
                "unconditional_positive_rate": float(aligned.iloc[:, 1].gt(0.0).mean()),
                "mean_realized_advantage": float(aligned.iloc[:, 1].mean()),
            }
        )
    return pd.DataFrame(rows)


def _action_state_metrics(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    novelty_cells = contract["eligibility"]["novelty_cells"]
    for action in ACTION_KEYS:
        target = str(contract["actions"][action]["target"])
        for state in novelty_cells[action]:
            mask = predictions["next_open_position_state"].eq(int(state))
            mask &= _action_eligible(predictions, action, contract)
            aligned = predictions.loc[mask, [f"predicted_{action}", target]].dropna()
            cell_events = events.loc[
                events["event_family"].eq(action) & events["baseline_state"].eq(int(state))
            ]
            rows.append(
                {
                    "action": action,
                    "state": int(state),
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


def _state_model_gate(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    coefficients: pd.DataFrame,
    action_metrics: pd.DataFrame,
    cell_metrics: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["model_gate"]
    cosine_pairs, cosine_median = _coefficient_cosine(coefficients)
    passing_actions = int(action_metrics["spearman_ic"].ge(float(threshold["action_ic_min"])).sum())
    positive_action_spreads = int(action_metrics["top_bottom_quintile_spread"].gt(0.0).sum())
    passing_cells = int(cell_metrics["spearman_ic"].ge(float(threshold["action_ic_min"])).sum())
    positive_cell_spreads = int(cell_metrics["top_bottom_quintile_spread"].gt(0.0).sum())
    large_cells = cell_metrics.loc[
        cell_metrics["observations"].ge(int(threshold["large_cell_observations_min"]))
    ]
    large_cell_floor = bool(
        large_cells["spearman_ic"].ge(float(threshold["large_cell_ic_floor"])).all()
    )
    eligible_values: list[pd.Series] = []
    for action in ACTION_KEYS:
        target = str(contract["actions"][action]["target"])
        eligible_values.append(
            predictions.loc[_action_eligible(predictions, action, contract), target]
        )
    pooled_base_rate = float(pd.concat(eligible_values, ignore_index=True).dropna().gt(0.0).mean())
    triggered_precision = float(events["win"].mean()) if len(events) else np.nan
    median_triggered = float(events["realized_advantage"].median()) if len(events) else np.nan
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
    without_best_year = (
        float(yearly.drop(index=yearly.idxmax()).sum()) if len(yearly) > 1 else np.nan
    )
    checks = {
        "actions_passing_ic": passing_actions >= int(threshold["actions_passing_ic_min"]),
        "actions_positive_spread": positive_action_spreads
        >= int(threshold["actions_positive_quintile_spread_min"]),
        "eligible_cells_passing_ic": passing_cells
        >= int(threshold["eligible_cells_passing_ic_min"]),
        "eligible_cells_positive_spread": positive_cell_spreads
        >= int(threshold["eligible_cells_positive_quintile_spread_min"]),
        "large_cell_ic_floor": large_cell_floor,
        "triggered_precision_lift": np.isfinite(triggered_precision)
        and triggered_precision - pooled_base_rate
        >= float(threshold["triggered_precision_lift_min"]),
        "median_triggered_advantage": np.isfinite(median_triggered)
        and median_triggered > float(threshold["median_triggered_advantage_min"]),
        "minimum_macro_clusters": int(clustered["macro_cluster_id"].nunique())
        >= int(threshold["minimum_macro_clusters"]),
        "cluster_concentration": cluster_share
        <= float(threshold["largest_positive_cluster_share_max"]),
        "coefficient_stability": np.isfinite(cosine_median)
        and cosine_median >= float(threshold["coefficient_cosine_similarity_median_min"]),
        "without_best_year": np.isfinite(without_best_year) and without_best_year >= 0.0,
    }
    return {
        "checks": checks,
        "metrics": {
            "actions_passing_ic": passing_actions,
            "actions_positive_quintile_spread": positive_action_spreads,
            "eligible_cells_passing_ic": passing_cells,
            "eligible_cells_positive_quintile_spread": positive_cell_spreads,
            "large_cells": int(len(large_cells)),
            "pooled_eligible_positive_rate": pooled_base_rate,
            "triggered_precision": triggered_precision,
            "triggered_precision_lift": triggered_precision - pooled_base_rate
            if np.isfinite(triggered_precision)
            else np.nan,
            "median_triggered_advantage": median_triggered,
            "macro_clusters": int(clustered["macro_cluster_id"].nunique()),
            "largest_positive_cluster_share": cluster_share,
            "coefficient_cosine_similarity_median": cosine_median,
            "triggered_advantage_without_best_year": without_best_year,
        },
        "coefficient_cosine_pairs": cosine_pairs.to_dict(orient="records"),
        "passed": bool(all(checks.values())),
    }


def run_state_conditioned_model(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[AdvantageModelResult, pd.DataFrame]:
    proxy, actual, feature_names, target_names = build_state_conditioned_frames(
        bars, proxy_baseline_daily, actual_baseline_daily, contract
    )
    prediction_parts: list[pd.DataFrame] = []
    coefficient_parts: list[pd.DataFrame] = []
    for fold in contract["outer_folds"]:
        prediction, coefficient = _predict_fold(proxy, feature_names, target_names, contract, fold)
        prediction_parts.append(prediction)
        coefficient_parts.append(coefficient)
    oof = pd.concat(prediction_parts).sort_index()
    coefficients = pd.concat(coefficient_parts, ignore_index=True)
    events = select_novel_action_events(oof, contract, sample="oof")
    action_metrics = _action_metrics(oof, contract)
    cell_metrics = _action_state_metrics(oof, events, contract)
    model_gate = _state_model_gate(
        oof, events, coefficients, action_metrics, cell_metrics, contract
    )

    actual_start = max(pd.Timestamp(contract["data"]["actual_product_start"]), actual.index.min())
    train_end = _embargo_train_end(
        proxy.index,
        actual_start,
        pd.Timestamp("2023-12-29"),
        int(contract["training"]["embargo_sessions"]),
    )
    training = proxy.loc[pd.Timestamp("2011-01-03") : train_end]
    training = training.loc[training["global_training_sample"].astype(bool)]
    model = _fit_model(training, feature_names, target_names, contract)
    actual_sample = actual.loc[actual_start:].copy()
    predicted = np.asarray(model.predict(actual_sample[list(feature_names)]), dtype=float)
    actual_output = actual_sample[list(target_names)].copy()
    for position, action in enumerate(ACTION_KEYS):
        actual_output[f"predicted_{action}"] = predicted[:, position]
    actual_output["fold"] = "actual_2024_plus"
    carry = [
        "qqq_distance_ma20",
        "qqq_distance_ma200",
        "voo_distance_ma200",
        "vol_max_percentile_252",
        "next_open_position_state",
        "next_open_weight_QQQI",
        "next_open_weight_QQQ",
        "next_open_weight_TQQQ",
    ]
    actual_output[carry] = actual_sample[carry]
    actual_events = select_novel_action_events(actual_output, contract, sample="actual_2024_plus")
    actual_coefficients = _coefficient_frame(
        model,
        fold="actual_2024_plus",
        feature_names=feature_names,
        target_names=target_names,
    )
    result = AdvantageModelResult(
        frame=proxy,
        feature_names=feature_names,
        target_names=target_names,
        oof_predictions=oof,
        fold_coefficients=coefficients,
        action_metrics=action_metrics,
        oof_events=events,
        model_gate=model_gate,
        actual_predictions=actual_output,
        actual_events=actual_events,
        actual_coefficients=actual_coefficients,
    )
    return result, cell_metrics


def _improvement_gate(
    state_model: AdvantageModelResult,
    state_policy: AdvantagePolicyResult,
    unconditioned_model: AdvantageModelResult,
    unconditioned_policy: AdvantagePolicyResult,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["v4_16_improvement_gate"]
    state_actions = int(state_model.model_gate["metrics"]["actions_passing_ic"])
    unconditioned_actions = int(unconditioned_model.model_gate["metrics"]["actions_passing_ic"])
    state_precision_lift = float(state_model.model_gate["metrics"]["triggered_precision_lift"])
    unconditioned_precision_lift = float(
        unconditioned_model.model_gate["metrics"]["triggered_precision_lift"]
    )
    state_oof = state_policy.oof_results["full_event_policy"].metrics
    unconditioned_oof = unconditioned_policy.oof_results["full_event_policy"].metrics
    cagr_improvement_pp = (float(state_oof["cagr"]) - float(unconditioned_oof["cagr"])) * 100.0
    calmar_improvement = float(state_oof["calmar"]) - float(unconditioned_oof["calmar"])
    checks = {
        "actions_passing_ic": state_actions - unconditioned_actions
        >= int(threshold["actions_passing_ic_improvement_min"]),
        "precision_lift": state_precision_lift - unconditioned_precision_lift
        >= float(threshold["triggered_precision_lift_improvement_min"]),
        "oof_cagr": cagr_improvement_pp >= float(threshold["oof_cagr_improvement_pp_min"]),
        "oof_calmar": calmar_improvement >= float(threshold["oof_calmar_improvement_min"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "actions_passing_ic_improvement": state_actions - unconditioned_actions,
            "triggered_precision_lift_improvement": state_precision_lift
            - unconditioned_precision_lift,
            "oof_cagr_improvement_pp": cagr_improvement_pp,
            "oof_calmar_improvement": calmar_improvement,
        },
        "passed": bool(all(checks.values())),
    }


def run_state_conditioned_research(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> StateConditionedResearchResult:
    state_model, cell_metrics = run_state_conditioned_model(
        bars, proxy_baseline_daily, actual_baseline_daily, contract
    )
    state_policy = run_action_advantage_policy(
        bars,
        proxy_baseline_daily,
        actual_baseline_daily,
        state_model,
        contract,
    )
    v416_contract = _v4_16_compatible_contract(contract)
    unconditioned_model = run_unconditioned_v4_16_model(bars, proxy_baseline_daily, v416_contract)
    unconditioned_policy = run_action_advantage_policy(
        bars,
        proxy_baseline_daily,
        actual_baseline_daily,
        unconditioned_model,
        v416_contract,
    )
    improvement = _improvement_gate(
        state_model,
        state_policy,
        unconditioned_model,
        unconditioned_policy,
        contract,
    )
    checks = {
        "state_model_gate": bool(state_model.model_gate["passed"]),
        "state_portfolio_gate": bool(state_policy.portfolio_gate["passed"]),
        "actual_contradiction_gate": bool(state_policy.contradiction_gate["passed"]),
        "v4_16_improvement_gate": bool(improvement["passed"]),
    }
    final = {"checks": checks, "passed": bool(all(checks.values()))}
    return StateConditionedResearchResult(
        state_model=state_model,
        state_policy=state_policy,
        unconditioned_model=unconditioned_model,
        unconditioned_policy=unconditioned_policy,
        action_state_metrics=cell_metrics,
        improvement_gate=improvement,
        final_gate=final,
    )
