"""Governed XGBoost LambdaRank ten-session allocation state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from src.research.v4_23_xgb_lambdarank_data import build_group_frame
from src.research.v4_23_xgb_lambdarank_model import (
    concentration_metrics,
    embargo_train_end,
    fit_ranker,
    importance_metrics,
    phase1_gate,
    placebo_metrics,
    predict,
    ranking_metrics,
    score_outer_folds,
    select_from_scores,
)
from src.research.v4_23_xgb_lambdarank_policy import (
    actual_gate,
    phase2_evidence,
    phase2_gate,
)


@dataclass(frozen=True)
class XGBStateMachineResult:
    proxy_group_frame: pd.DataFrame
    actual_group_frame: pd.DataFrame
    fold_coverage: pd.DataFrame
    oof_scores: pd.DataFrame
    actual_scores: pd.DataFrame
    ranking_by_fold: pd.DataFrame
    ranking_by_action: pd.DataFrame
    placebo_metrics: pd.DataFrame
    feature_importance: pd.DataFrame
    shap_importance: pd.DataFrame
    concentration_metrics: pd.DataFrame
    phase1_gate: dict[str, Any]
    oof_selected_blocks: pd.DataFrame
    actual_selected_blocks: pd.DataFrame
    oof_headline: pd.DataFrame
    actual_headline: pd.DataFrame
    oof_daily: dict[str, pd.DataFrame]
    actual_daily: dict[str, pd.DataFrame]
    oof_trades: dict[str, pd.DataFrame]
    actual_trades: dict[str, pd.DataFrame]
    phase2_gate: dict[str, Any]
    actual_contradiction_gate: dict[str, Any]
    final_gate: dict[str, Any]


def run_xgb_lambdarank_state_machine(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
) -> XGBStateMachineResult:
    proxy, feature_names = build_group_frame(
        bars,
        proxy_baseline_daily,
        contract,
        v416_contract,
        actual=False,
    )
    actual, actual_feature_names = build_group_frame(
        bars,
        actual_baseline_daily,
        contract,
        v416_contract,
        actual=True,
    )
    if feature_names != actual_feature_names:
        raise AssertionError("proxy and actual model schemas diverged")

    oof_scores, coverage, bundles = score_outer_folds(
        proxy, feature_names, contract
    )
    selected, by_fold, by_action = ranking_metrics(oof_scores)
    concentration = concentration_metrics(selected, contract)
    gain, shap = importance_metrics(bundles, feature_names, contract)
    observed_ndcg = float(selected["selected_ndcg_at_1"].mean())
    placebo = placebo_metrics(proxy, feature_names, contract, observed_ndcg)
    ranking_gate = phase1_gate(
        selected,
        by_fold,
        by_action,
        placebo,
        shap,
        concentration,
        contract,
    )

    unique_dates = pd.DatetimeIndex(
        sorted(pd.to_datetime(proxy["decision_date"].unique()))
    )
    actual_start = pd.Timestamp(contract["data"]["actual_product_start"])
    training_end = embargo_train_end(
        unique_dates,
        actual_start,
        pd.Timestamp("2023-12-29"),
        int(contract["decision"]["embargo_sessions"]),
    )
    actual_training = proxy.loc[proxy["decision_date"].le(training_end)].copy()
    actual_scores = actual.loc[actual["decision_date"].ge(actual_start)].copy()
    actual_bundle = fit_ranker(actual_training, feature_names, contract)
    actual_scores["score"] = predict(actual_bundle, actual_scores)
    actual_scores["fold"] = "actual_2024_plus"
    actual_selected = select_from_scores(actual_scores)

    if bool(ranking_gate["passed"]):
        oof_headline, oof_daily, oof_trades, oof_results = phase2_evidence(
            selected,
            bars,
            proxy_baseline_daily,
            contract,
            actual=False,
        )
        actual_headline, actual_daily, actual_trades, _ = phase2_evidence(
            actual_selected,
            bars,
            actual_baseline_daily,
            contract,
            actual=True,
        )
        policy_gate = phase2_gate(
            oof_headline, oof_results, selected, contract
        )
        contradiction_gate = actual_gate(actual_headline, contract)
    else:
        oof_headline = pd.DataFrame()
        actual_headline = pd.DataFrame()
        oof_daily = {}
        actual_daily = {}
        oof_trades = {}
        actual_trades = {}
        policy_gate = {"passed": False, "skipped": True, "checks": {}}
        contradiction_gate = {
            "passed": False,
            "skipped": True,
            "checks": {},
        }

    final = {
        "passed": bool(
            ranking_gate["passed"]
            and policy_gate["passed"]
            and contradiction_gate["passed"]
        ),
        "checks": {
            "phase1_ranking_gate": bool(ranking_gate["passed"]),
            "phase2_policy_gate": bool(policy_gate["passed"]),
            "actual_contradiction_gate": bool(contradiction_gate["passed"]),
        },
        "prospective_shadow_authorized": bool(
            ranking_gate["passed"]
            and policy_gate["passed"]
            and contradiction_gate["passed"]
        ),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return XGBStateMachineResult(
        proxy_group_frame=proxy,
        actual_group_frame=actual,
        fold_coverage=coverage,
        oof_scores=oof_scores,
        actual_scores=actual_scores,
        ranking_by_fold=by_fold,
        ranking_by_action=by_action,
        placebo_metrics=placebo,
        feature_importance=gain,
        shap_importance=shap,
        concentration_metrics=concentration,
        phase1_gate=ranking_gate,
        oof_selected_blocks=selected,
        actual_selected_blocks=actual_selected,
        oof_headline=oof_headline,
        actual_headline=actual_headline,
        oof_daily=oof_daily,
        actual_daily=actual_daily,
        oof_trades=oof_trades,
        actual_trades=actual_trades,
        phase2_gate=policy_gate,
        actual_contradiction_gate=contradiction_gate,
        final_gate=final,
    )
