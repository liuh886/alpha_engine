"""Coverage-safe execution for the v4.13 state2-only transfer experiment.

A target calendar year can precede a usable two-class donor training sample.
Such episodes receive no synthetic probability and make no strategy change:
they are explicitly marked ``unavailable`` and retain the frozen v4.2 75%
TQQQ state-2 budget.  Primary shadow eligibility additionally requires that
every primary-window episode was genuinely modeled.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

import src.research.v4_2_donor_state2_sgov_tqqq as core
import src.research.v4_2_donor_state2_sgov_tqqq_runtime as base


def predict_target_episodes_with_coverage(
    target_episodes: pd.DataFrame,
    donor_episodes: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Predict when possible; otherwise retain an explicit unavailable row."""

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
        predicted["training_asset_count"] = int(
            training["underlying"].nunique()
        )
        usable = (
            len(training) >= 10
            and training["positive_episode_excess"].nunique() >= 2
        )
        if usable:
            model = core._fit_pipeline(training, features, contract)
            predicted["probability"] = model.predict_proba(
                validation[list(features)]
            )[:, 1]
            predicted["probability_available"] = True
        else:
            predicted["probability"] = -1.0
            predicted["probability_available"] = False
        rows.append(predicted)

    if not rows:
        raise ValueError("no target state-2 episode rows were produced")
    output = pd.concat(rows, ignore_index=True).sort_values(
        "execution_date"
    )
    low = float(contract["strategy_mapping"]["probability_low_below"])
    high = float(
        contract["strategy_mapping"]["probability_high_at_or_above"]
    )
    output["probability_bucket"] = "medium"
    output.loc[output["probability"].lt(low), "probability_bucket"] = "low"
    output.loc[output["probability"].ge(high), "probability_bucket"] = "high"
    output.loc[
        ~output["probability_available"], "probability_bucket"
    ] = "unavailable"
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
) -> tuple[Any, dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, Any], dict[str, pd.DataFrame], dict[str, Any]]:
    """Run the base target-safe runtime with explicit model availability."""

    original_predictor = base.predict_target_episodes_walk_forward
    original_weight = core._variant_tqqq_weight
    base.predict_target_episodes_walk_forward = (
        predict_target_episodes_with_coverage
    )
    core._variant_tqqq_weight = _coverage_safe_variant_weight
    try:
        result = base.run_donor_state2_sgov_tqqq(
            bars, bridge_contract, contract
        )
    finally:
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
            "unavailable_years": sorted(
                pd.to_datetime(
                    predictions.loc[~available, "signal_close_date"]
                ).dt.year.unique().astype(int).tolist()
            ),
        }
        diagnostics["scope_samples"][scope].update(coverage[scope])

    primary_complete = coverage["primary"]["unavailable_episodes"] == 0
    diagnostics["primary_gate"]["checks"][
        "all_primary_episodes_modeled"
    ] = primary_complete
    diagnostics["primary_gate"]["metrics"][
        "model_coverage"
    ] = coverage["primary"]
    diagnostics["primary_gate"]["passed"] = bool(
        all(diagnostics["primary_gate"]["checks"].values())
    )
    diagnostics["target_model_coverage"] = coverage
    diagnostics["unavailable_episode_policy"] = (
        "retain_frozen_v4_2_75_percent_tqqq_without_synthetic_probability"
    )
    diagnostics["shadow_candidate_authorized"] = bool(
        diagnostics["donor_gate"]["passed"]
        and diagnostics["primary_gate"]["passed"]
        and diagnostics["contradiction_gate"]["passed"]
    )
    if not primary_complete:
        diagnostics["decision"] = (
            "state2_cash_budget_primary_model_coverage_incomplete"
        )
    elif diagnostics["shadow_candidate_authorized"]:
        diagnostics["decision"] = (
            "state2_cash_budget_prospective_shadow_supported"
        )
    elif not diagnostics["donor_gate"]["passed"]:
        diagnostics["decision"] = (
            "donor_formal_state2_transfer_signal_not_stable"
        )
    elif not diagnostics["primary_gate"]["passed"]:
        diagnostics["decision"] = (
            "state2_cash_budget_does_not_beat_v4_2_primary_window"
        )
    else:
        diagnostics["decision"] = (
            "state2_cash_budget_blocked_by_later_contradiction"
        )
    return (
        model,
        predictions_by_scope,
        headline_by_scope,
        results_by_scope,
        attribution_by_scope,
        diagnostics,
    )
