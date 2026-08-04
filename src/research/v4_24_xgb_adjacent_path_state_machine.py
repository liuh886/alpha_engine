"""Governed v4.24 XGBoost adjacent path-utility state-machine study."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.v4_24_xgb_adjacent_path_data import (
    STATE_ORDER,
    build_path_utility_frame,
)
from src.research.v4_24_xgb_adjacent_path_model import (
    edge_metrics,
    importance_metrics,
    placebo_metrics,
    score_actual,
    score_outer_folds,
    select_ordinal_state,
    selection_metrics,
)
from src.research.v4_24_xgb_adjacent_path_policy import (
    actual_gate,
    phase2_evidence,
    phase2_gate,
)


@dataclass(frozen=True)
class AdjacentPathUtilityResult:
    proxy_frame: pd.DataFrame
    actual_frame: pd.DataFrame
    feature_names: tuple[str, ...]
    fold_coverage: pd.DataFrame
    oof_scores: pd.DataFrame
    actual_scores: pd.DataFrame
    edge_summary: pd.DataFrame
    edge_by_fold: pd.DataFrame
    oof_selected: pd.DataFrame
    actual_selected: pd.DataFrame
    selection_by_fold: pd.DataFrame
    selection_by_state: pd.DataFrame
    concentration: pd.DataFrame
    placebo: pd.DataFrame
    feature_importance: pd.DataFrame
    family_importance: pd.DataFrame
    phase1_gate: dict[str, Any]
    oof_headline: pd.DataFrame
    actual_headline: pd.DataFrame
    oof_daily: dict[str, pd.DataFrame]
    actual_daily: dict[str, pd.DataFrame]
    oof_trades: dict[str, pd.DataFrame]
    actual_trades: dict[str, pd.DataFrame]
    phase2_gate: dict[str, Any]
    actual_contradiction_gate: dict[str, Any]
    final_gate: dict[str, Any]


def _phase1_gate(
    edge_summary: pd.DataFrame,
    selected: pd.DataFrame,
    selection_by_fold: pd.DataFrame,
    selection_by_state: pd.DataFrame,
    concentration: pd.DataFrame,
    placebo: pd.DataFrame,
    feature_importance: pd.DataFrame,
    family_importance: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    gate = contract["validation"]["phase1"]
    selected_regret = float(selected["selected_utility_regret"].mean())
    baseline_regret = float(selected["baseline_utility_regret"].mean())
    regret_reduction = (
        1.0 - selected_regret / baseline_regret
        if baseline_regret > 1e-12
        else np.nan
    )
    mean_auc = float(edge_summary["roc_auc"].mean())
    minimum_auc = float(edge_summary["roc_auc"].min())
    mean_balanced = float(edge_summary["balanced_accuracy"].mean())
    median_advantage = float(
        selected["selected_utility_advantage_vs_v4_2"].median()
    )
    positive_folds = int(
        selection_by_fold["total_utility_advantage_vs_v4_2"].gt(0.0).sum()
    )
    top_two_rate = float(selected["selected_top_two"].mean())
    minimum_state_count = int(selection_by_state["selected_groups"].min())
    maximum_state_share = float(selection_by_state["selection_share"].max())
    concentration_row = concentration.iloc[0]
    placebo_beat_rate = float(placebo["observed_beats_placebo"].mean())
    largest_feature = float(feature_importance["shap_share"].max())
    largest_family = float(family_importance["shap_share"].max())
    checks = {
        "mean_edge_auc": mean_auc >= float(gate["mean_edge_auc_min"]),
        "minimum_edge_auc": minimum_auc >= float(gate["minimum_edge_auc_min"]),
        "mean_balanced_accuracy": mean_balanced
        >= float(gate["mean_balanced_accuracy_min"]),
        "utility_regret_reduction": regret_reduction
        >= float(gate["utility_regret_reduction_min"]),
        "median_utility_advantage": median_advantage
        > float(gate["median_utility_advantage_min"]),
        "positive_outer_folds": positive_folds
        >= int(gate["positive_outer_folds_min"]),
        "top_two_rate": top_two_rate >= float(gate["top_two_rate_min"]),
        "minimum_state_selections": minimum_state_count
        >= int(gate["minimum_state_selections"]),
        "maximum_state_selection_share": maximum_state_share
        <= float(gate["maximum_state_selection_share"]),
        "year_concentration": float(
            concentration_row["largest_positive_year_share"]
        )
        <= float(gate["largest_positive_year_share_max"]),
        "cluster_concentration": float(
            concentration_row["largest_positive_cluster_share"]
        )
        <= float(gate["largest_positive_cluster_share_max"]),
        "without_best_year": float(
            concentration_row["advantage_without_best_year"]
        )
        > 0.0,
        "without_best_cluster": float(
            concentration_row["advantage_without_best_cluster"]
        )
        > 0.0,
        "placebo": placebo_beat_rate >= float(gate["placebo_beat_rate_min"]),
        "single_feature_concentration": largest_feature
        <= float(gate["largest_single_feature_shap_share_max"]),
        "feature_family_concentration": largest_family
        <= float(gate["largest_feature_family_shap_share_max"]),
    }
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "mean_edge_auc": mean_auc,
        "minimum_edge_auc": minimum_auc,
        "mean_balanced_accuracy": mean_balanced,
        "selected_mean_utility_regret": selected_regret,
        "baseline_mean_utility_regret": baseline_regret,
        "utility_regret_reduction": regret_reduction,
        "median_utility_advantage_vs_v4_2": median_advantage,
        "total_utility_advantage_vs_v4_2": float(
            selected["selected_utility_advantage_vs_v4_2"].sum()
        ),
        "positive_outer_folds": positive_folds,
        "top_two_rate": top_two_rate,
        "minimum_state_selections": minimum_state_count,
        "maximum_state_selection_share": maximum_state_share,
        "placebo_beat_rate": placebo_beat_rate,
        "largest_single_feature_shap_share": largest_feature,
        "largest_feature_family_shap_share": largest_family,
    }


def run_adjacent_path_utility_study(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
) -> AdjacentPathUtilityResult:
    proxy, feature_names = build_path_utility_frame(
        bars,
        proxy_baseline_daily,
        contract,
        v416_contract,
        actual=False,
    )
    actual, actual_features = build_path_utility_frame(
        bars,
        actual_baseline_daily,
        contract,
        v416_contract,
        actual=True,
    )
    if feature_names != actual_features:
        raise AssertionError("proxy and actual feature schemas diverged")
    actual_start = pd.Timestamp(contract["data"]["actual_product_start"])
    actual = actual.loc[actual["decision_date"].ge(actual_start)].copy()
    if actual.empty:
        raise ValueError("actual 2024+ path-utility frame is empty")

    oof_scores, fold_coverage, bundles = score_outer_folds(
        proxy, feature_names, contract
    )
    edge_summary, edge_by_fold = edge_metrics(oof_scores)
    oof_selected = select_ordinal_state(oof_scores, contract)
    selection_by_fold, selection_by_state, concentration = selection_metrics(
        oof_selected, contract
    )
    selected_regret = float(oof_selected["selected_utility_regret"].mean())
    baseline_regret = float(oof_selected["baseline_utility_regret"].mean())
    observed_reduction = (
        1.0 - selected_regret / baseline_regret
        if baseline_regret > 1e-12
        else np.nan
    )
    placebo = placebo_metrics(
        proxy, feature_names, contract, observed_reduction
    )
    feature_importance, family_importance = importance_metrics(
        bundles, feature_names, contract
    )
    phase1 = _phase1_gate(
        edge_summary,
        oof_selected,
        selection_by_fold,
        selection_by_state,
        concentration,
        placebo,
        feature_importance,
        family_importance,
        contract,
    )

    training = proxy.loc[
        proxy["decision_date"].le(pd.Timestamp("2023-12-29"))
    ].copy()
    actual_scores, _ = score_actual(
        training, actual, feature_names, contract
    )
    actual_selected = select_ordinal_state(actual_scores, contract)

    empty_headline = pd.DataFrame()
    empty_frames: dict[str, pd.DataFrame] = {}
    if not phase1["passed"]:
        phase2 = {
            "passed": False,
            "skipped": True,
            "reason": "phase1_gate_failed",
        }
        actual_contradiction = {
            "passed": False,
            "skipped": True,
            "reason": "phase2_not_authorized",
        }
        oof_headline = empty_headline
        actual_headline = empty_headline
        oof_daily = empty_frames
        actual_daily = empty_frames
        oof_trades = empty_frames
        actual_trades = empty_frames
    else:
        (
            oof_headline,
            oof_daily,
            oof_trades,
            oof_results,
        ) = phase2_evidence(
            oof_selected,
            bars,
            proxy_baseline_daily,
            contract,
            actual=False,
        )
        phase2 = phase2_gate(
            oof_headline,
            oof_results,
            oof_selected,
            concentration.iloc[0],
            contract,
        )
        if not phase2["passed"]:
            actual_headline = empty_headline
            actual_daily = empty_frames
            actual_trades = empty_frames
            actual_contradiction = {
                "passed": False,
                "skipped": True,
                "reason": "phase2_gate_failed",
            }
        else:
            (
                actual_headline,
                actual_daily,
                actual_trades,
                _,
            ) = phase2_evidence(
                actual_selected,
                bars,
                actual_baseline_daily,
                contract,
                actual=True,
            )
            actual_contradiction = actual_gate(actual_headline, contract)

    prospective = bool(
        phase1["passed"]
        and phase2["passed"]
        and actual_contradiction["passed"]
    )
    final_gate = {
        "passed": prospective,
        "prospective_shadow_authorized": prospective,
        "direct_promotion_authorized": False,
        "v4_2_unchanged": True,
        "telegram_unchanged": True,
        "issue_348_unchanged": True,
    }
    return AdjacentPathUtilityResult(
        proxy_frame=proxy,
        actual_frame=actual,
        feature_names=feature_names,
        fold_coverage=fold_coverage,
        oof_scores=oof_scores,
        actual_scores=actual_scores,
        edge_summary=edge_summary,
        edge_by_fold=edge_by_fold,
        oof_selected=oof_selected,
        actual_selected=actual_selected,
        selection_by_fold=selection_by_fold,
        selection_by_state=selection_by_state,
        concentration=concentration,
        placebo=placebo,
        feature_importance=feature_importance,
        family_importance=family_importance,
        phase1_gate=phase1,
        oof_headline=oof_headline,
        actual_headline=actual_headline,
        oof_daily=oof_daily,
        actual_daily=actual_daily,
        oof_trades=oof_trades,
        actual_trades=actual_trades,
        phase2_gate=phase2,
        actual_contradiction_gate=actual_contradiction,
        final_gate=final_gate,
    )
