"""Governed v4.26 XGBoost ordinal risk-budget convergence study."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    cohen_kappa_score,
    log_loss,
    recall_score,
    roc_auc_score,
)

from src.research.v4_24_xgb_adjacent_path_data import STATE_ORDER, build_path_utility_frame
from src.research.v4_24_xgb_adjacent_path_model import embargo_train_end
from src.research.v4_24_xgb_adjacent_path_policy import actual_gate, phase2_evidence, phase2_gate


@dataclass(frozen=True)
class OrdinalModelBundle:
    fold: str
    booster: xgb.Booster
    feature_names: tuple[str, ...]
    training_groups: int
    class_counts: tuple[int, ...]
    test_frame: pd.DataFrame


@dataclass(frozen=True)
class OrdinalRiskBudgetResult:
    proxy_frame: pd.DataFrame
    actual_frame: pd.DataFrame
    feature_names: tuple[str, ...]
    fold_coverage: pd.DataFrame
    oof_scores: pd.DataFrame
    actual_scores: pd.DataFrame
    model_metrics: pd.DataFrame
    class_metrics: pd.DataFrame
    confusion: pd.DataFrame
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


def _add_oracle_label(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    utility_columns = [f"{state}_path_utility" for state in STATE_ORDER]
    values = output[utility_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("non-finite state utility in v4.26 frame")
    # np.argmax returns the first maximum; STATE_ORDER is low-to-high risk.
    labels = np.argmax(values, axis=1).astype(int)
    output["oracle_state_index"] = labels
    output["oracle_state"] = [STATE_ORDER[value] for value in labels]
    return output


def build_ordinal_frames(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[str, ...]]:
    proxy, feature_names = build_path_utility_frame(
        bars, proxy_baseline_daily, contract, v416_contract, actual=False
    )
    actual, actual_features = build_path_utility_frame(
        bars, actual_baseline_daily, contract, v416_contract, actual=True
    )
    if feature_names != actual_features:
        raise AssertionError("proxy and actual feature schemas diverged")
    actual_start = pd.Timestamp(contract["data"]["actual_product_start"])
    actual = actual.loc[actual["decision_date"].ge(actual_start)].copy()
    if actual.empty:
        raise ValueError("actual 2024+ ordinal frame is empty")
    return _add_oracle_label(proxy), _add_oracle_label(actual), feature_names


def _params(contract: Mapping[str, Any], seed_offset: int = 0) -> dict[str, Any]:
    model = contract["model"]
    return {
        "objective": str(model["objective"]),
        "num_class": int(model["num_class"]),
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
        "seed": int(model["seed"]) + int(seed_offset),
        "nthread": int(model.get("nthread", 2)),
        "verbosity": 0,
    }


def _fit(
    training: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    *,
    fold: str,
    labels: pd.Series | None = None,
    seed_offset: int = 0,
) -> OrdinalModelBundle:
    y = (
        pd.to_numeric(training["oracle_state_index"], errors="raise")
        if labels is None
        else pd.to_numeric(labels.reindex(training.index), errors="raise")
    ).astype(int)
    counts = y.value_counts().reindex(range(len(STATE_ORDER)), fill_value=0)
    minimum = int(contract["training"]["minimum_class_count"])
    if int(counts.min()) < minimum:
        raise ValueError(f"{fold} class count below {minimum}: {counts.to_dict()}")
    matrix = xgb.DMatrix(
        training[list(feature_names)],
        label=y.to_numpy(dtype=float),
        feature_names=list(feature_names),
        missing=np.nan,
    )
    booster = xgb.train(
        _params(contract, seed_offset),
        matrix,
        num_boost_round=int(contract["model"]["boosting_rounds"]),
    )
    return OrdinalModelBundle(
        fold=fold,
        booster=booster,
        feature_names=tuple(feature_names),
        training_groups=int(len(training)),
        class_counts=tuple(int(counts.loc[index]) for index in range(len(STATE_ORDER))),
        test_frame=pd.DataFrame(),
    )


def _predict(bundle: OrdinalModelBundle, frame: pd.DataFrame) -> np.ndarray:
    matrix = xgb.DMatrix(
        frame[list(bundle.feature_names)],
        feature_names=list(bundle.feature_names),
        missing=np.nan,
    )
    probabilities = np.asarray(bundle.booster.predict(matrix), dtype=float)
    if probabilities.ndim != 2 or probabilities.shape[1] != len(STATE_ORDER):
        raise AssertionError(f"unexpected multiclass probability shape {probabilities.shape}")
    return probabilities


def _attach_predictions(frame: pd.DataFrame, probabilities: np.ndarray) -> pd.DataFrame:
    output = frame.copy()
    for index, state in enumerate(STATE_ORDER):
        output[f"prob_{state}"] = probabilities[:, index]
    expected = probabilities @ np.arange(len(STATE_ORDER), dtype=float)
    selected_index = np.floor(expected + 0.5).astype(int)
    selected_index = np.clip(selected_index, 0, len(STATE_ORDER) - 1)
    output["expected_risk_index"] = expected
    output["selected_state_index"] = selected_index
    output["selected_state"] = [STATE_ORDER[value] for value in selected_index]
    return _selection_evidence(output)


def _selection_evidence(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for raw in scored.sort_values("decision_date").to_dict(orient="records"):
        state = str(raw["selected_state"])
        utilities = {candidate: float(raw[f"{candidate}_path_utility"]) for candidate in STATE_ORDER}
        ordered = sorted(
            STATE_ORDER,
            key=lambda candidate: (utilities[candidate], -STATE_ORDER.index(candidate)),
            reverse=True,
        )
        oracle = max([*utilities.values(), float(raw["baseline_path_utility"])])
        row = dict(raw)
        row.update(
            {
                "selected_terminal_return": float(raw[f"{state}_terminal_return"]),
                "selected_mae": float(raw[f"{state}_mae"]),
                "selected_path_utility": utilities[state],
                "selected_utility_rank": int(ordered.index(state) + 1),
                "selected_top_two": bool(ordered.index(state) < 2),
                "selected_utility_advantage_vs_v4_2": float(
                    utilities[state] - float(raw["baseline_path_utility"])
                ),
                "selected_utility_regret": float(oracle - utilities[state]),
                "baseline_utility_regret": float(
                    oracle - float(raw["baseline_path_utility"])
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("decision_date").reset_index(drop=True)


def score_outer_folds(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    *,
    permuted_labels: pd.Series | None = None,
    seed_offset: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, list[OrdinalModelBundle]]:
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["decision_date"].unique())))
    parts: list[pd.DataFrame] = []
    coverage: list[dict[str, Any]] = []
    bundles: list[OrdinalModelBundle] = []
    for fold_number, fold_spec in enumerate(contract["outer_folds"]):
        fold = str(fold_spec["fold"])
        test_start = pd.Timestamp(fold_spec["test_start"])
        test_end = pd.Timestamp(fold_spec["test_end"])
        train_end = embargo_train_end(
            dates,
            test_start,
            pd.Timestamp(fold_spec["train_end"]),
            embargo_sessions=int(contract["decision"]["embargo_sessions"]),
            sample_every_sessions=int(contract["decision"]["sample_every_sessions"]),
        )
        training = frame.loc[
            frame["decision_date"].between(
                pd.Timestamp(fold_spec["train_start"]), train_end, inclusive="both"
            )
        ].copy()
        testing = frame.loc[
            frame["decision_date"].between(test_start, test_end, inclusive="both")
        ].copy()
        if len(training) < int(contract["training"]["minimum_groups"]):
            raise ValueError(f"{fold} has insufficient training groups")
        if testing.empty:
            raise ValueError(f"{fold} has no test groups")
        labels = None if permuted_labels is None else permuted_labels.reindex(training.index)
        bundle = _fit(
            training,
            feature_names,
            contract,
            fold=fold,
            labels=labels,
            seed_offset=seed_offset + fold_number,
        )
        probabilities = _predict(bundle, testing)
        scored = _attach_predictions(testing, probabilities)
        scored["fold"] = fold
        unique_expected = int(np.unique(np.round(scored["expected_risk_index"], 10)).size)
        coverage.append(
            {
                "fold": fold,
                "training_start": training["decision_date"].min(),
                "training_end": training["decision_date"].max(),
                "training_groups": int(len(training)),
                "class_0_count": bundle.class_counts[0],
                "class_1_count": bundle.class_counts[1],
                "class_2_count": bundle.class_counts[2],
                "class_3_count": bundle.class_counts[3],
                "test_start": testing["decision_date"].min(),
                "test_end": testing["decision_date"].max(),
                "test_groups": int(len(testing)),
                "unique_expected_risk_values": unique_expected,
                "declared_embargo_sessions": int(contract["decision"]["embargo_sessions"]),
                "intervening_decision_groups": 1,
            }
        )
        bundles.append(
            OrdinalModelBundle(
                fold=bundle.fold,
                booster=bundle.booster,
                feature_names=bundle.feature_names,
                training_groups=bundle.training_groups,
                class_counts=bundle.class_counts,
                test_frame=testing.copy(),
            )
        )
        parts.append(scored)
    return (
        pd.concat(parts, ignore_index=True).sort_values("decision_date").reset_index(drop=True),
        pd.DataFrame(coverage),
        bundles,
    )


def score_actual(
    training: pd.DataFrame,
    actual: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, OrdinalModelBundle]:
    bundle = _fit(training, feature_names, contract, fold="actual_2024_plus")
    scored = _attach_predictions(actual, _predict(bundle, actual))
    scored["fold"] = "actual_2024_plus"
    return scored, bundle


def _macro_auc(scored: pd.DataFrame) -> float:
    y = scored["oracle_state_index"].astype(int).to_numpy()
    probabilities = scored[[f"prob_{state}" for state in STATE_ORDER]].to_numpy(dtype=float)
    try:
        return float(
            roc_auc_score(
                y,
                probabilities,
                labels=list(range(len(STATE_ORDER))),
                multi_class="ovr",
                average="macro",
            )
        )
    except ValueError:
        return np.nan


def classification_metrics(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    class_rows: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []
    groups = [("pooled", scored), *list(scored.groupby("fold"))]
    for name, table in groups:
        y = table["oracle_state_index"].astype(int).to_numpy()
        predicted = table["selected_state_index"].astype(int).to_numpy()
        probabilities = table[[f"prob_{state}" for state in STATE_ORDER]].to_numpy(dtype=float)
        rows.append(
            {
                "scope": str(name),
                "groups": int(len(table)),
                "macro_ovr_auc": _macro_auc(table),
                "quadratic_weighted_kappa": float(
                    cohen_kappa_score(y, predicted, weights="quadratic")
                ),
                "macro_recall": float(
                    recall_score(y, predicted, labels=list(range(4)), average="macro", zero_division=0)
                ),
                "multiclass_log_loss": float(log_loss(y, probabilities, labels=list(range(4)))),
                "exact_state_accuracy": float(np.mean(y == predicted)),
                "mean_absolute_state_error": float(np.mean(np.abs(y - predicted))),
            }
        )
        for index, state in enumerate(STATE_ORDER):
            mask = y == index
            class_rows.append(
                {
                    "scope": str(name),
                    "state": state,
                    "support": int(mask.sum()),
                    "recall": float(np.mean(predicted[mask] == index)) if mask.any() else np.nan,
                    "mean_probability": float(probabilities[:, index].mean()),
                }
            )
        for actual_index, actual_state in enumerate(STATE_ORDER):
            for predicted_index, predicted_state in enumerate(STATE_ORDER):
                confusion_rows.append(
                    {
                        "scope": str(name),
                        "actual_state": actual_state,
                        "predicted_state": predicted_state,
                        "count": int(np.sum((y == actual_index) & (predicted == predicted_index))),
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame(class_rows), pd.DataFrame(confusion_rows)


def selection_metrics(
    selected: pd.DataFrame, contract: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fold_rows: list[dict[str, Any]] = []
    for fold, table in selected.groupby("fold"):
        selected_regret = float(table["selected_utility_regret"].mean())
        baseline_regret = float(table["baseline_utility_regret"].mean())
        fold_rows.append(
            {
                "fold": fold,
                "groups": int(len(table)),
                "selected_mean_utility_regret": selected_regret,
                "baseline_mean_utility_regret": baseline_regret,
                "utility_regret_reduction": (
                    1.0 - selected_regret / baseline_regret
                    if baseline_regret > 1e-12
                    else np.nan
                ),
                "median_utility_advantage_vs_v4_2": float(
                    table["selected_utility_advantage_vs_v4_2"].median()
                ),
                "total_utility_advantage_vs_v4_2": float(
                    table["selected_utility_advantage_vs_v4_2"].sum()
                ),
                "top_two_rate": float(table["selected_top_two"].mean()),
            }
        )
    state_rows: list[dict[str, Any]] = []
    for state in STATE_ORDER:
        table = selected.loc[selected["selected_state"].eq(state)]
        state_rows.append(
            {
                "state": state,
                "selected_groups": int(len(table)),
                "selection_share": float(len(table) / len(selected)),
                "top_two_rate": float(table["selected_top_two"].mean()) if len(table) else np.nan,
                "median_utility_advantage_vs_v4_2": (
                    float(table["selected_utility_advantage_vs_v4_2"].median())
                    if len(table)
                    else np.nan
                ),
                "total_utility_advantage_vs_v4_2": float(
                    table["selected_utility_advantage_vs_v4_2"].sum()
                ),
            }
        )
    table = selected.copy()
    table["year"] = pd.to_datetime(table["decision_date"]).dt.year
    cluster_days = int(contract["decision"]["macro_cluster_calendar_days"])
    cluster = 0
    anchor: pd.Timestamp | None = None
    mapping: dict[pd.Timestamp, int] = {}
    for date in pd.to_datetime(table["decision_date"]).sort_values():
        timestamp = pd.Timestamp(date)
        if anchor is None or (timestamp - anchor).days > cluster_days:
            cluster += 1
            anchor = timestamp
        mapping[timestamp] = cluster
    table["macro_cluster"] = pd.to_datetime(table["decision_date"]).map(mapping)
    positive = table["selected_utility_advantage_vs_v4_2"].clip(lower=0.0)
    total_positive = float(positive.sum())
    by_year = table.assign(positive=positive).groupby("year")["positive"].sum()
    by_cluster = table.assign(positive=positive).groupby("macro_cluster")["positive"].sum()
    best_year = int(by_year.idxmax()) if total_positive > 0.0 else None
    best_cluster = int(by_cluster.idxmax()) if total_positive > 0.0 else None
    concentration = pd.DataFrame(
        [
            {
                "total_utility_advantage": float(table["selected_utility_advantage_vs_v4_2"].sum()),
                "positive_utility_advantage": total_positive,
                "largest_positive_year_share": (
                    float(by_year.max() / total_positive) if total_positive > 0.0 else np.nan
                ),
                "largest_positive_cluster_share": (
                    float(by_cluster.max() / total_positive) if total_positive > 0.0 else np.nan
                ),
                "best_year": best_year,
                "best_macro_cluster": best_cluster,
                "advantage_without_best_year": float(
                    table.loc[table["year"].ne(best_year), "selected_utility_advantage_vs_v4_2"].sum()
                ),
                "advantage_without_best_cluster": float(
                    table.loc[
                        table["macro_cluster"].ne(best_cluster),
                        "selected_utility_advantage_vs_v4_2",
                    ].sum()
                ),
            }
        ]
    )
    return pd.DataFrame(fold_rows), pd.DataFrame(state_rows), concentration


def _regret_reduction(selected: pd.DataFrame) -> float:
    selected_regret = float(selected["selected_utility_regret"].mean())
    baseline_regret = float(selected["baseline_utility_regret"].mean())
    return 1.0 - selected_regret / baseline_regret if baseline_regret > 1e-12 else np.nan


def placebo_metrics(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    observed: float,
) -> pd.DataFrame:
    trials = int(contract["validation"]["placebo_trials"])
    rows: list[dict[str, Any]] = []
    original = frame["oracle_state_index"].astype(int)
    for trial in range(trials):
        rng = np.random.default_rng(int(contract["model"]["seed"]) + 1000 + trial)
        permuted = pd.Series(rng.permutation(original.to_numpy()), index=frame.index)
        scored, _, _ = score_outer_folds(
            frame,
            feature_names,
            contract,
            permuted_labels=permuted,
            seed_offset=100 + trial * 10,
        )
        placebo_reduction = _regret_reduction(scored)
        rows.append(
            {
                "trial": trial,
                "placebo_regret_reduction": placebo_reduction,
                "observed_regret_reduction": observed,
                "observed_beats_placebo": bool(observed > placebo_reduction),
            }
        )
    return pd.DataFrame(rows)


def importance_metrics(
    bundles: Sequence[OrdinalModelBundle],
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    shap_totals = pd.Series(0.0, index=list(feature_names), dtype=float)
    gain_totals = pd.Series(0.0, index=list(feature_names), dtype=float)
    for bundle in bundles:
        gain = bundle.booster.get_score(importance_type="gain")
        for feature in feature_names:
            gain_totals.loc[feature] += float(gain.get(feature, 0.0))
        matrix = xgb.DMatrix(
            bundle.test_frame[list(feature_names)],
            feature_names=list(feature_names),
            missing=np.nan,
        )
        contributions = np.asarray(
            bundle.booster.predict(matrix, pred_contribs=True, strict_shape=True),
            dtype=float,
        )
        if contributions.ndim != 3:
            raise AssertionError(f"unexpected SHAP shape {contributions.shape}")
        values = np.abs(contributions[:, :, :-1]).mean(axis=(0, 1))
        shap_totals += pd.Series(values, index=list(feature_names))
    shap_sum = float(shap_totals.sum())
    gain_sum = float(gain_totals.sum())
    feature_table = pd.DataFrame(
        {
            "feature": list(feature_names),
            "mean_abs_shap": shap_totals.to_numpy(),
            "shap_share": shap_totals.to_numpy() / shap_sum if shap_sum > 0 else np.nan,
            "gain": gain_totals.to_numpy(),
            "gain_share": gain_totals.to_numpy() / gain_sum if gain_sum > 0 else np.nan,
        }
    ).sort_values("shap_share", ascending=False)
    family_rows: list[dict[str, Any]] = []
    for family, features in contract["feature_families"].items():
        subset = feature_table.loc[feature_table["feature"].isin(features)]
        family_rows.append(
            {
                "family": str(family),
                "mean_abs_shap": float(subset["mean_abs_shap"].sum()),
                "shap_share": float(subset["shap_share"].sum()),
                "gain": float(subset["gain"].sum()),
                "gain_share": float(subset["gain_share"].sum()),
            }
        )
    return feature_table.reset_index(drop=True), pd.DataFrame(family_rows).sort_values(
        "shap_share", ascending=False
    )


def _phase1_gate(
    metrics: pd.DataFrame,
    selected: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    state_metrics: pd.DataFrame,
    concentration: pd.DataFrame,
    placebo: pd.DataFrame,
    feature_importance: pd.DataFrame,
    family_importance: pd.DataFrame,
    coverage: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    gate = contract["validation"]["phase1"]
    pooled = metrics.loc[metrics["scope"].eq("pooled")].iloc[0]
    regret_reduction = _regret_reduction(selected)
    median_advantage = float(selected["selected_utility_advantage_vs_v4_2"].median())
    positive_folds = int(fold_metrics["total_utility_advantage_vs_v4_2"].gt(0.0).sum())
    top_two_rate = float(selected["selected_top_two"].mean())
    minimum_state_count = int(state_metrics["selected_groups"].min())
    maximum_state_share = float(state_metrics["selection_share"].max())
    concentration_row = concentration.iloc[0]
    placebo_beat_rate = float(placebo["observed_beats_placebo"].mean())
    largest_feature = float(feature_importance["shap_share"].max())
    largest_family = float(family_importance["shap_share"].max())
    geometry_pass = bool(
        coverage["unique_expected_risk_values"].ge(
            int(contract["model"]["minimum_unique_expected_risk_values"])
        ).all()
    )
    checks = {
        "macro_ovr_auc": float(pooled["macro_ovr_auc"]) >= float(gate["macro_ovr_auc_min"]),
        "quadratic_weighted_kappa": float(pooled["quadratic_weighted_kappa"])
        >= float(gate["quadratic_weighted_kappa_min"]),
        "macro_recall": float(pooled["macro_recall"]) >= float(gate["macro_recall_min"]),
        "utility_regret_reduction": regret_reduction
        >= float(gate["utility_regret_reduction_min"]),
        "median_utility_advantage": median_advantage > float(gate["median_utility_advantage_min"]),
        "positive_outer_folds": positive_folds >= int(gate["positive_outer_folds_min"]),
        "top_two_rate": top_two_rate >= float(gate["top_two_rate_min"]),
        "minimum_state_selections": minimum_state_count
        >= int(gate["minimum_state_selections"]),
        "maximum_state_selection_share": maximum_state_share
        <= float(gate["maximum_state_selection_share"]),
        "probability_geometry": geometry_pass,
        "year_concentration": float(concentration_row["largest_positive_year_share"])
        <= float(gate["largest_positive_year_share_max"]),
        "cluster_concentration": float(concentration_row["largest_positive_cluster_share"])
        <= float(gate["largest_positive_cluster_share_max"]),
        "without_best_year": float(concentration_row["advantage_without_best_year"]) > 0.0,
        "without_best_cluster": float(concentration_row["advantage_without_best_cluster"]) > 0.0,
        "placebo": placebo_beat_rate >= float(gate["placebo_beat_rate_min"]),
        "single_feature_concentration": largest_feature
        <= float(gate["largest_single_feature_shap_share_max"]),
        "feature_family_concentration": largest_family
        <= float(gate["largest_feature_family_shap_share_max"]),
    }
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "macro_ovr_auc": float(pooled["macro_ovr_auc"]),
        "quadratic_weighted_kappa": float(pooled["quadratic_weighted_kappa"]),
        "macro_recall": float(pooled["macro_recall"]),
        "multiclass_log_loss": float(pooled["multiclass_log_loss"]),
        "mean_absolute_state_error": float(pooled["mean_absolute_state_error"]),
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


def run_ordinal_risk_budget_study(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    v416_contract: Mapping[str, Any],
) -> OrdinalRiskBudgetResult:
    proxy, actual, feature_names = build_ordinal_frames(
        bars, proxy_baseline_daily, actual_baseline_daily, contract, v416_contract
    )
    oof_scores, fold_coverage, bundles = score_outer_folds(proxy, feature_names, contract)
    model_metrics, class_metrics, confusion = classification_metrics(oof_scores)
    selection_by_fold, selection_by_state, concentration = selection_metrics(oof_scores, contract)
    observed_reduction = _regret_reduction(oof_scores)
    placebo = placebo_metrics(proxy, feature_names, contract, observed_reduction)
    feature_importance, family_importance = importance_metrics(
        bundles, feature_names, contract
    )
    phase1 = _phase1_gate(
        model_metrics,
        oof_scores,
        selection_by_fold,
        selection_by_state,
        concentration,
        placebo,
        feature_importance,
        family_importance,
        fold_coverage,
        contract,
    )
    training = proxy.loc[
        proxy["decision_date"].le(pd.Timestamp("2023-12-29"))
    ].copy()
    actual_scores, _ = score_actual(training, actual, feature_names, contract)

    empty_headline = pd.DataFrame()
    empty_frames: dict[str, pd.DataFrame] = {}
    if not phase1["passed"]:
        phase2 = {"passed": False, "skipped": True, "reason": "phase1_gate_failed"}
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
        oof_headline, oof_daily, oof_trades, oof_results = phase2_evidence(
            oof_scores, bars, proxy_baseline_daily, contract, actual=False
        )
        phase2 = phase2_gate(
            oof_headline,
            oof_results,
            oof_scores,
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
            actual_headline, actual_daily, actual_trades, _ = phase2_evidence(
                actual_scores, bars, actual_baseline_daily, contract, actual=True
            )
            actual_contradiction = actual_gate(actual_headline, contract)
    prospective = bool(
        phase1["passed"] and phase2["passed"] and actual_contradiction["passed"]
    )
    final_gate = {
        "passed": prospective,
        "candidate_shadow_authorized": prospective,
        "direct_promotion_authorized": False,
        "v4_2_unchanged": True,
        "telegram_unchanged": True,
        "issue_348_unchanged": True,
        "daily_feature_xgboost_path_closed_on_failure": not prospective,
    }
    return OrdinalRiskBudgetResult(
        proxy_frame=proxy,
        actual_frame=actual,
        feature_names=feature_names,
        fold_coverage=fold_coverage,
        oof_scores=oof_scores,
        actual_scores=actual_scores,
        model_metrics=model_metrics,
        class_metrics=class_metrics,
        confusion=confusion,
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
