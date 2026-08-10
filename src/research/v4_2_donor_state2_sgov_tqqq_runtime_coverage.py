"""Coverage-safe execution for the v4.13 state2-only transfer experiment.

All formal target state-2 episodes are retained. Missing close-observable target
features are handled by the frozen pipeline's donor-trained median imputer. A
target calendar year that precedes a usable two-class donor sample receives no
synthetic probability and makes no strategy change: it is marked unavailable
and retains the frozen v4.2 75% TQQQ budget.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

import src.research.v4_2_donor_state2_sgov_tqqq as core
import src.research.v4_2_donor_state2_sgov_tqqq_runtime as base


def build_all_target_state2_prediction_rows(
    baseline_daily: pd.DataFrame,
    feature_frame: pd.DataFrame,
    *,
    features: Sequence[str],
) -> pd.DataFrame:
    """Retain every formal target episode and allow pipeline imputation."""

    state = baseline_daily["position_state"].astype(int)
    starts = state.eq(2) & state.shift(1, fill_value=0).ne(2)
    index = baseline_daily.index
    rows: list[dict[str, Any]] = []
    for number, execution_date in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(execution_date))
        if start_location <= 0:
            continue
        end_location = start_location
        while end_location + 1 < len(index) and int(state.iloc[end_location + 1]) == 2:
            end_location += 1
        signal_close_date = index[start_location - 1]
        row: dict[str, Any] = {
            "asset_episode_id": f"QQQ_{number:03d}",
            "underlying": "QQQ",
            "leveraged": "TQQQ",
            "signal_close_date": signal_close_date,
            "execution_date": execution_date,
            "episode_end_date": index[end_location],
            "holding_sessions": int(end_location - start_location + 1),
            "signal_row_available": signal_close_date in feature_frame.index,
        }
        if signal_close_date in feature_frame.index:
            signal = feature_frame.loc[signal_close_date]
            if isinstance(signal, pd.DataFrame):
                raise AssertionError("target feature frame contains duplicate dates")
            for feature in features:
                row[str(feature)] = signal.get(str(feature), float("nan"))
        else:
            for feature in features:
                row[str(feature)] = float("nan")
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("no target formal state-2 prediction rows were generated")
    return result.sort_values("execution_date").reset_index(drop=True)


def predict_target_episodes_with_coverage(
    target_episodes: pd.DataFrame,
    donor_episodes: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Predict with donor median imputation or retain an unavailable row."""

    features = tuple(str(value) for value in contract["features"])
    rows: list[pd.DataFrame] = []
    years = pd.to_datetime(target_episodes["signal_close_date"]).dt.year
    for year, validation in target_episodes.groupby(years):
        cutoff = pd.Timestamp(year=int(year), month=1, day=1)
        training = donor_episodes.loc[
            pd.to_datetime(donor_episodes["signal_close_date"]).lt(cutoff)
        ].copy()
        predicted = validation.copy()
        predicted["training_cutoff"] = cutoff
        predicted["training_episode_count"] = int(len(training))
        predicted["training_asset_count"] = int(training["underlying"].nunique())
        usable_training = len(training) >= 10 and training["positive_episode_excess"].nunique() >= 2
        usable_signal = predicted["signal_row_available"].astype(bool)
        predicted["probability"] = -1.0
        predicted["probability_available"] = False
        if usable_training and bool(usable_signal.any()):
            model = core._fit_pipeline(training, features, contract)
            locations = predicted.index[usable_signal]
            predicted.loc[locations, "probability"] = model.predict_proba(
                predicted.loc[locations, list(features)]
            )[:, 1]
            predicted.loc[locations, "probability_available"] = True
        rows.append(predicted)

    if not rows:
        raise ValueError("no target state-2 episode rows were produced")
    output = pd.concat(rows, ignore_index=True).sort_values("execution_date")
    low = float(contract["strategy_mapping"]["probability_low_below"])
    high = float(contract["strategy_mapping"]["probability_high_at_or_above"])
    output["probability_bucket"] = "medium"
    output.loc[output["probability"].lt(low), "probability_bucket"] = "low"
    output.loc[output["probability"].ge(high), "probability_bucket"] = "high"
    output.loc[~output["probability_available"], "probability_bucket"] = "unavailable"
    return output.reset_index(drop=True)


