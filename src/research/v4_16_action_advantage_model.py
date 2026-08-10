"""Strongly regularized multi-action advantage model for the QQQ strategy family.

One multi-output Ridge model combines the retained continuous VIX, VXN, RSI20,
Bollinger and QQQ-versus-VOO factors.  It estimates four discrete action returns
relative to the frozen v4.2 path.  Model family, alpha, interactions, thresholds,
actions, horizons, sampling and embargo are all fixed by contract.
"""

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

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars
from src.research.v4_14_multifactor_event_discovery import (
    _assign_macro_clusters,
    _forward_total_return,
    build_multifactor_feature_frame,
)
from src.research.v4_14_multifactor_event_policy import (
    _baseline_exact,
    _event_action_trace,
    _event_attribution,
    _run_policy,
    _run_static,
)

ACTION_KEYS = (
    "cash_defense",
    "broad_equity",
    "nasdaq_core",
    "nasdaq_acceleration",
)
BASELINE_ASSETS = ("QQQI", "QQQ", "TQQQ")


@dataclass(frozen=True)
class AdvantageModelResult:
    frame: pd.DataFrame
    feature_names: tuple[str, ...]
    target_names: tuple[str, ...]
    oof_predictions: pd.DataFrame
    fold_coefficients: pd.DataFrame
    action_metrics: pd.DataFrame
    oof_events: pd.DataFrame
    model_gate: dict[str, Any]
    actual_predictions: pd.DataFrame
    actual_events: pd.DataFrame
    actual_coefficients: pd.DataFrame


@dataclass(frozen=True)
class AdvantagePolicyResult:
    oof_results: dict[str, StrategyResult]
    actual_results: dict[str, StrategyResult]
    oof_headline: pd.DataFrame
    actual_headline: pd.DataFrame
    oof_action_trace: pd.DataFrame
    actual_action_trace: pd.DataFrame
    oof_attribution: pd.DataFrame
    actual_attribution: pd.DataFrame
    portfolio_gate: dict[str, Any]
    contradiction_gate: dict[str, Any]
    diagnostics: dict[str, Any]


def _model_pipeline(contract: Mapping[str, Any]) -> Pipeline:
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


