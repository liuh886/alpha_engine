"""Adjacent-edge XGBoost fitting and Phase 1 evidence for v4.24."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, roc_auc_score

from src.research.v4_24_xgb_adjacent_path_data import EDGE_ORDER, STATE_ORDER


@dataclass(frozen=True)
class EdgeModelBundle:
    edge: str
    booster: xgb.Booster
    feature_names: tuple[str, ...]
    training_groups: int
    positive_rate: float


def embargo_train_end(
    index: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    declared_train_end: pd.Timestamp,
    *,
    embargo_sessions: int,
    sample_every_sessions: int,
) -> pd.Timestamp:
    """Translate a trading-session embargo onto a non-overlapping decision grid."""

    location = int(index.searchsorted(test_start, side="left"))
    embargo_groups = int(ceil(embargo_sessions / sample_every_sessions))
    location = max(location - embargo_groups - 1, 0)
    return min(declared_train_end, pd.Timestamp(index[location]))


def _params(contract: Mapping[str, Any], seed_offset: int) -> dict[str, Any]:
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
        "seed": int(model["seed"]) + int(seed_offset),
        "nthread": int(model.get("nthread", 2)),
        "verbosity": 0,
    }


def _edge_spec(contract: Mapping[str, Any], edge: str) -> Mapping[str, Any]:
    for specification in contract["states"]["edges"]:
        if str(specification["edge"]) == edge:
            return specification
    raise KeyError(edge)


def fit_edge_model(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    *,
    edge: str,
    labels: pd.Series | None = None,
) -> EdgeModelBundle:
    label_column = f"label_{edge}"
    y = (
        pd.to_numeric(frame[label_column], errors="raise")
        if labels is None
        else pd.to_numeric(labels.reindex(frame.index), errors="raise")
    )
    if y.nunique() < 2:
        raise ValueError(f"{edge} training labels contain one class")
    matrix = xgb.DMatrix(
        frame[list(feature_names)],
        label=y.to_numpy(dtype=float),
        feature_names=list(feature_names),
        missing=np.nan,
    )
    specification = _edge_spec(contract, edge)
    booster = xgb.train(
        _params(contract, int(specification["seed_offset"])),
        matrix,
        num_boost_round=int(contract["model"]["boosting_rounds"]),
    )
    return EdgeModelBundle(
        edge=edge,
        booster=booster,
        feature_names=tuple(feature_names),
        training_groups=int(len(frame)),
        positive_rate=float(y.mean()),
    )


def predict_edge(bundle: EdgeModelBundle, frame: pd.DataFrame) -> np.ndarray:
    matrix = xgb.DMatrix(
        frame[list(bundle.feature_names)],
        feature_names=list(bundle.feature_names),
        missing=np.nan,
    )
    return np.asarray(bundle.booster.predict(matrix), dtype=float)


def score_outer_folds(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    list[tuple[str, str, EdgeModelBundle, pd.DataFrame]],
]:
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["decision_date"].unique())))
    scored_parts: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    bundles: list[tuple[str, str, EdgeModelBundle, pd.DataFrame]] = []
    for fold_spec in contract["outer_folds"]:
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
        testing["fold"] = fold
        for edge in EDGE_ORDER:
            bundle = fit_edge_model(training, feature_names, contract, edge=edge)
            testing[f"prob_{edge}"] = predict_edge(bundle, testing)
            bundles.append((fold, edge, bundle, testing.copy()))
            coverage_rows.append(
                {
                    "fold": fold,
                    "edge": edge,
                    "training_start": training["decision_date"].min(),
                    "training_end": training["decision_date"].max(),
                    "training_groups": int(len(training)),
                    "training_positive_rate": bundle.positive_rate,
                    "test_start": testing["decision_date"].min(),
                    "test_end": testing["decision_date"].max(),
                    "test_groups": int(len(testing)),
                    "declared_embargo_sessions": int(
                        contract["decision"]["embargo_sessions"]
                    ),
                    "intervening_decision_groups": 1,
                }
            )
        scored_parts.append(testing)
    scored = pd.concat(scored_parts, ignore_index=True).sort_values("decision_date")
    return scored, pd.DataFrame(coverage_rows), bundles


def score_actual(
    training: pd.DataFrame,
    actual: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, list[tuple[str, EdgeModelBundle, pd.DataFrame]]]:
    output = actual.copy()
    bundles: list[tuple[str, EdgeModelBundle, pd.DataFrame]] = []
    for edge in EDGE_ORDER:
        bundle = fit_edge_model(training, feature_names, contract, edge=edge)
        output[f"prob_{edge}"] = predict_edge(bundle, output)
        bundles.append((edge, bundle, output.copy()))
    output["fold"] = "actual_2024_plus"
    return output, bundles


def select_ordinal_state(
    scored: pd.DataFrame, contract: Mapping[str, Any]
) -> pd.DataFrame:
    threshold = float(contract["decision"]["probability_threshold"])
    rows: list[dict[str, Any]] = []
    for raw in scored.sort_values("decision_date").to_dict(orient="records"):
        selected_index = 0
        edge_trace: list[str] = []
        for position, edge in enumerate(EDGE_ORDER):
            probability = float(raw[f"prob_{edge}"])
            passed = probability >= threshold
            edge_trace.append(f"{edge}:{probability:.8f}:{int(passed)}")
            if position != selected_index or not passed:
                break
            selected_index += 1
        state = STATE_ORDER[selected_index]
        state_utilities = {
            candidate: float(raw[f"{candidate}_path_utility"])
            for candidate in STATE_ORDER
        }
        oracle = max([*state_utilities.values(), float(raw["baseline_path_utility"])])
        ordered_states = sorted(
            STATE_ORDER,
            key=lambda candidate: (
                state_utilities[candidate],
                STATE_ORDER.index(candidate),
            ),
            reverse=True,
        )
        row = dict(raw)
        row.update(
            {
                "selected_state": state,
                "edge_trace": "|".join(edge_trace),
                "selected_terminal_return": float(
                    raw[f"{state}_terminal_return"]
                ),
                "selected_mae": float(raw[f"{state}_mae"]),
                "selected_path_utility": state_utilities[state],
                "selected_utility_rank": int(ordered_states.index(state) + 1),
                "selected_top_two": bool(ordered_states.index(state) < 2),
                "selected_utility_advantage_vs_v4_2": float(
                    state_utilities[state] - float(raw["baseline_path_utility"])
                ),
                "selected_utility_regret": float(oracle - state_utilities[state]),
                "baseline_utility_regret": float(
                    oracle - float(raw["baseline_path_utility"])
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("decision_date").reset_index(drop=True)


def _safe_auc(labels: pd.Series, probabilities: pd.Series) -> float:
    y = pd.to_numeric(labels, errors="coerce")
    p = pd.to_numeric(probabilities, errors="coerce")
    mask = y.notna() & p.notna()
    if y.loc[mask].nunique() < 2:
        return np.nan
    return float(roc_auc_score(y.loc[mask], p.loc[mask]))


def edge_metrics(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for edge in EDGE_ORDER:
        y = pd.to_numeric(scored[f"label_{edge}"], errors="coerce")
        p = pd.to_numeric(scored[f"prob_{edge}"], errors="coerce")
        prediction = p.ge(0.50).astype(int)
        rows.append(
            {
                "edge": edge,
                "groups": int(len(scored)),
                "positive_rate": float(y.mean()),
                "roc_auc": _safe_auc(y, p),
                "balanced_accuracy": float(balanced_accuracy_score(y, prediction)),
                "brier_score": float(brier_score_loss(y, p)),
            }
        )
        for fold, table in scored.groupby("fold"):
            fy = pd.to_numeric(table[f"label_{edge}"], errors="coerce")
            fp = pd.to_numeric(table[f"prob_{edge}"], errors="coerce")
            predicted = fp.ge(0.50).astype(int)
            fold_rows.append(
                {
                    "fold": fold,
                    "edge": edge,
                    "groups": int(len(table)),
                    "positive_rate": float(fy.mean()),
                    "roc_auc": _safe_auc(fy, fp),
                    "balanced_accuracy": float(
                        balanced_accuracy_score(fy, predicted)
                    ),
                    "brier_score": float(brier_score_loss(fy, fp)),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(fold_rows)


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
                "top_two_rate": (
                    float(table["selected_top_two"].mean()) if len(table) else np.nan
                ),
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
    by_cluster = (
        table.assign(positive=positive)
        .groupby("macro_cluster")["positive"]
        .sum()
    )
    best_year = int(by_year.idxmax()) if total_positive > 0.0 else None
    best_cluster = int(by_cluster.idxmax()) if total_positive > 0.0 else None
    concentration = pd.DataFrame(
        [
            {
                "total_utility_advantage": float(
                    table["selected_utility_advantage_vs_v4_2"].sum()
                ),
                "positive_utility_advantage": total_positive,
                "largest_positive_year_share": (
                    float(by_year.max() / total_positive)
                    if total_positive > 0.0
                    else np.nan
                ),
                "largest_positive_cluster_share": (
                    float(by_cluster.max() / total_positive)
                    if total_positive > 0.0
                    else np.nan
                ),
                "best_year": best_year,
                "best_macro_cluster": best_cluster,
                "advantage_without_best_year": float(
                    table.loc[
                        table["year"].ne(best_year),
                        "selected_utility_advantage_vs_v4_2",
                    ].sum()
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


def placebo_metrics(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
    observed_regret_reduction: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base_seed = int(contract["model"]["seed"])
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["decision_date"].unique())))
    for trial in range(int(contract["validation"]["placebo_trials"])):
        rng = np.random.default_rng(base_seed + 1000 + trial)
        scored_parts: list[pd.DataFrame] = []
        for fold_spec in contract["outer_folds"]:
            test_start = pd.Timestamp(fold_spec["test_start"])
            train_end = embargo_train_end(
                dates,
                test_start,
                pd.Timestamp(fold_spec["train_end"]),
                embargo_sessions=int(contract["decision"]["embargo_sessions"]),
                sample_every_sessions=int(
                    contract["decision"]["sample_every_sessions"]
                ),
            )
            training = frame.loc[
                frame["decision_date"].between(
                    pd.Timestamp(fold_spec["train_start"]),
                    train_end,
                    inclusive="both",
                )
            ].copy()
            testing = frame.loc[
                frame["decision_date"].between(
                    test_start,
                    pd.Timestamp(fold_spec["test_end"]),
                    inclusive="both",
                )
            ].copy()
            testing["fold"] = str(fold_spec["fold"])
            for edge in EDGE_ORDER:
                values = training[f"label_{edge}"].to_numpy(copy=True)
                rng.shuffle(values)
                labels = pd.Series(values, index=training.index)
                bundle = fit_edge_model(
                    training,
                    feature_names,
                    contract,
                    edge=edge,
                    labels=labels,
                )
                testing[f"prob_{edge}"] = predict_edge(bundle, testing)
            scored_parts.append(testing)
        selected = select_ordinal_state(pd.concat(scored_parts, ignore_index=True), contract)
        selected_regret = float(selected["selected_utility_regret"].mean())
        baseline_regret = float(selected["baseline_utility_regret"].mean())
        reduction = (
            1.0 - selected_regret / baseline_regret
            if baseline_regret > 1e-12
            else np.nan
        )
        rows.append(
            {
                "trial": trial,
                "placebo_utility_regret_reduction": reduction,
                "observed_utility_regret_reduction": observed_regret_reduction,
                "observed_beats_placebo": bool(
                    np.isfinite(reduction) and observed_regret_reduction > reduction
                ),
            }
        )
    return pd.DataFrame(rows)


def importance_metrics(
    bundles: Sequence[tuple[str, str, EdgeModelBundle, pd.DataFrame]],
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for fold, edge, bundle, testing in bundles:
        matrix = xgb.DMatrix(
            testing[list(feature_names)],
            feature_names=list(feature_names),
            missing=np.nan,
        )
        contributions = np.asarray(
            bundle.booster.predict(matrix, pred_contribs=True), dtype=float
        )[:, :-1]
        gain = bundle.booster.get_score(importance_type="gain")
        for position, feature in enumerate(feature_names):
            rows.append(
                {
                    "fold": fold,
                    "edge": edge,
                    "feature": feature,
                    "gain": float(gain.get(feature, 0.0)),
                    "mean_abs_shap": float(np.abs(contributions[:, position]).mean()),
                }
            )
    detail = pd.DataFrame(rows)
    feature_total = detail.groupby("feature", as_index=False).agg(
        gain=("gain", "sum"), mean_abs_shap=("mean_abs_shap", "mean")
    )
    shap_sum = float(feature_total["mean_abs_shap"].sum())
    feature_total["shap_share"] = (
        feature_total["mean_abs_shap"] / shap_sum if shap_sum > 0.0 else np.nan
    )
    family_map: dict[str, str] = {}
    for family, members in contract["feature_families"].items():
        for feature in members:
            family_map[str(feature)] = str(family)
    feature_total["family"] = feature_total["feature"].map(family_map)
    if feature_total["family"].isna().any():
        missing = feature_total.loc[feature_total["family"].isna(), "feature"].tolist()
        raise AssertionError(f"feature family missing: {missing}")
    family = feature_total.groupby("family", as_index=False).agg(
        mean_abs_shap=("mean_abs_shap", "sum"), gain=("gain", "sum")
    )
    family["shap_share"] = (
        family["mean_abs_shap"] / shap_sum if shap_sum > 0.0 else np.nan
    )
    return (
        feature_total.sort_values("shap_share", ascending=False).reset_index(drop=True),
        family.sort_values("shap_share", ascending=False).reset_index(drop=True),
    )
