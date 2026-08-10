"""Grouped XGBoost fitting and Phase 1 evidence for v4.23."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import xgboost as xgb

from src.research.v4_23_xgb_lambdarank_data import ACTION_ORDER


@dataclass(frozen=True)
class RankModelBundle:
    booster: xgb.Booster
    feature_names: tuple[str, ...]
    training_groups: int
    training_rows: int


def embargo_train_end(
    index: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    declared_train_end: pd.Timestamp,
    embargo_sessions: int,
) -> pd.Timestamp:
    location = int(index.searchsorted(test_start, side="left"))
    location = max(location - embargo_sessions - 1, 0)
    return min(declared_train_end, pd.Timestamp(index[location]))


def _params(contract: Mapping[str, Any]) -> dict[str, Any]:
    model = contract["model"]
    return {
        "objective": str(model["objective"]),
        "eval_metric": str(model["eval_metric"]),
        "tree_method": str(model["tree_method"]),
        "max_depth": int(model["max_depth"]),
        "eta": float(model["learning_rate"]),
        "min_child_weight": float(model["min_child_weight"]),
        "subsample": float(model["subsample"]),
        "colsample_bytree": float(model["colsample_bytree"]),
        "lambda": float(model["reg_lambda"]),
        "alpha": float(model["reg_alpha"]),
        "gamma": float(model["gamma"]),
        "max_bin": int(model["max_bin"]),
        "seed": int(model["seed"]),
        "nthread": int(model.get("nthread", 2)),
        "verbosity": 0,
    }


def fit_ranker(
    groups: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    *,
    relevance: pd.Series | None = None,
) -> RankModelBundle:
    ordered = groups.sort_values(["decision_date", "action_order"]).copy()
    group_sizes = ordered.groupby("decision_date", sort=False).size().tolist()
    if not group_sizes or any(size != len(ACTION_ORDER) for size in group_sizes):
        raise ValueError("ranker groups must contain exactly five actions")
    labels = ordered["relevance"] if relevance is None else relevance.loc[ordered.index]
    matrix = xgb.DMatrix(
        ordered[list(feature_names)],
        label=pd.to_numeric(labels, errors="raise").to_numpy(dtype=float),
        feature_names=list(feature_names),
        missing=np.nan,
    )
    matrix.set_group(group_sizes)
    booster = xgb.train(
        _params(contract),
        matrix,
        num_boost_round=int(contract["model"]["boosting_rounds"]),
    )
    return RankModelBundle(
        booster=booster,
        feature_names=tuple(feature_names),
        training_groups=len(group_sizes),
        training_rows=len(ordered),
    )


def predict(bundle: RankModelBundle, groups: pd.DataFrame) -> np.ndarray:
    matrix = xgb.DMatrix(
        groups[list(bundle.feature_names)],
        feature_names=list(bundle.feature_names),
        missing=np.nan,
    )
    return np.asarray(bundle.booster.predict(matrix), dtype=float)


def _ndcg_at_one(relevance: int) -> float:
    return float((2.0 ** float(relevance) - 1.0) / 15.0)


def select_from_scores(scored: pd.DataFrame) -> pd.DataFrame:
    best_return = scored.groupby("decision_date")["realized_action_return"].max()
    selected = (
        scored.sort_values(
            ["decision_date", "score", "action_order"],
            ascending=[True, False, True],
        )
        .groupby("decision_date", sort=True)
        .head(1)
        .copy()
    )
    selected["selected_realized_rank"] = 5 - selected["relevance"].astype(int)
    selected["selected_ndcg_at_1"] = selected["relevance"].map(_ndcg_at_one)
    selected["selected_regret"] = (
        selected["decision_date"].map(best_return) - selected["realized_action_return"]
    )
    return selected.sort_values("decision_date").reset_index(drop=True)


def score_outer_folds(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[str, RankModelBundle, pd.DataFrame]]]:
    unique_dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["decision_date"].unique())))
    scored_parts: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    bundles: list[tuple[str, RankModelBundle, pd.DataFrame]] = []
    for specification in contract["outer_folds"]:
        fold = str(specification["fold"])
        test_start = pd.Timestamp(specification["test_start"])
        test_end = pd.Timestamp(specification["test_end"])
        train_end = embargo_train_end(
            unique_dates,
            test_start,
            pd.Timestamp(specification["train_end"]),
            int(contract["decision"]["embargo_sessions"]),
        )
        training = frame.loc[
            frame["decision_date"].between(
                pd.Timestamp(specification["train_start"]),
                train_end,
                inclusive="both",
            )
        ].copy()
        testing = frame.loc[
            frame["decision_date"].between(test_start, test_end, inclusive="both")
        ].copy()
        if training["decision_date"].nunique() < int(contract["training"]["minimum_groups"]):
            raise ValueError(f"{fold} has insufficient training groups")
        if testing.empty:
            raise ValueError(f"{fold} has no test groups")
        bundle = fit_ranker(training, feature_names, contract)
        testing["score"] = predict(bundle, testing)
        testing["fold"] = fold
        scored_parts.append(testing)
        bundles.append((fold, bundle, testing))
        coverage_rows.append(
            {
                "fold": fold,
                "training_start": training["decision_date"].min(),
                "training_end": training["decision_date"].max(),
                "training_groups": int(training["decision_date"].nunique()),
                "training_rows": int(len(training)),
                "test_start": testing["decision_date"].min(),
                "test_end": testing["decision_date"].max(),
                "test_groups": int(testing["decision_date"].nunique()),
                "test_rows": int(len(testing)),
                "declared_embargo_sessions": int(contract["decision"]["embargo_sessions"]),
            }
        )
    scored = pd.concat(scored_parts, ignore_index=True).sort_values(
        ["decision_date", "action_order"]
    )
    return scored, pd.DataFrame(coverage_rows), bundles


def ranking_metrics(
    scored: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    selected = select_from_scores(scored)
    comparator = scored.loc[scored["action"].eq(scored["v4_2_comparator_action"])].set_index(
        "decision_date"
    )
    best = scored.groupby("decision_date")["realized_action_return"].max()
    comparator["comparator_ndcg_at_1"] = comparator["relevance"].map(_ndcg_at_one)
    comparator["comparator_regret"] = best - comparator["realized_action_return"]
    indexed = selected.set_index("decision_date")
    indexed["comparator_ndcg_at_1"] = comparator["comparator_ndcg_at_1"]
    indexed["comparator_regret"] = comparator["comparator_regret"]
    indexed["comparator_action_return"] = comparator["realized_action_return"]
    indexed["selected_advantage_over_comparator_action"] = (
        indexed["realized_action_return"] - indexed["comparator_action_return"]
    )
    selected = indexed.reset_index()
    fold_rows: list[dict[str, Any]] = []
    for fold, table in selected.groupby("fold"):
        selected_regret = float(table["selected_regret"].mean())
        comparator_regret = float(table["comparator_regret"].mean())
        fold_rows.append(
            {
                "fold": fold,
                "groups": int(len(table)),
                "selected_ndcg_at_1": float(table["selected_ndcg_at_1"].mean()),
                "comparator_ndcg_at_1": float(table["comparator_ndcg_at_1"].mean()),
                "ndcg_improvement": float(
                    table["selected_ndcg_at_1"].mean() - table["comparator_ndcg_at_1"].mean()
                ),
                "selected_mean_regret": selected_regret,
                "comparator_mean_regret": comparator_regret,
                "regret_reduction": (
                    1.0 - selected_regret / comparator_regret
                    if comparator_regret > 1e-12
                    else np.nan
                ),
                "top_two_rate": float(table["relevance"].ge(3).mean()),
                "median_advantage_vs_v4_2": float(table["realized_advantage_vs_v4_2"].median()),
                "total_advantage_vs_v4_2": float(table["realized_advantage_vs_v4_2"].sum()),
            }
        )
    action_rows: list[dict[str, Any]] = []
    for action in ACTION_ORDER:
        table = selected.loc[selected["action"].eq(action)]
        action_rows.append(
            {
                "action": action,
                "selected_groups": int(len(table)),
                "top_two_rate": (float(table["relevance"].ge(3).mean()) if len(table) else np.nan),
                "median_advantage_vs_v4_2": (
                    float(table["realized_advantage_vs_v4_2"].median()) if len(table) else np.nan
                ),
                "total_advantage_vs_v4_2": (
                    float(table["realized_advantage_vs_v4_2"].sum()) if len(table) else 0.0
                ),
            }
        )
    return selected, pd.DataFrame(fold_rows), pd.DataFrame(action_rows)


def concentration_metrics(selected: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    table = selected.copy()
    table["year"] = pd.to_datetime(table["decision_date"]).dt.year
    dates = pd.to_datetime(table["decision_date"]).sort_values()
    cluster_days = int(contract["validation"]["macro_cluster_calendar_days"])
    cluster_by_date: dict[pd.Timestamp, int] = {}
    cluster_id = 0
    cluster_start: pd.Timestamp | None = None
    for date in dates:
        timestamp = pd.Timestamp(date)
        if cluster_start is None or (timestamp - cluster_start).days > cluster_days:
            cluster_id += 1
            cluster_start = timestamp
        cluster_by_date[timestamp] = cluster_id
    table["macro_cluster"] = pd.to_datetime(table["decision_date"]).map(cluster_by_date)
    positive = table["realized_advantage_vs_v4_2"].clip(lower=0.0)
    total_positive = float(positive.sum())
    by_year = table.assign(positive=positive).groupby("year")["positive"].sum()
    by_cluster = table.assign(positive=positive).groupby("macro_cluster")["positive"].sum()
    best_year = int(by_year.idxmax()) if total_positive > 0 else None
    best_cluster = by_cluster.idxmax() if total_positive > 0 else None
    return pd.DataFrame(
        [
            {
                "total_advantage": float(table["realized_advantage_vs_v4_2"].sum()),
                "positive_advantage": total_positive,
                "largest_positive_year_share": (
                    float(by_year.max() / total_positive) if total_positive > 0 else np.nan
                ),
                "largest_positive_cluster_share": (
                    float(by_cluster.max() / total_positive) if total_positive > 0 else np.nan
                ),
                "best_year": best_year,
                "best_macro_cluster": best_cluster,
                "advantage_without_best_year": float(
                    table.loc[
                        table["year"].ne(best_year),
                        "realized_advantage_vs_v4_2",
                    ].sum()
                ),
                "advantage_without_best_cluster": float(
                    table.loc[
                        table["macro_cluster"].ne(best_cluster),
                        "realized_advantage_vs_v4_2",
                    ].sum()
                ),
            }
        ]
    )


def placebo_metrics(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    observed_ndcg: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seed = int(contract["model"]["seed"])
    for trial in range(int(contract["validation"]["placebo_trials"])):
        rng = np.random.default_rng(seed + trial + 1)
        scored_parts: list[pd.DataFrame] = []
        unique_dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["decision_date"].unique())))
        for specification in contract["outer_folds"]:
            test_start = pd.Timestamp(specification["test_start"])
            train_end = embargo_train_end(
                unique_dates,
                test_start,
                pd.Timestamp(specification["train_end"]),
                int(contract["decision"]["embargo_sessions"]),
            )
            training = frame.loc[
                frame["decision_date"].between(
                    pd.Timestamp(specification["train_start"]),
                    train_end,
                    inclusive="both",
                )
            ].copy()
            testing = frame.loc[
                frame["decision_date"].between(
                    test_start,
                    pd.Timestamp(specification["test_end"]),
                    inclusive="both",
                )
            ].copy()
            permuted = training["relevance"].copy()
            for _, group in training.groupby("decision_date", sort=False):
                values = permuted.loc[group.index].to_numpy(copy=True)
                rng.shuffle(values)
                permuted.loc[group.index] = values
            bundle = fit_ranker(training, feature_names, contract, relevance=permuted)
            testing["score"] = predict(bundle, testing)
            scored_parts.append(testing)
        selected = select_from_scores(pd.concat(scored_parts, ignore_index=True))
        ndcg = float(selected["selected_ndcg_at_1"].mean())
        rows.append(
            {
                "trial": trial,
                "placebo_ndcg_at_1": ndcg,
                "observed_ndcg_at_1": observed_ndcg,
                "observed_beats_placebo": bool(observed_ndcg > ndcg),
            }
        )
    return pd.DataFrame(rows)


def importance_metrics(
    bundles: Sequence[tuple[str, RankModelBundle, pd.DataFrame]],
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    gain_rows: list[dict[str, Any]] = []
    shap_rows: list[dict[str, Any]] = []
    for fold, bundle, testing in bundles:
        gain = bundle.booster.get_score(importance_type="gain")
        total_gain = float(sum(gain.values()))
        matrix = xgb.DMatrix(
            testing[list(feature_names)],
            feature_names=list(feature_names),
            missing=np.nan,
        )
        contributions = np.asarray(bundle.booster.predict(matrix, pred_contribs=True), dtype=float)
        absolute = np.abs(contributions[:, :-1]).mean(axis=0)
        total_shap = float(absolute.sum())
        for feature, shap_value in zip(feature_names, absolute):
            gain_value = float(gain.get(feature, 0.0))
            gain_rows.append(
                {
                    "fold": fold,
                    "feature": feature,
                    "gain": gain_value,
                    "gain_share": gain_value / total_gain if total_gain else 0.0,
                }
            )
            shap_rows.append(
                {
                    "fold": fold,
                    "feature": feature,
                    "mean_abs_shap": float(shap_value),
                    "shap_share": (float(shap_value / total_shap) if total_shap else 0.0),
                }
            )
    family_lookup = {
        feature: family
        for family, features in contract["features"]["families"].items()
        for feature in features
    }
    gain_frame = pd.DataFrame(gain_rows)
    shap_frame = pd.DataFrame(shap_rows)
    gain_frame["family"] = gain_frame["feature"].map(family_lookup)
    shap_frame["family"] = shap_frame["feature"].map(family_lookup)
    return gain_frame, shap_frame


def phase1_gate(
    selected: pd.DataFrame,
    by_fold: pd.DataFrame,
    by_action: pd.DataFrame,
    placebo: pd.DataFrame,
    shap: pd.DataFrame,
    concentration: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    gate = contract["validation"]["phase1"]
    ndcg = float(selected["selected_ndcg_at_1"].mean())
    comparator_ndcg = float(selected["comparator_ndcg_at_1"].mean())
    selected_regret = float(selected["selected_regret"].mean())
    comparator_regret = float(selected["comparator_regret"].mean())
    regret_reduction = (
        1.0 - selected_regret / comparator_regret if comparator_regret > 1e-12 else np.nan
    )
    feature_mean = shap.groupby("feature")["mean_abs_shap"].mean()
    family_mean = shap.groupby("family")["mean_abs_shap"].mean()
    largest_feature = float(feature_mean.max() / feature_mean.sum())
    largest_family = float(family_mean.max() / family_mean.sum())
    row = concentration.iloc[0]
    checks = {
        "ndcg_improvement": ndcg - comparator_ndcg >= float(gate["ndcg_improvement_min"]),
        "regret_reduction": regret_reduction >= float(gate["regret_reduction_min"]),
        "positive_median_advantage": float(selected["realized_advantage_vs_v4_2"].median())
        > float(gate["median_advantage_min"]),
        "positive_outer_folds": int(by_fold["total_advantage_vs_v4_2"].gt(0.0).sum())
        >= int(gate["positive_outer_folds_min"]),
        "top_two_rate": float(selected["relevance"].ge(3).mean())
        >= float(gate["top_two_rate_min"]),
        "year_concentration": float(row["largest_positive_year_share"])
        <= float(gate["largest_positive_year_share_max"]),
        "cluster_concentration": float(row["largest_positive_cluster_share"])
        <= float(gate["largest_positive_cluster_share_max"]),
        "without_best_year": float(row["advantage_without_best_year"]) > 0.0,
        "without_best_cluster": float(row["advantage_without_best_cluster"]) > 0.0,
        "placebo": float(placebo["observed_beats_placebo"].mean())
        >= float(gate["placebo_beat_rate_min"]),
        "single_feature_concentration": largest_feature
        <= float(gate["largest_single_feature_share_max"]),
        "feature_family_concentration": largest_family
        <= float(gate["largest_feature_family_share_max"]),
    }
    unsupported = by_action.loc[
        by_action["selected_groups"].lt(int(gate["minimum_selected_groups_per_action"])),
        "action",
    ].tolist()
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "selected_ndcg_at_1": ndcg,
        "comparator_ndcg_at_1": comparator_ndcg,
        "ndcg_improvement": ndcg - comparator_ndcg,
        "selected_mean_regret": selected_regret,
        "comparator_mean_regret": comparator_regret,
        "regret_reduction": regret_reduction,
        "median_advantage_vs_v4_2": float(selected["realized_advantage_vs_v4_2"].median()),
        "positive_outer_folds": int(by_fold["total_advantage_vs_v4_2"].gt(0.0).sum()),
        "top_two_rate": float(selected["relevance"].ge(3).mean()),
        "unsupported_actions": unsupported,
        "placebo_beat_rate": float(placebo["observed_beats_placebo"].mean()),
        "largest_single_feature_share": largest_feature,
        "largest_feature_family_share": largest_family,
    }