def build_action_advantage_frame(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    """Build continuous factors, frozen interactions and v4.2-relative labels."""

    frame = build_multifactor_feature_frame(bars, proxy_baseline_daily).copy()
    frame["qqq_rsi20_centered"] = (frame["qqq_rsi20"] - 50.0) / 50.0
    feature_names = [str(value) for value in contract["base_features"]]
    for raw in contract["interactions"]:
        name = str(raw["name"])
        left = str(raw["left"])
        right = str(raw["right"])
        frame[name] = pd.to_numeric(frame[left], errors="coerce") * pd.to_numeric(
            frame[right], errors="coerce"
        )
        feature_names.append(name)

    baseline_return = proxy_baseline_daily["net_return"].reindex(frame.index)
    baseline_10d = _forward_total_return(baseline_return, 10)
    baseline_5d = _forward_total_return(baseline_return, 5)
    acceleration_daily = (
        0.25 * frame["qqq_next_open_return"] + 0.75 * frame["tqqq_next_open_return"]
    )
    acceleration_5d = _forward_total_return(acceleration_daily, 5)
    label_cost = float(contract["boundaries"]["label_round_trip_cost_bps"]) / 10_000.0
    frame["cash_defense_advantage_10d"] = frame["forward_bil_10d"] - baseline_10d - label_cost
    frame["broad_equity_advantage_10d"] = frame["forward_voo_10d"] - baseline_10d - label_cost
    frame["nasdaq_core_advantage_10d"] = frame["forward_qqq_10d"] - baseline_10d - label_cost
    frame["nasdaq_acceleration_advantage_5d"] = acceleration_5d - baseline_5d - label_cost
    target_names = tuple(str(contract["actions"][action]["target"]) for action in ACTION_KEYS)
    frame["global_training_sample"] = (
        (np.arange(len(frame)) - int(contract["training"]["global_anchor_position"]))
        % int(contract["training"]["sample_every_sessions"])
    ).eq(0)
    return frame, tuple(feature_names), target_names


def _fit_model(
    training: pd.DataFrame,
    feature_names: Sequence[str],
    target_names: Sequence[str],
    contract: Mapping[str, Any],
) -> Pipeline:
    usable = training.dropna(subset=list(target_names)).copy()
    if len(usable) < int(contract["training"]["minimum_training_samples"]):
        raise ValueError("insufficient non-overlapping training samples")
    model = _model_pipeline(contract)
    model.fit(usable[list(feature_names)], usable[list(target_names)])
    return model


def _coefficient_frame(
    model: Pipeline,
    *,
    fold: str,
    feature_names: Sequence[str],
    target_names: Sequence[str],
) -> pd.DataFrame:
    ridge: Ridge = model.named_steps["model"]
    coefficient = np.asarray(ridge.coef_, dtype=float)
    rows: list[dict[str, Any]] = []
    for target_position, target in enumerate(target_names):
        for feature_position, feature in enumerate(feature_names):
            rows.append(
                {
                    "fold": fold,
                    "target": target,
                    "feature": feature,
                    "coefficient": float(coefficient[target_position, feature_position]),
                }
            )
    return pd.DataFrame(rows)


def _embargo_train_end(
    index: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    declared_train_end: pd.Timestamp,
    embargo_sessions: int,
) -> pd.Timestamp:
    location = int(index.searchsorted(test_start, side="left"))
    embargo_location = max(location - embargo_sessions - 1, 0)
    return min(declared_train_end, pd.Timestamp(index[embargo_location]))


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
    declared_train_end = pd.Timestamp(fold_specification["train_end"])
    train_end = _embargo_train_end(
        frame.index,
        test_start,
        declared_train_end,
        int(contract["training"]["embargo_sessions"]),
    )
    training = frame.loc[train_start:train_end].copy()
    training = training.loc[training["global_training_sample"].astype(bool)]
    model = _fit_model(training, feature_names, target_names, contract)
    test = frame.loc[test_start:test_end].copy()
    predictions = np.asarray(model.predict(test[list(feature_names)]), dtype=float)
    output = test[list(target_names)].copy()
    for position, action in enumerate(ACTION_KEYS):
        output[f"predicted_{action}"] = predictions[:, position]
    output["fold"] = fold
    output["training_start"] = training.index.min()
    output["training_end"] = training.index.max()
    output["training_samples"] = int(training.dropna(subset=list(target_names)).shape[0])
    output["qqq_distance_ma20"] = test["qqq_distance_ma20"]
    output["qqq_distance_ma200"] = test["qqq_distance_ma200"]
    output["voo_distance_ma200"] = test["voo_distance_ma200"]
    output["vol_max_percentile_252"] = test["vol_max_percentile_252"]
    return output, _coefficient_frame(
        model,
        fold=fold,
        feature_names=feature_names,
        target_names=target_names,
    )


def _action_eligible(
    predictions: pd.DataFrame,
    action: str,
    contract: Mapping[str, Any],
) -> pd.Series:
    if action in {"cash_defense", "nasdaq_core"}:
        return pd.Series(True, index=predictions.index)
    eligibility = contract["eligibility"]
    if action == "broad_equity":
        return predictions["voo_distance_ma200"].ge(0.0)
    if action == "nasdaq_acceleration":
        return (
            predictions["qqq_distance_ma200"].gt(0.0)
            & predictions["qqq_distance_ma20"].le(
                float(eligibility["acceleration_qqq_distance_ma20_max"])
            )
            & predictions["vol_max_percentile_252"].le(
                float(eligibility["acceleration_vol_percentile_max"])
            )
        )
    raise ValueError(f"unsupported action eligibility: {action}")


def select_advantage_events(
    predictions: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    sample: str,
) -> pd.DataFrame:
    """Convert fresh score crossings into non-overlapping discrete action events."""

    pred_columns = {action: f"predicted_{action}" for action in ACTION_KEYS}
    score = predictions[[pred_columns[action] for action in ACTION_KEYS]].copy()
    score.columns = list(ACTION_KEYS)
    for action in ACTION_KEYS:
        score.loc[~_action_eligible(predictions, action, contract), action] = -np.inf
    top_action = score.idxmax(axis=1)
    top_score = score.max(axis=1)
    second_score = score.apply(
        lambda row: float(np.partition(row.to_numpy(dtype=float), -2)[-2]),
        axis=1,
    )
    qualifies = (
        top_score.ge(float(contract["training"]["advantage_threshold"]))
        & (top_score - second_score).ge(float(contract["training"]["action_margin_threshold"]))
        & np.isfinite(top_score)
    )
    previous_same_qualified = qualifies.shift(1, fill_value=False) & top_action.eq(
        top_action.shift(1)
    )
    fresh = qualifies & ~previous_same_qualified
    next_allowed = 0
    rows: list[dict[str, Any]] = []
    index = predictions.index
    cooldown = int(contract["training"]["cooldown_sessions"])
    for location, is_fresh in enumerate(fresh.to_numpy(dtype=bool)):
        if not is_fresh or location < next_allowed:
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


def _coefficient_cosine(coefficients: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    pivot = coefficients.pivot_table(
        index="fold", columns=["target", "feature"], values="coefficient"
    ).sort_index(axis=1)
    rows: list[dict[str, Any]] = []
    for left, right in combinations(pivot.index, 2):
        a = pivot.loc[left].to_numpy(dtype=float)
        b = pivot.loc[right].to_numpy(dtype=float)
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        cosine = float(np.dot(a, b) / denominator) if denominator > 1e-18 else np.nan
        rows.append({"fold_left": left, "fold_right": right, "cosine": cosine})
    table = pd.DataFrame(rows)
    median = float(table["cosine"].median()) if not table.empty else np.nan
    return table, median


def _model_metrics(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    coefficients: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in ACTION_KEYS:
        target = str(contract["actions"][action]["target"])
        prediction = predictions[f"predicted_{action}"]
        realized = predictions[target]
        aligned = pd.concat([prediction, realized], axis=1).dropna()
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
    action_metrics = pd.DataFrame(rows)
    cosine_table, cosine_median = _coefficient_cosine(coefficients)
    clustered = _assign_macro_clusters(
        events,
        int(contract["training"]["macro_cluster_calendar_days"]),
    )
    positive_cluster = (
        clustered.groupby("macro_cluster_id")["realized_advantage"].sum().clip(lower=0.0)
        if not clustered.empty
        else pd.Series(dtype=float)
    )
    total_positive = float(positive_cluster.sum())
    cluster_share = float(positive_cluster.max() / total_positive) if total_positive > 0.0 else 1.0
    pooled_unconditional = float(
        pd.concat(
            [predictions[str(contract["actions"][action]["target"])] for action in ACTION_KEYS],
            ignore_index=True,
        )
        .dropna()
        .gt(0.0)
        .mean()
    )
    triggered_precision = float(events["win"].mean()) if not events.empty else np.nan
    median_triggered = float(events["realized_advantage"].median()) if not events.empty else np.nan
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
    thresholds = contract["validation"]["model_gate"]
    passing_ic = int(action_metrics["spearman_ic"].ge(float(thresholds["action_ic_min"])).sum())
    positive_spreads = int(action_metrics["top_bottom_quintile_spread"].gt(0.0).sum())
    checks = {
        "actions_passing_ic": passing_ic >= int(thresholds["actions_passing_ic_min"]),
        "actions_positive_spread": positive_spreads
        >= int(thresholds["actions_positive_quintile_spread_min"]),
        "triggered_precision_lift": np.isfinite(triggered_precision)
        and triggered_precision - pooled_unconditional
        >= float(thresholds["triggered_precision_lift_min"]),
        "median_triggered_advantage": np.isfinite(median_triggered)
        and median_triggered > float(thresholds["median_triggered_advantage_min"]),
        "minimum_macro_clusters": int(clustered["macro_cluster_id"].nunique())
        >= int(thresholds["minimum_macro_clusters"]),
        "cluster_concentration": cluster_share
        <= float(thresholds["largest_positive_cluster_share_max"]),
        "coefficient_stability": np.isfinite(cosine_median)
        and cosine_median >= float(thresholds["coefficient_cosine_similarity_median_min"]),
        "without_best_year": np.isfinite(without_best_year) and without_best_year >= 0.0,
    }
    gate = {
        "checks": checks,
        "metrics": {
            "actions_passing_ic": passing_ic,
            "actions_positive_quintile_spread": positive_spreads,
            "pooled_unconditional_positive_rate": pooled_unconditional,
            "triggered_precision": triggered_precision,
            "triggered_precision_lift": triggered_precision - pooled_unconditional
            if np.isfinite(triggered_precision)
            else np.nan,
            "median_triggered_advantage": median_triggered,
            "macro_clusters": int(clustered["macro_cluster_id"].nunique()),
            "largest_positive_cluster_share": cluster_share,
            "coefficient_cosine_similarity_median": cosine_median,
            "triggered_advantage_without_best_year": without_best_year,
        },
        "passed": bool(all(checks.values())),
    }
    return action_metrics, cosine_table, gate


def run_action_advantage_model(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> AdvantageModelResult:
    frame, feature_names, target_names = build_action_advantage_frame(
        bars, proxy_baseline_daily, contract
    )
    prediction_parts: list[pd.DataFrame] = []
    coefficient_parts: list[pd.DataFrame] = []
    for fold in contract["outer_folds"]:
        prediction, coefficient = _predict_fold(frame, feature_names, target_names, contract, fold)
        prediction_parts.append(prediction)
        coefficient_parts.append(coefficient)
    oof = pd.concat(prediction_parts).sort_index()
    coefficients = pd.concat(coefficient_parts, ignore_index=True)
    oof_events = select_advantage_events(oof, contract, sample="oof")
    action_metrics, cosine_table, model_gate = _model_metrics(
        oof, oof_events, coefficients, contract
    )
    model_gate["coefficient_cosine_pairs"] = cosine_table.to_dict(orient="records")

    actual_start = max(
        pd.Timestamp(contract["data"]["actual_product_start"]),
        frame.index.min(),
    )
    train_start = pd.Timestamp("2011-01-03")
    train_end = _embargo_train_end(
        frame.index,
        actual_start,
        pd.Timestamp("2023-12-29"),
        int(contract["training"]["embargo_sessions"]),
    )
    training = frame.loc[train_start:train_end]
    training = training.loc[training["global_training_sample"].astype(bool)]
    actual_model = _fit_model(training, feature_names, target_names, contract)
    actual = frame.loc[actual_start:].copy()
    prediction = np.asarray(actual_model.predict(actual[list(feature_names)]), dtype=float)
    actual_output = actual[list(target_names)].copy()
    for position, action in enumerate(ACTION_KEYS):
        actual_output[f"predicted_{action}"] = prediction[:, position]
    actual_output["fold"] = "actual_2024_plus"
    actual_output["qqq_distance_ma20"] = actual["qqq_distance_ma20"]
    actual_output["qqq_distance_ma200"] = actual["qqq_distance_ma200"]
    actual_output["voo_distance_ma200"] = actual["voo_distance_ma200"]
    actual_output["vol_max_percentile_252"] = actual["vol_max_percentile_252"]
    actual_events = select_advantage_events(actual_output, contract, sample="actual_2024_plus")
    actual_coefficients = _coefficient_frame(
        actual_model,
        fold="actual_2024_plus",
        feature_names=feature_names,
        target_names=target_names,
    )
    return AdvantageModelResult(
        frame=frame,
        feature_names=feature_names,
        target_names=target_names,
        oof_predictions=oof,
        fold_coefficients=coefficients,
        action_metrics=action_metrics,
        oof_events=oof_events,
        model_gate=model_gate,
        actual_predictions=actual_output,
        actual_events=actual_events,
        actual_coefficients=actual_coefficients,
    )


def _portfolio_gate(
    results: Mapping[str, StrategyResult],
    attribution: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["portfolio_shadow_gate"]
    baseline = results["frozen_v4_2"]
    policy = results["full_event_policy"]
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
    relative_years: dict[str, float] = {}
    for year, group in aligned.groupby(aligned.index.year):
        relative_years[str(int(year))] = float(
            (1.0 + group["policy"]).prod() - (1.0 + group["baseline"]).prod()
        )
    positive_year_rate = float(np.mean([value > 0.0 for value in relative_years.values()]))
    year_series = pd.Series(relative_years, dtype=float)
    without_best_year = (
        float(year_series.drop(index=year_series.idxmax()).sum())
        if len(year_series) > 1
        else np.nan
    )
    positive = attribution.loc[attribution["relative_return"].gt(0.0)].copy()
    total_positive = float(positive["relative_return"].sum()) if len(positive) else 0.0
    event_share = (
        float(positive["relative_return"].max() / total_positive) if total_positive > 0.0 else 1.0
    )
    family_positive = positive.groupby("event_family")["relative_return"].sum()
    family_share = float(family_positive.max() / total_positive) if total_positive > 0.0 else 1.0
    event_cluster = _assign_macro_clusters(
        events,
        int(contract["training"]["macro_cluster_calendar_days"]),
    )
    attributed = attribution.merge(
        event_cluster[["event_id", "macro_cluster_id"]], on="event_id", how="left"
    )
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
        comparator = results[f"ablation_{action}"]
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
    checks = {
        "cagr": cagr_delta_pp >= float(threshold["cagr_improvement_vs_v4_2_pp_min"]),
        "max_drawdown": drawdown_worsening_pp <= float(threshold["max_drawdown_worsening_pp_max"]),
        "calmar": calmar_delta >= float(threshold["calmar_improvement_vs_v4_2_min"]),
        "sortino": float(policy.metrics["sortino"]) >= float(baseline.metrics["sortino"]),
        "positive_years": positive_year_rate >= float(threshold["positive_calendar_year_rate_min"]),
        "family_concentration": family_share
        <= float(threshold["largest_family_positive_share_max"]),
        "event_concentration": event_share <= float(threshold["largest_event_positive_share_max"]),
        "turnover": turnover_increase <= float(threshold["turnover_increase_max"]),
        "without_best_year": np.isfinite(without_best_year) and without_best_year >= 0.0,
        "without_best_cluster": np.isfinite(without_best_cluster) and without_best_cluster >= 0.0,
        **{f"beats_{action}_ablation": wins >= 2 for action, wins in ablation_wins.items()},
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_pp": cagr_delta_pp,
            "max_drawdown_worsening_pp": drawdown_worsening_pp,
            "calmar_delta": calmar_delta,
            "positive_calendar_year_rate": positive_year_rate,
            "calendar_year_relative_returns": relative_years,
            "relative_return_without_best_year": without_best_year,
            "largest_family_positive_share": family_share,
            "largest_event_positive_share": event_share,
            "relative_return_without_best_cluster": without_best_cluster,
            "turnover_increase": turnover_increase,
            "ablation_win_counts": ablation_wins,
        },
        "passed": bool(all(checks.values())),
    }


def run_action_advantage_policy(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    model_result: AdvantageModelResult,
    contract: Mapping[str, Any],
) -> AdvantagePolicyResult:
    """Evaluate OOF and actual fixed-action policies from Ridge score crossings."""

    frame = model_result.frame
    oof_start = pd.Timestamp(contract["outer_folds"][0]["test_start"])
    oof_end = pd.Timestamp(contract["outer_folds"][-1]["test_end"])
    oof_index = proxy_baseline_daily.index[
        (proxy_baseline_daily.index >= oof_start) & (proxy_baseline_daily.index <= oof_end)
    ]
    oof_index = oof_index.intersection(frame.index).sort_values()
    baseline_oof = _baseline_exact(proxy_baseline_daily, oof_index, contract)
    oof_trace = _event_action_trace(oof_index, model_result.oof_events, contract)
    voo_return = frame["voo_next_open_return"].reindex(oof_index)
    cash_return = frame["bil_next_open_return"].reindex(oof_index)
    oof_results: dict[str, StrategyResult] = {
        "frozen_v4_2": baseline_oof,
        "full_event_policy": _run_policy(
            proxy_baseline_daily.reindex(oof_index),
            voo_return,
            cash_return,
            oof_trace,
            contract,
            name="full_event_policy",
            proxy_mode=True,
        ),
    }
    for action in ACTION_KEYS:
        trace = _event_action_trace(
            oof_index,
            model_result.oof_events,
            contract,
            include_families=[action],
        )
        oof_results[f"ablation_{action}"] = _run_policy(
            proxy_baseline_daily.reindex(oof_index),
            voo_return,
            cash_return,
            trace,
            contract,
            name=f"ablation_{action}",
            proxy_mode=True,
        )
    oof_results["buy_hold_QQQ"] = _run_static(
        proxy_baseline_daily.reindex(oof_index),
        voo_return,
        cash_return,
        contract,
        name="buy_hold_QQQ",
        weights={"QQQ": 1.0},
    )
    oof_results["buy_hold_VOO"] = _run_static(
        proxy_baseline_daily.reindex(oof_index),
        voo_return,
        cash_return,
        contract,
        name="buy_hold_VOO",
        weights={"VOO": 1.0},
    )
    oof_results["static_QQQ_TQQQ_25_75"] = _run_static(
        proxy_baseline_daily.reindex(oof_index),
        voo_return,
        cash_return,
        contract,
        name="static_QQQ_TQQQ_25_75",
        weights={"QQQ": 0.25, "TQQQ": 0.75},
    )
    oof_attribution = _event_attribution(oof_results["full_event_policy"], baseline_oof)
    portfolio_gate = _portfolio_gate(
        oof_results, oof_attribution, model_result.oof_events, contract
    )

    qqqi = _normalise_bars(bars["QQQI"], "QQQI")
    sgov = _normalise_bars(bars["SGOV"], "SGOV")
    voo = _normalise_bars(bars["VOO"], "VOO")
    actual_start = max(
        pd.Timestamp(contract["data"]["actual_product_start"]),
        actual_baseline_daily.index.min(),
    )
    actual_index = actual_baseline_daily.index[actual_baseline_daily.index >= actual_start]
    actual_index = (
        actual_index.intersection(qqqi.index)
        .intersection(sgov.index)
        .intersection(voo.index)
        .sort_values()
    )
    baseline_actual = _baseline_exact(actual_baseline_daily, actual_index, contract)
    actual_trace = _event_action_trace(actual_index, model_result.actual_events, contract)
    actual_voo = voo["open"].shift(-1).div(voo["open"]).sub(1.0).reindex(actual_index)
    actual_cash = sgov["open"].shift(-1).div(sgov["open"]).sub(1.0).reindex(actual_index)
    actual_results: dict[str, StrategyResult] = {
        "frozen_v4_2": baseline_actual,
        "full_event_policy": _run_policy(
            actual_baseline_daily.reindex(actual_index),
            actual_voo,
            actual_cash,
            actual_trace,
            contract,
            name="full_event_policy",
            proxy_mode=False,
        ),
    }
    for action in ACTION_KEYS:
        trace = _event_action_trace(
            actual_index,
            model_result.actual_events,
            contract,
            include_families=[action],
        )
        actual_results[f"ablation_{action}"] = _run_policy(
            actual_baseline_daily.reindex(actual_index),
            actual_voo,
            actual_cash,
            trace,
            contract,
            name=f"ablation_{action}",
            proxy_mode=False,
        )
    actual_attribution = _event_attribution(actual_results["full_event_policy"], baseline_actual)
    oof_headline = pd.DataFrame(
        [dict(result.metrics) for result in oof_results.values()]
    ).set_index("strategy")
    actual_headline = pd.DataFrame(
        [dict(result.metrics) for result in actual_results.values()]
    ).set_index("strategy")
    threshold = float(
        contract["validation"]["portfolio_shadow_gate"]["actual_max_drawdown_worsening_pp_max"]
    )
    actual_base = actual_results["frozen_v4_2"]
    actual_policy = actual_results["full_event_policy"]
    actual_cagr_delta = float(actual_policy.metrics["cagr"] - actual_base.metrics["cagr"])
    actual_calmar_delta = float(actual_policy.metrics["calmar"] - actual_base.metrics["calmar"])
    actual_drawdown_worsening_pp = max(
        0.0,
        float(
            (actual_base.metrics["max_drawdown"] - actual_policy.metrics["max_drawdown"]) * 100.0
        ),
    )
    contradiction_checks = {
        "cagr_and_calmar_not_both_negative": not (
            actual_cagr_delta < 0.0 and actual_calmar_delta < 0.0
        ),
        "max_drawdown": actual_drawdown_worsening_pp <= threshold,
    }
    contradiction_gate = {
        "checks": contradiction_checks,
        "metrics": {
            "actual_cagr_delta": actual_cagr_delta,
            "actual_calmar_delta": actual_calmar_delta,
            "actual_drawdown_worsening_pp": actual_drawdown_worsening_pp,
        },
        "passed": bool(all(contradiction_checks.values())),
    }
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "oof_observations": int(len(oof_index)),
        "oof_events": int(len(model_result.oof_events)),
        "actual_observations": int(len(actual_index)),
        "actual_events": int(len(model_result.actual_events)),
        "portfolio_gate": portfolio_gate,
        "contradiction_gate": contradiction_gate,
        "shadow_candidate_authorized": bool(
            model_result.model_gate["passed"]
            and portfolio_gate["passed"]
            and contradiction_gate["passed"]
        ),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return AdvantagePolicyResult(
        oof_results=oof_results,
        actual_results=actual_results,
        oof_headline=oof_headline,
        actual_headline=actual_headline,
        oof_action_trace=oof_trace,
        actual_action_trace=actual_trace,
        oof_attribution=oof_attribution,
        actual_attribution=actual_attribution,
        portfolio_gate=portfolio_gate,
        contradiction_gate=contradiction_gate,
        diagnostics=diagnostics,
    )