_ORIGINAL_VARIANT_WEIGHT = core._variant_tqqq_weight


def _coverage_safe_variant_weight(bucket: str, variant: str) -> float:
    if bucket == "unavailable":
        return 0.75
    return _ORIGINAL_VARIANT_WEIGHT(bucket, variant)


def run_donor_state2_sgov_tqqq(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[
    Any,
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, Any],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run the base target-safe runtime with explicit model availability."""

    original_builder = base.build_target_state2_prediction_rows
    original_predictor = base.predict_target_episodes_walk_forward
    original_weight = core._variant_tqqq_weight
    base.build_target_state2_prediction_rows = build_all_target_state2_prediction_rows
    base.predict_target_episodes_walk_forward = predict_target_episodes_with_coverage
    core._variant_tqqq_weight = _coverage_safe_variant_weight
    try:
        result = base.run_donor_state2_sgov_tqqq(bars, bridge_contract, contract)
    finally:
        base.build_target_state2_prediction_rows = original_builder
        base.predict_target_episodes_walk_forward = original_predictor
        core._variant_tqqq_weight = original_weight

    (
        model,
        predictions_by_scope,
        headline_by_scope,
        results_by_scope,
        attribution_by_scope,
        diagnostics,
    ) = result
    coverage: dict[str, dict[str, Any]] = {}
    for scope, predictions in predictions_by_scope.items():
        available = predictions["probability_available"].astype(bool)
        coverage[scope] = {
            "total_episodes": int(len(predictions)),
            "modeled_episodes": int(available.sum()),
            "unavailable_episodes": int((~available).sum()),
            "modeled_episode_rate": float(available.mean()),
            "imputed_signal_episodes": int(
                (available & predictions[list(contract["features"])].isna().any(axis=1)).sum()
            ),
            "unavailable_years": sorted(
                pd.to_datetime(predictions.loc[~available, "signal_close_date"])
                .dt.year.unique()
                .astype(int)
                .tolist()
            ),
        }
        diagnostics["scope_samples"][scope].update(coverage[scope])

    primary_complete = coverage["primary"]["unavailable_episodes"] == 0
    diagnostics["primary_gate"]["checks"]["all_primary_episodes_modeled"] = primary_complete
    diagnostics["primary_gate"]["metrics"]["model_coverage"] = coverage["primary"]
    diagnostics["primary_gate"]["passed"] = bool(
        all(diagnostics["primary_gate"]["checks"].values())
    )
    diagnostics["target_model_coverage"] = coverage
    diagnostics["target_feature_policy"] = (
        "retain_all_formal_state2_episodes_and_use_frozen_donor_median_imputer"
    )
    diagnostics["unavailable_episode_policy"] = (
        "retain_frozen_v4_2_75_percent_tqqq_without_synthetic_probability"
    )
    diagnostics["shadow_candidate_authorized"] = bool(
        diagnostics["donor_gate"]["passed"]
        and diagnostics["primary_gate"]["passed"]
        and diagnostics["contradiction_gate"]["passed"]
    )
    if not primary_complete:
        diagnostics["decision"] = "state2_cash_budget_primary_model_coverage_incomplete"
    elif diagnostics["shadow_candidate_authorized"]:
        diagnostics["decision"] = "state2_cash_budget_prospective_shadow_supported"
    elif not diagnostics["donor_gate"]["passed"]:
        diagnostics["decision"] = "donor_formal_state2_transfer_signal_not_stable"
    elif not diagnostics["primary_gate"]["passed"]:
        diagnostics["decision"] = "state2_cash_budget_does_not_beat_v4_2_primary_window"
    else:
        diagnostics["decision"] = "state2_cash_budget_blocked_by_later_contradiction"
    return (
        model,
        predictions_by_scope,
        headline_by_scope,
        results_by_scope,
        attribution_by_scope,
        diagnostics,
    )
