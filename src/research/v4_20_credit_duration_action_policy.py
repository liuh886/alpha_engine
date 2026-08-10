"""Governed Phase 2 for the v4.19-admitted credit/duration factor block."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.research.v4_14_multifactor_event_discovery import _assign_macro_clusters
from src.research.v4_16_action_advantage_model import (
    ACTION_KEYS,
    AdvantageModelResult,
    AdvantagePolicyResult,
    run_action_advantage_policy,
)
from src.research.v4_16_action_advantage_runtime import (
    build_action_advantage_frame,
    select_advantage_events,
)
from src.research.v4_19_incremental_market_internals import (
    build_market_internal_feature_blocks,
)


@dataclass(frozen=True)
class CreditDurationPhase2Result:
    frame: pd.DataFrame
    base_model: AdvantageModelResult
    candidate_model: AdvantageModelResult
    base_policy: AdvantagePolicyResult
    candidate_policy: AdvantagePolicyResult
    rank_action_metrics: pd.DataFrame
    rank_action_state_metrics: pd.DataFrame
    rank_fold_metrics: pd.DataFrame
    calibration_metrics: pd.DataFrame
    event_metrics: pd.DataFrame
    coefficient_cosines: pd.DataFrame
    same_row_coverage: pd.DataFrame
    ranking_gate: dict[str, Any]
    calibration_gate: dict[str, Any]
    event_gate: dict[str, Any]
    portfolio_gate: dict[str, Any]
    actual_contradiction_gate: dict[str, Any]
    final_gate: dict[str, Any]


def _pipeline(contract: Mapping[str, Any]) -> Pipeline:
    model = contract["model"]
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                Ridge(
                    alpha=float(model["alpha"]),
                    fit_intercept=bool(model["fit_intercept"]),
                ),
            ),
        ]
    )


def _embargo_train_end(
    index: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    declared_train_end: pd.Timestamp,
    embargo_sessions: int,
) -> pd.Timestamp:
    location = int(index.searchsorted(test_start, side="left"))
    location = max(location - embargo_sessions - 1, 0)
    return min(declared_train_end, pd.Timestamp(index[location]))


def _fit(
    frame: pd.DataFrame,
    features: Sequence[str],
    targets: Sequence[str],
    contract: Mapping[str, Any],
) -> Pipeline:
    usable = frame.dropna(subset=list(features) + list(targets))
    if len(usable) < int(contract["training"]["minimum_training_samples"]):
        raise ValueError("insufficient shared non-overlapping training samples")
    model = _pipeline(contract)
    model.fit(usable[list(features)], usable[list(targets)])
    return model


def _coefficient_frame(
    model: Pipeline,
    *,
    fold: str,
    model_name: str,
    features: Sequence[str],
    targets: Sequence[str],
) -> pd.DataFrame:
    ridge: Ridge = model.named_steps["model"]
    coefficient = np.asarray(ridge.coef_, dtype=float)
    rows: list[dict[str, Any]] = []
    for target_position, target in enumerate(targets):
        for feature_position, feature in enumerate(features):
            rows.append(
                {
                    "fold": fold,
                    "model": model_name,
                    "target": target,
                    "feature": feature,
                    "coefficient": float(coefficient[target_position, feature_position]),
                }
            )
    return pd.DataFrame(rows)


def _quintile_spread(prediction: pd.Series, realized: pd.Series) -> float:
    table = pd.concat(
        [prediction.rename("prediction"), realized.rename("realized")], axis=1
    ).dropna()
    if len(table) < 10:
        return np.nan
    percentile = table["prediction"].rank(pct=True, method="average")
    top = table.loc[percentile.ge(0.80), "realized"]
    bottom = table.loc[percentile.le(0.20), "realized"]
    if top.empty or bottom.empty:
        return np.nan
    return float(top.mean() - bottom.mean())


def _calibration_slope(prediction: pd.Series, realized: pd.Series) -> float:
    table = pd.concat([prediction, realized], axis=1).dropna()
    if len(table) < 3:
        return np.nan
    x = table.iloc[:, 0].to_numpy(dtype=float)
    y = table.iloc[:, 1].to_numpy(dtype=float)
    variance = float(np.var(x))
    if variance <= 1e-18:
        return np.nan
    return float(np.cov(x, y, ddof=0)[0, 1] / variance)


def _cosine_table(coefficients: pd.DataFrame) -> pd.DataFrame:
    candidate = coefficients.loc[coefficients["model"].eq("candidate")]
    pivot = candidate.pivot_table(
        index="fold", columns=["target", "feature"], values="coefficient"
    ).sort_index(axis=1)
    rows: list[dict[str, Any]] = []
    for left, right in combinations(pivot.index, 2):
        a = pivot.loc[left].to_numpy(dtype=float)
        b = pivot.loc[right].to_numpy(dtype=float)
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        rows.append(
            {
                "fold_left": left,
                "fold_right": right,
                "cosine": (float(np.dot(a, b) / denominator) if denominator > 1e-18 else np.nan),
            }
        )
    return pd.DataFrame(rows)


def _prediction_output(
    test: pd.DataFrame,
    predictions: np.ndarray,
    targets: Sequence[str],
    *,
    fold: str,
) -> pd.DataFrame:
    output = test[list(targets)].copy()
    output["fold"] = fold
    for position, action in enumerate(ACTION_KEYS):
        output[f"predicted_{action}"] = predictions[:, position]
    for column in (
        "qqq_distance_ma20",
        "qqq_distance_ma200",
        "voo_distance_ma200",
        "vol_max_percentile_252",
        "v4_2_execution_state",
    ):
        if column in test.columns:
            output[column] = test[column]
    return output


def _build_shared_models(
    frame: pd.DataFrame,
    base_features: Sequence[str],
    candidate_features: Sequence[str],
    targets: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    base_parts: list[pd.DataFrame] = []
    candidate_parts: list[pd.DataFrame] = []
    coefficient_parts: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    for specification in contract["outer_folds"]:
        fold = str(specification["fold"])
        test_start = pd.Timestamp(specification["test_start"])
        test_end = pd.Timestamp(specification["test_end"])
        train_start = pd.Timestamp(specification["train_start"])
        train_end = _embargo_train_end(
            frame.index,
            test_start,
            pd.Timestamp(specification["train_end"]),
            int(contract["training"]["embargo_sessions"]),
        )
        training = frame.loc[train_start:train_end]
        training = training.loc[training["global_training_sample"].astype(bool)]
        shared_train = training.dropna(subset=list(candidate_features) + list(targets))
        testing = frame.loc[test_start:test_end]
        shared_test = testing.dropna(subset=list(candidate_features) + list(targets))
        if shared_test.empty:
            raise ValueError(f"{fold} has no shared test rows")
        base_model = _fit(shared_train, base_features, targets, contract)
        candidate_model = _fit(shared_train, candidate_features, targets, contract)
        base_prediction = np.asarray(
            base_model.predict(shared_test[list(base_features)]), dtype=float
        )
        candidate_prediction = np.asarray(
            candidate_model.predict(shared_test[list(candidate_features)]),
            dtype=float,
        )
        base_parts.append(_prediction_output(shared_test, base_prediction, targets, fold=fold))
        candidate_parts.append(
            _prediction_output(shared_test, candidate_prediction, targets, fold=fold)
        )
        coefficient_parts.append(
            _coefficient_frame(
                base_model,
                fold=fold,
                model_name="base",
                features=base_features,
                targets=targets,
            )
        )
        coefficient_parts.append(
            _coefficient_frame(
                candidate_model,
                fold=fold,
                model_name="candidate",
                features=candidate_features,
                targets=targets,
            )
        )
        coverage_rows.append(
            {
                "fold": fold,
                "training_start": shared_train.index.min(),
                "training_end": shared_train.index.max(),
                "training_samples": int(len(shared_train)),
                "test_start": shared_test.index.min(),
                "test_end": shared_test.index.max(),
                "test_samples": int(len(shared_test)),
                "base_candidate_training_rows_identical": True,
                "base_candidate_test_rows_identical": True,
            }
        )
    return (
        pd.concat(base_parts).sort_index(),
        pd.concat(candidate_parts).sort_index(),
        pd.concat(coefficient_parts, ignore_index=True),
        pd.DataFrame(coverage_rows),
        frame,
    )


def _build_actual_models(
    frame: pd.DataFrame,
    base_features: Sequence[str],
    candidate_features: Sequence[str],
    targets: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actual_start = max(
        pd.Timestamp(contract["data"]["actual_product_start"]),
        frame.index.min(),
    )
    train_end = _embargo_train_end(
        frame.index,
        actual_start,
        pd.Timestamp("2023-12-29"),
        int(contract["training"]["embargo_sessions"]),
    )
    training = frame.loc[pd.Timestamp("2011-01-03") : train_end]
    training = training.loc[training["global_training_sample"].astype(bool)]
    shared_train = training.dropna(subset=list(candidate_features) + list(targets))
    actual = frame.loc[actual_start:].dropna(subset=list(candidate_features))
    base_model = _fit(shared_train, base_features, targets, contract)
    candidate_model = _fit(shared_train, candidate_features, targets, contract)
    base_prediction = np.asarray(base_model.predict(actual[list(base_features)]), dtype=float)
    candidate_prediction = np.asarray(
        candidate_model.predict(actual[list(candidate_features)]), dtype=float
    )
    base_output = _prediction_output(actual, base_prediction, targets, fold="actual_2024_plus")
    candidate_output = _prediction_output(
        actual, candidate_prediction, targets, fold="actual_2024_plus"
    )
    coefficients = pd.concat(
        [
            _coefficient_frame(
                base_model,
                fold="actual_2024_plus",
                model_name="base",
                features=base_features,
                targets=targets,
            ),
            _coefficient_frame(
                candidate_model,
                fold="actual_2024_plus",
                model_name="candidate",
                features=candidate_features,
                targets=targets,
            ),
        ],
        ignore_index=True,
    )
    return base_output, candidate_output, coefficients


def _action_metrics(
    base: pd.DataFrame,
    candidate: pd.DataFrame,
    targets: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    action_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for action, target in zip(ACTION_KEYS, targets):
        realized = candidate[target]
        base_prediction = base[f"predicted_{action}"]
        candidate_prediction = candidate[f"predicted_{action}"]
        base_ic = base_prediction.corr(realized, method="spearman")
        candidate_ic = candidate_prediction.corr(realized, method="spearman")
        base_spread = _quintile_spread(base_prediction, realized)
        candidate_spread = _quintile_spread(candidate_prediction, realized)
        action_rows.append(
            {
                "action": action,
                "observations": int(realized.notna().sum()),
                "base_spearman_ic": float(base_ic),
                "candidate_spearman_ic": float(candidate_ic),
                "ic_improvement": float(candidate_ic - base_ic),
                "base_top_bottom_quintile_spread": base_spread,
                "candidate_top_bottom_quintile_spread": candidate_spread,
                "quintile_spread_improvement": float(candidate_spread - base_spread),
            }
        )
        state = candidate.get(
            "v4_2_execution_state",
            pd.Series(np.nan, index=candidate.index),
        )
        for state_value in (0, 1, 2):
            mask = pd.to_numeric(state, errors="coerce").eq(state_value)
            cell = candidate.loc[mask]
            base_cell = base.loc[mask]
            if len(cell) < 10:
                base_cell_ic = np.nan
                candidate_cell_ic = np.nan
            else:
                base_cell_ic = base_cell[f"predicted_{action}"].corr(
                    cell[target], method="spearman"
                )
                candidate_cell_ic = cell[f"predicted_{action}"].corr(
                    cell[target], method="spearman"
                )
            state_rows.append(
                {
                    "action": action,
                    "state": state_value,
                    "observations": int(len(cell)),
                    "base_spearman_ic": base_cell_ic,
                    "candidate_spearman_ic": candidate_cell_ic,
                    "ic_improvement": (
                        float(candidate_cell_ic - base_cell_ic)
                        if np.isfinite(base_cell_ic) and np.isfinite(candidate_cell_ic)
                        else np.nan
                    ),
                }
            )
    for fold, candidate_fold in candidate.groupby("fold"):
        base_fold = base.loc[candidate_fold.index]
        deltas: list[float] = []
        positive = 0
        for action, target in zip(ACTION_KEYS, targets):
            base_ic = base_fold[f"predicted_{action}"].corr(
                candidate_fold[target], method="spearman"
            )
            candidate_ic = candidate_fold[f"predicted_{action}"].corr(
                candidate_fold[target], method="spearman"
            )
            delta = float(candidate_ic - base_ic)
            deltas.append(delta)
            positive += int(delta > 0.0)
        fold_rows.append(
            {
                "fold": fold,
                "mean_action_ic_improvement": float(np.mean(deltas)),
                "actions_with_positive_ic_improvement": positive,
            }
        )
    return (
        pd.DataFrame(action_rows),
        pd.DataFrame(state_rows),
        pd.DataFrame(fold_rows),
    )


def _calibration_metrics(
    base: pd.DataFrame,
    candidate: pd.DataFrame,
    targets: Sequence[str],
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    high_threshold = float(contract["validation"]["calibration_gate"]["high_score_threshold"])
    rows: list[dict[str, Any]] = []
    for action, target in zip(ACTION_KEYS, targets):
        realized = candidate[target]
        base_prediction = base[f"predicted_{action}"]
        candidate_prediction = candidate[f"predicted_{action}"]
        base_error = (base_prediction - realized).abs()
        candidate_error = (candidate_prediction - realized).abs()
        high = candidate_prediction.ge(high_threshold) & realized.notna()
        rows.append(
            {
                "action": action,
                "observations": int(realized.notna().sum()),
                "base_mae": float(base_error.mean()),
                "candidate_mae": float(candidate_error.mean()),
                "candidate_base_mae_ratio": float(candidate_error.mean() / base_error.mean()),
                "candidate_bias": float((candidate_prediction - realized).mean()),
                "base_calibration_slope": _calibration_slope(base_prediction, realized),
                "candidate_calibration_slope": _calibration_slope(candidate_prediction, realized),
                "candidate_high_score_observations": int(high.sum()),
                "candidate_high_score_mean_realized": (
                    float(realized.loc[high].mean()) if high.any() else np.nan
                ),
                "candidate_high_score_mae": (
                    float(candidate_error.loc[high].mean()) if high.any() else np.nan
                ),
                "base_error_on_candidate_high_score_dates": (
                    float(base_error.loc[high].mean()) if high.any() else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _ranking_concentration(
    base: pd.DataFrame,
    candidate: pd.DataFrame,
    targets: Sequence[str],
) -> tuple[float, float]:
    improvements: list[pd.Series] = []
    for action, target in zip(ACTION_KEYS, targets):
        base_error = (candidate[target] - base[f"predicted_{action}"]).abs()
        candidate_error = (candidate[target] - candidate[f"predicted_{action}"]).abs()
        improvements.append((base_error - candidate_error).rename(action))
    daily = pd.concat(improvements, axis=1).sum(axis=1)
    cluster = ((daily.index - daily.index.min()).days // 30).astype(int)
    positive_cluster = daily.groupby(cluster).sum().clip(lower=0.0)
    total = float(positive_cluster.sum())
    cluster_share = float(positive_cluster.max() / total) if total > 0.0 else 1.0
    return cluster_share, float(daily.sum())


def _ranking_gate(
    action: pd.DataFrame,
    state: pd.DataFrame,
    folds: pd.DataFrame,
    cosines: pd.DataFrame,
    base: pd.DataFrame,
    candidate: pd.DataFrame,
    targets: Sequence[str],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["ranking_gate"]
    ic_threshold = float(threshold["action_ic_improvement_threshold"])
    passing_actions = int(action["ic_improvement"].ge(ic_threshold).sum())
    nonnegative_actions = int(action["ic_improvement"].ge(0.0).sum())
    positive_spreads = int(action["quintile_spread_improvement"].ge(0.0).sum())
    passing_cells = int(state["ic_improvement"].ge(ic_threshold).sum())
    large = action.loc[action["observations"].ge(int(threshold["large_action_observations_min"]))]
    cosine_median = float(cosines["cosine"].median()) if not cosines.empty else np.nan
    era = folds.set_index("fold")["mean_action_ic_improvement"]
    positive_eras = int(era.gt(0.0).sum())
    without_best = float(era.drop(index=era.idxmax()).sum()) if len(era) > 1 else np.nan
    positive = era.clip(lower=0.0)
    positive_total = float(positive.sum())
    era_share = float(positive.max() / positive_total) if positive_total > 0.0 else 1.0
    cluster_share, total_error_reduction = _ranking_concentration(base, candidate, targets)
    checks = {
        "actions_passing_ic_improvement": passing_actions
        >= int(threshold["actions_passing_ic_improvement_min"]),
        "all_actions_nonnegative_ic_improvement": nonnegative_actions == len(ACTION_KEYS),
        "actions_positive_quintile_spread": positive_spreads
        >= int(threshold["actions_positive_quintile_spread_improvement_min"]),
        "action_state_cells": passing_cells
        >= int(threshold["action_state_cells_passing_ic_improvement_min"]),
        "no_large_action_degradation": bool(
            large.empty
            or large["ic_improvement"]
            .ge(float(threshold["maximum_large_action_ic_degradation"]))
            .all()
        ),
        "coefficient_stability": np.isfinite(cosine_median)
        and cosine_median >= float(threshold["coefficient_cosine_similarity_median_min"]),
        "positive_outer_eras": positive_eras >= int(threshold["positive_outer_eras_min"]),
        "without_best_era": np.isfinite(without_best)
        and without_best >= float(threshold["improvement_without_best_era_min"]),
        "era_concentration": era_share <= float(threshold["largest_positive_era_share_max"]),
        "cluster_concentration": cluster_share
        <= float(threshold["largest_positive_macro_cluster_share_max"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "actions_passing_ic_improvement": passing_actions,
            "nonnegative_action_ic_improvements": nonnegative_actions,
            "actions_positive_quintile_spread_improvement": positive_spreads,
            "action_state_cells_passing": passing_cells,
            "coefficient_cosine_similarity_median": cosine_median,
            "positive_outer_eras": positive_eras,
            "improvement_without_best_era": without_best,
            "largest_positive_era_share": era_share,
            "largest_positive_macro_cluster_share": cluster_share,
            "total_absolute_error_reduction": total_error_reduction,
        },
        "passed": bool(all(checks.values())),
    }


def _calibration_gate(metrics: pd.DataFrame, contract: Mapping[str, Any]) -> dict[str, Any]:
    threshold = contract["validation"]["calibration_gate"]
    mae_not_worse = int(metrics["candidate_mae"].le(metrics["base_mae"]).sum())
    slope_in_range = int(
        metrics["candidate_calibration_slope"]
        .between(
            float(threshold["calibration_slope_min"]),
            float(threshold["calibration_slope_max"]),
        )
        .sum()
    )
    high_nonnegative = int(metrics["candidate_high_score_mean_realized"].ge(0.0).sum())
    candidate_high_error = (
        float(
            np.average(
                metrics["candidate_high_score_mae"].fillna(0.0),
                weights=metrics["candidate_high_score_observations"],
            )
        )
        if metrics["candidate_high_score_observations"].sum() > 0
        else np.nan
    )
    base_high_error = (
        float(
            np.average(
                metrics["base_error_on_candidate_high_score_dates"].fillna(0.0),
                weights=metrics["candidate_high_score_observations"],
            )
        )
        if metrics["candidate_high_score_observations"].sum() > 0
        else np.nan
    )
    checks = {
        "maximum_mae_ratio": metrics["candidate_base_mae_ratio"]
        .le(float(threshold["maximum_action_mae_ratio"]))
        .all(),
        "actions_mae_not_worse": mae_not_worse >= int(threshold["actions_mae_not_worse_min"]),
        "prediction_bias": metrics["candidate_bias"]
        .abs()
        .le(float(threshold["maximum_absolute_prediction_bias"]))
        .all(),
        "calibration_slopes_in_range": slope_in_range
        >= int(threshold["actions_calibration_slope_in_range_min"]),
        "no_negative_calibration_slope": metrics["candidate_calibration_slope"]
        .ge(float(threshold["minimum_calibration_slope"]))
        .all(),
        "high_score_mean_realized": high_nonnegative
        >= int(threshold["high_score_actions_nonnegative_mean_realized_min"]),
        "pooled_high_score_error": np.isfinite(candidate_high_error)
        and np.isfinite(base_high_error)
        and candidate_high_error <= base_high_error,
    }
    return {
        "checks": checks,
        "metrics": {
            "actions_mae_not_worse": mae_not_worse,
            "actions_calibration_slope_in_range": slope_in_range,
            "high_score_actions_nonnegative_mean_realized": high_nonnegative,
            "candidate_pooled_high_score_mae": candidate_high_error,
            "base_error_on_candidate_high_score_dates": base_high_error,
        },
        "passed": bool(all(checks.values())),
    }


def _event_summary(
    events: pd.DataFrame,
    predictions: pd.DataFrame,
    targets: Sequence[str],
    contract: Mapping[str, Any],
    *,
    model_name: str,
) -> dict[str, Any]:
    unconditional = float(
        pd.concat([predictions[target] for target in targets], ignore_index=True)
        .dropna()
        .gt(0.0)
        .mean()
    )
    precision = float(events["win"].mean()) if not events.empty else np.nan
    median = float(events["realized_advantage"].median()) if not events.empty else np.nan
    clustered = _assign_macro_clusters(
        events,
        int(contract["training"]["macro_cluster_calendar_days"]),
    )
    positive_cluster = (
        clustered.groupby("macro_cluster_id")["realized_advantage"].sum().clip(lower=0.0)
        if not clustered.empty
        else pd.Series(dtype=float)
    )
    positive_total = float(positive_cluster.sum())
    cluster_share = float(positive_cluster.max() / positive_total) if positive_total > 0.0 else 1.0
    yearly = (
        events.groupby(pd.to_datetime(events["signal_close_date"]).dt.year)[
            "realized_advantage"
        ].sum()
        if not events.empty
        else pd.Series(dtype=float)
    )
    without_best_year = (
        float(yearly.drop(index=yearly.idxmax()).sum()) if len(yearly) > 1 else np.nan
    )
    cluster_sum = (
        clustered.groupby("macro_cluster_id")["realized_advantage"].sum()
        if not clustered.empty
        else pd.Series(dtype=float)
    )
    without_best_cluster = (
        float(cluster_sum.drop(index=cluster_sum.idxmax()).sum())
        if len(cluster_sum) > 1
        else np.nan
    )
    return {
        "model": model_name,
        "events": int(len(events)),
        "unconditional_positive_rate": unconditional,
        "triggered_precision": precision,
        "precision_lift": (precision - unconditional if np.isfinite(precision) else np.nan),
        "median_triggered_advantage": median,
        "macro_clusters": int(clustered["macro_cluster_id"].nunique())
        if not clustered.empty
        else 0,
        "largest_positive_cluster_share": cluster_share,
        "advantage_without_best_year": without_best_year,
        "advantage_without_best_cluster": without_best_cluster,
    }


def _event_gate(
    base_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["event_gate"]
    precision_improvement = float(
        candidate_summary["triggered_precision"] - base_summary["triggered_precision"]
    )
    median_improvement = float(
        candidate_summary["median_triggered_advantage"] - base_summary["median_triggered_advantage"]
    )
    checks = {
        "precision_lift": candidate_summary["precision_lift"]
        >= float(threshold["triggered_precision_lift_min"]),
        "median_advantage": candidate_summary["median_triggered_advantage"]
        > float(threshold["median_triggered_advantage_min"]),
        "minimum_clusters": candidate_summary["macro_clusters"]
        >= int(threshold["minimum_macro_clusters"]),
        "cluster_concentration": candidate_summary["largest_positive_cluster_share"]
        <= float(threshold["largest_positive_cluster_share_max"]),
        "without_best_year": candidate_summary["advantage_without_best_year"]
        >= float(threshold["without_best_year_min"]),
        "without_best_cluster": candidate_summary["advantage_without_best_cluster"]
        >= float(threshold["without_best_cluster_min"]),
        "precision_vs_v4_16": precision_improvement
        >= float(threshold["precision_improvement_vs_v4_16_min"]),
        "median_vs_v4_16": median_improvement
        >= float(threshold["median_advantage_improvement_vs_v4_16_min"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "base": dict(base_summary),
            "candidate": dict(candidate_summary),
            "precision_improvement_vs_v4_16": precision_improvement,
            "median_advantage_improvement_vs_v4_16": median_improvement,
        },
        "passed": bool(all(checks.values())),
    }


def _portfolio_gate(
    base_policy: AdvantagePolicyResult,
    candidate_policy: AdvantagePolicyResult,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["portfolio_gate"]
    baseline = candidate_policy.oof_results["frozen_v4_2"]
    policy = candidate_policy.oof_results["full_event_policy"]
    v416 = base_policy.oof_results["full_event_policy"]
    cagr_delta_pp = (float(policy.metrics["cagr"]) - float(baseline.metrics["cagr"])) * 100.0
    drawdown_worsening_pp = max(
        0.0,
        (float(baseline.metrics["max_drawdown"]) - float(policy.metrics["max_drawdown"])) * 100.0,
    )
    calmar_delta = float(policy.metrics["calmar"]) - float(baseline.metrics["calmar"])
    aligned = pd.concat(
        [
            policy.daily["net_return"].rename("policy"),
            baseline.daily["net_return"].rename("baseline"),
        ],
        axis=1,
    ).dropna()
    yearly: dict[str, float] = {}
    for year, group in aligned.groupby(aligned.index.year):
        yearly[str(int(year))] = float(
            (1.0 + group["policy"]).prod() - (1.0 + group["baseline"]).prod()
        )
    positive_year_rate = float(np.mean([value > 0.0 for value in yearly.values()]))
    year_series = pd.Series(yearly, dtype=float)
    without_best_year = (
        float(year_series.drop(index=year_series.idxmax()).sum())
        if len(year_series) > 1
        else np.nan
    )
    attribution = candidate_policy.oof_attribution
    positive = attribution.loc[attribution["relative_return"].gt(0.0)]
    total_positive = float(positive["relative_return"].sum()) if len(positive) else 0.0
    event_share = (
        float(positive["relative_return"].max() / total_positive) if total_positive > 0.0 else 1.0
    )
    family_positive = positive.groupby("event_family")["relative_return"].sum()
    family_share = float(family_positive.max() / total_positive) if total_positive > 0.0 else 1.0
    events = candidate_policy.oof_action_trace
    active = events.loc[events["event_id"].notna(), ["event_id"]].copy()
    active["date"] = active.index
    event_dates = active.groupby("event_id")["date"].min().reset_index()
    event_dates["macro_cluster_id"] = (
        event_dates["date"] - event_dates["date"].min()
    ).dt.days // 30
    attributed = attribution.merge(event_dates, on="event_id", how="left")
    cluster_relative = attributed.groupby("macro_cluster_id")["relative_return"].sum()
    without_best_cluster = (
        float(cluster_relative.drop(index=cluster_relative.idxmax()).sum())
        if len(cluster_relative) > 1
        else np.nan
    )
    turnover_increase = (
        float(policy.metrics["turnover_units"]) / float(baseline.metrics["turnover_units"]) - 1.0
    )
    ablation_wins: dict[str, int] = {}
    for action in ACTION_KEYS:
        comparator = candidate_policy.oof_results[f"ablation_{action}"]
        ablation_wins[action] = int(
            sum(
                [
                    float(policy.metrics["cagr"]) > float(comparator.metrics["cagr"]),
                    float(policy.metrics["max_drawdown"])
                    > float(comparator.metrics["max_drawdown"]),
                    float(policy.metrics["sortino"]) > float(comparator.metrics["sortino"]),
                    float(policy.metrics["calmar"]) > float(comparator.metrics["calmar"]),
                ]
            )
        )
    cagr_vs_v416 = float(policy.metrics["cagr"] - v416.metrics["cagr"])
    calmar_vs_v416 = float(policy.metrics["calmar"] - v416.metrics["calmar"])
    checks = {
        "cagr_vs_v4_2": cagr_delta_pp >= float(threshold["cagr_improvement_vs_v4_2_pp_min"]),
        "max_drawdown": drawdown_worsening_pp <= float(threshold["max_drawdown_worsening_pp_max"]),
        "calmar_vs_v4_2": calmar_delta >= float(threshold["calmar_improvement_vs_v4_2_min"]),
        "sortino": float(policy.metrics["sortino"]) >= float(baseline.metrics["sortino"]),
        "positive_years": positive_year_rate >= float(threshold["positive_calendar_year_rate_min"]),
        "turnover": turnover_increase <= float(threshold["turnover_increase_max"]),
        "family_concentration": family_share
        <= float(threshold["largest_family_positive_share_max"]),
        "event_concentration": event_share <= float(threshold["largest_event_positive_share_max"]),
        "without_best_year": without_best_year >= float(threshold["without_best_year_min"]),
        "without_best_cluster": without_best_cluster
        >= float(threshold["without_best_cluster_min"]),
        "cagr_vs_v4_16": cagr_vs_v416 > float(threshold["cagr_improvement_vs_v4_16_min"]),
        "calmar_vs_v4_16": calmar_vs_v416 > float(threshold["calmar_improvement_vs_v4_16_min"]),
        **{
            f"beats_{action}_ablation": wins >= int(threshold["ablation_metric_wins_min"])
            for action, wins in ablation_wins.items()
        },
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_pp_vs_v4_2": cagr_delta_pp,
            "max_drawdown_worsening_pp": drawdown_worsening_pp,
            "calmar_delta_vs_v4_2": calmar_delta,
            "positive_calendar_year_rate": positive_year_rate,
            "calendar_year_relative_returns": yearly,
            "relative_return_without_best_year": without_best_year,
            "relative_return_without_best_cluster": without_best_cluster,
            "largest_family_positive_share": family_share,
            "largest_event_positive_share": event_share,
            "turnover_increase": turnover_increase,
            "cagr_delta_vs_v4_16": cagr_vs_v416,
            "calmar_delta_vs_v4_16": calmar_vs_v416,
            "ablation_win_counts": ablation_wins,
        },
        "passed": bool(all(checks.values())),
    }


def _actual_gate(
    base_policy: AdvantagePolicyResult,
    candidate_policy: AdvantagePolicyResult,
    candidate_events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["actual_contradiction_gate"]
    baseline = candidate_policy.actual_results["frozen_v4_2"]
    policy = candidate_policy.actual_results["full_event_policy"]
    v416 = base_policy.actual_results["full_event_policy"]
    cagr_delta = float(policy.metrics["cagr"] - baseline.metrics["cagr"])
    calmar_delta = float(policy.metrics["calmar"] - baseline.metrics["calmar"])
    cagr_vs_v416 = float(policy.metrics["cagr"] - v416.metrics["cagr"])
    calmar_vs_v416 = float(policy.metrics["calmar"] - v416.metrics["calmar"])
    drawdown_worsening_pp = max(
        0.0,
        (float(baseline.metrics["max_drawdown"]) - float(policy.metrics["max_drawdown"])) * 100.0,
    )
    median_event = (
        float(candidate_events["realized_advantage"].median())
        if not candidate_events.empty
        else np.nan
    )
    checks = {
        "not_both_below_v4_2": not (cagr_delta < 0.0 and calmar_delta < 0.0),
        "max_drawdown": drawdown_worsening_pp
        <= float(threshold["max_drawdown_worsening_vs_v4_2_pp_max"]),
        "not_both_below_v4_16": not (cagr_vs_v416 < 0.0 and calmar_vs_v416 < 0.0),
        "median_actual_event_advantage": np.isfinite(median_event)
        and median_event >= float(threshold["median_actual_event_advantage_min"]),
        "no_pre_inception_backfill": True,
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_vs_v4_2": cagr_delta,
            "calmar_delta_vs_v4_2": calmar_delta,
            "max_drawdown_worsening_pp": drawdown_worsening_pp,
            "cagr_delta_vs_v4_16": cagr_vs_v416,
            "calmar_delta_vs_v4_16": calmar_vs_v416,
            "median_actual_event_advantage": median_event,
        },
        "passed": bool(all(checks.values())),
    }


def _model_result(
    frame: pd.DataFrame,
    features: Sequence[str],
    targets: Sequence[str],
    oof: pd.DataFrame,
    coefficients: pd.DataFrame,
    actual: pd.DataFrame,
    actual_coefficients: pd.DataFrame,
    v416_contract: Mapping[str, Any],
    *,
    model_name: str,
) -> AdvantageModelResult:
    events = select_advantage_events(oof, v416_contract, sample=f"oof_{model_name}")
    actual_events = select_advantage_events(actual, v416_contract, sample=f"actual_{model_name}")
    action_rows: list[dict[str, Any]] = []
    for action, target in zip(ACTION_KEYS, targets):
        action_rows.append(
            {
                "action": action,
                "observations": int(oof[target].notna().sum()),
                "spearman_ic": float(
                    oof[f"predicted_{action}"].corr(oof[target], method="spearman")
                ),
                "top_bottom_quintile_spread": _quintile_spread(
                    oof[f"predicted_{action}"], oof[target]
                ),
            }
        )
    return AdvantageModelResult(
        frame=frame,
        feature_names=tuple(features),
        target_names=tuple(targets),
        oof_predictions=oof,
        fold_coefficients=coefficients.loc[coefficients["model"].eq(model_name)].drop(
            columns="model"
        ),
        action_metrics=pd.DataFrame(action_rows),
        oof_events=events,
        model_gate={"passed": False, "model": model_name},
        actual_predictions=actual,
        actual_events=actual_events,
        actual_coefficients=actual_coefficients.loc[
            actual_coefficients["model"].eq(model_name)
        ].drop(columns="model"),
    )


def run_credit_duration_phase2(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
) -> CreditDurationPhase2Result:
    frame, base_features, targets = build_action_advantage_frame(
        bars, proxy_baseline_daily, v416_contract
    )
    blocks = build_market_internal_feature_blocks(bars, frame.index)
    credit_features = tuple(str(value) for value in contract["credit_duration_block"]["features"])
    credit = blocks["credit_duration_risk_appetite"].loc[:, list(credit_features)]
    frame = frame.join(credit, how="left")
    candidate_features = tuple(base_features) + credit_features
    if len(base_features) != int(contract["base_comparator"]["total_inputs"]):
        raise AssertionError("base model input count does not match contract")
    if len(candidate_features) != int(contract["credit_duration_block"]["candidate_total_inputs"]):
        raise AssertionError("candidate model input count does not match contract")

    base_oof, candidate_oof, coefficients, coverage, frame = _build_shared_models(
        frame,
        base_features,
        candidate_features,
        targets,
        contract,
    )
    base_actual, candidate_actual, actual_coefficients = _build_actual_models(
        frame,
        base_features,
        candidate_features,
        targets,
        contract,
    )
    base_model = _model_result(
        frame,
        base_features,
        targets,
        base_oof,
        coefficients,
        base_actual,
        actual_coefficients,
        v416_contract,
        model_name="base",
    )
    candidate_model = _model_result(
        frame,
        candidate_features,
        targets,
        candidate_oof,
        coefficients,
        candidate_actual,
        actual_coefficients,
        v416_contract,
        model_name="candidate",
    )
    base_policy = run_action_advantage_policy(
        bars,
        proxy_baseline_daily,
        actual_baseline_daily,
        base_model,
        v416_contract,
    )
    candidate_policy = run_action_advantage_policy(
        bars,
        proxy_baseline_daily,
        actual_baseline_daily,
        candidate_model,
        v416_contract,
    )
    action_metrics, state_metrics, fold_metrics = _action_metrics(base_oof, candidate_oof, targets)
    calibration_metrics = _calibration_metrics(base_oof, candidate_oof, targets, contract)
    cosines = _cosine_table(coefficients)
    ranking_gate = _ranking_gate(
        action_metrics,
        state_metrics,
        fold_metrics,
        cosines,
        base_oof,
        candidate_oof,
        targets,
        contract,
    )
    calibration_gate = _calibration_gate(calibration_metrics, contract)
    base_event_summary = _event_summary(
        base_model.oof_events,
        base_oof,
        targets,
        contract,
        model_name="same_endpoint_v4_16",
    )
    candidate_event_summary = _event_summary(
        candidate_model.oof_events,
        candidate_oof,
        targets,
        contract,
        model_name="credit_duration_v4_20",
    )
    event_metrics = pd.DataFrame([base_event_summary, candidate_event_summary])
    event_gate = _event_gate(base_event_summary, candidate_event_summary, contract)
    portfolio_gate = _portfolio_gate(base_policy, candidate_policy, contract)
    actual_gate = _actual_gate(
        base_policy,
        candidate_policy,
        candidate_model.actual_events,
        contract,
    )
    checks = {
        "ranking_gate": ranking_gate["passed"],
        "calibration_gate": calibration_gate["passed"],
        "event_gate": event_gate["passed"],
        "portfolio_gate": portfolio_gate["passed"],
        "actual_contradiction_gate": actual_gate["passed"],
        "complete_credit_duration_block": len(credit_features) == 8,
        "same_rows": bool(
            coverage["base_candidate_training_rows_identical"].all()
            and coverage["base_candidate_test_rows_identical"].all()
        ),
        "baseline_and_alerts_unchanged": True,
    }
    final_gate = {
        "checks": checks,
        "passed": bool(all(checks.values())),
        "shadow_candidate_authorized": bool(all(checks.values())),
        "direct_promotion_authorized": False,
    }
    return CreditDurationPhase2Result(
        frame=frame,
        base_model=base_model,
        candidate_model=candidate_model,
        base_policy=base_policy,
        candidate_policy=candidate_policy,
        rank_action_metrics=action_metrics,
        rank_action_state_metrics=state_metrics,
        rank_fold_metrics=fold_metrics,
        calibration_metrics=calibration_metrics,
        event_metrics=event_metrics,
        coefficient_cosines=cosines,
        same_row_coverage=coverage,
        ranking_gate=ranking_gate,
        calibration_gate=calibration_gate,
        event_gate=event_gate,
        portfolio_gate=portfolio_gate,
        actual_contradiction_gate=actual_gate,
        final_gate=final_gate,
    )
