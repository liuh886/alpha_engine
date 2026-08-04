from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.research.etf_rotation_experiment import _normalise_bars, _return_metrics
from src.research.v4_21_state2_intraday_preflight import build_opening_alignment


@dataclass(frozen=True)
class IntradayPilotResult:
    frame: pd.DataFrame
    feature_names: tuple[str, ...]
    predictions: pd.DataFrame
    fold_coverage: pd.DataFrame
    fold_coefficients: pd.DataFrame
    coefficient_cosines: pd.DataFrame
    score_metrics: dict[str, Any]
    triggered_events: pd.DataFrame
    placebo_paths: pd.DataFrame
    feasibility_gate: dict[str, Any]
    strategy_daily: dict[str, pd.DataFrame]
    strategy_metrics: pd.DataFrame
    tail_metrics: dict[str, Any]
    tail_and_path_gate: dict[str, Any]
    decision: str


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def _trailing_percentile(
    series: pd.Series, *, window: int, minimum: int
) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    output = pd.Series(np.nan, index=values.index, dtype=float)
    array = values.to_numpy(dtype=float)
    for position, current in enumerate(array):
        start = max(0, position - window)
        history = array[start:position]
        history = history[np.isfinite(history)]
        if np.isfinite(current) and len(history) >= minimum:
            output.iloc[position] = float(np.mean(history <= current))
    return output


def _episode_age(states: pd.Series, target: int = 2) -> pd.Series:
    numeric = pd.to_numeric(states, errors="coerce")
    active = numeric.eq(target)
    groups = active.ne(active.shift(1)).cumsum()
    age = active.groupby(groups).cumcount().add(1).astype(float)
    return age.where(active)


def _next_target_weights(baseline: pd.DataFrame) -> pd.DataFrame:
    columns = ["weight_QQQI", "weight_QQQ", "weight_TQQQ"]
    target = baseline[columns].shift(-1).copy()
    target.columns = [f"next_{column}" for column in columns]
    return target


def _build_exact_overlay_label(
    frame: pd.DataFrame,
    baseline: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    out = frame.copy()
    rate = (
        float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
        / 10_000.0
    )
    q_first = out["QQQ_opening_close"] / out["QQQ_open"] - 1.0
    t_first = out["TQQQ_opening_close"] / out["TQQQ_open"] - 1.0
    q_wealth_1000 = 0.25 * (1.0 + q_first)
    t_wealth_1000 = 0.75 * (1.0 + t_first)
    wealth_1000 = q_wealth_1000 + t_wealth_1000
    q_weight_1000 = q_wealth_1000 / wealth_1000.replace(0.0, np.nan)
    t_weight_1000 = t_wealth_1000 / wealth_1000.replace(0.0, np.nan)
    switch_turnover = (1.0 - q_weight_1000).abs() + t_weight_1000.abs()

    q_full = out["QQQ_next_open"] / out["QQQ_open"]
    t_full = out["TQQQ_next_open"] / out["TQQQ_open"]
    baseline_gross = 0.25 * q_full + 0.75 * t_full - 1.0
    baseline_q_end_wealth = 0.25 * q_full
    baseline_t_end_wealth = 0.75 * t_full
    baseline_end_total = baseline_q_end_wealth + baseline_t_end_wealth
    baseline_q_end_weight = baseline_q_end_wealth / baseline_end_total.replace(
        0.0, np.nan
    )
    baseline_t_end_weight = baseline_t_end_wealth / baseline_end_total.replace(
        0.0, np.nan
    )

    q_remaining = out["QQQ_next_open"] / out["QQQ_opening_close"]
    overlay_gross = wealth_1000 * q_remaining - 1.0

    next_target = _next_target_weights(baseline).reindex(out.index)
    out = out.join(next_target)
    baseline_reconcile_turnover = (
        out["next_weight_QQQI"].abs()
        + (out["next_weight_QQQ"] - baseline_q_end_weight).abs()
        + (out["next_weight_TQQQ"] - baseline_t_end_weight).abs()
    )
    overlay_reconcile_turnover = (
        out["next_weight_QQQI"].abs()
        + (out["next_weight_QQQ"] - 1.0).abs()
        + out["next_weight_TQQQ"].abs()
    )
    baseline_reconcile_cost = baseline_reconcile_turnover * rate
    overlay_switch_cost = switch_turnover * rate
    overlay_reconcile_cost = overlay_reconcile_turnover * rate
    baseline_exact_net = baseline_gross - baseline_reconcile_cost
    overlay_exact_net = (
        overlay_gross - overlay_switch_cost - overlay_reconcile_cost
    )

    out["qqq_first30_return"] = q_first
    out["tqqq_first30_return"] = t_first
    out["baseline_exact_gross_return"] = baseline_gross
    out["overlay_exact_gross_return"] = overlay_gross
    out["switch_turnover_units"] = switch_turnover
    out["baseline_next_reconcile_turnover_units"] = baseline_reconcile_turnover
    out["overlay_next_reconcile_turnover_units"] = overlay_reconcile_turnover
    out["incremental_turnover_units"] = (
        switch_turnover
        + overlay_reconcile_turnover
        - baseline_reconcile_turnover
    )
    out["baseline_exact_net_return"] = baseline_exact_net
    out["overlay_exact_net_return"] = overlay_exact_net
    out["delever_to_qqq_net_advantage"] = overlay_exact_net - baseline_exact_net
    out["delever_positive"] = out["delever_to_qqq_net_advantage"].gt(0.0)
    out["baseline_official_net_return"] = baseline["net_return"].reindex(out.index)
    out["baseline_official_turnover_units"] = baseline[
        "turnover_units"
    ].reindex(out.index)
    return out


def build_intraday_pilot_frame(
    intraday_bars: Mapping[str, pd.DataFrame],
    daily_bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    alignment = build_opening_alignment(intraday_bars, contract)
    if alignment.empty:
        raise ValueError("no common intraday opening alignment")
    frame = alignment.copy()
    frame["qqq_gap_from_previous_regular_close"] = (
        frame["QQQ_open"] / frame["QQQ_previous_regular_close"] - 1.0
    )
    frame["qqq_first30_return"] = (
        frame["QQQ_opening_close"] / frame["QQQ_open"] - 1.0
    )
    frame["spy_first30_return"] = (
        frame["SPY_opening_close"] / frame["SPY_open"] - 1.0
    )
    frame["tqqq_first30_return"] = (
        frame["TQQQ_opening_close"] / frame["TQQQ_open"] - 1.0
    )
    opening_range = (
        frame["QQQ_opening_high"] - frame["QQQ_opening_low"]
    ) / frame["QQQ_open"].replace(0.0, np.nan)
    trailing_range = opening_range.shift(1).rolling(20, min_periods=20).median()
    frame["qqq_opening_range_ratio_to_trailing20_median"] = (
        opening_range / trailing_range.replace(0.0, np.nan)
    )
    frame["qqq_opening_volume_percentile_trailing60"] = _trailing_percentile(
        frame["QQQ_opening_volume"], window=60, minimum=20
    )
    frame["qqq_minus_spy_first30_return"] = (
        frame["qqq_first30_return"] - frame["spy_first30_return"]
    )
    frame["tqqq_tracking_residual_first30"] = (
        frame["tqqq_first30_return"] - 3.0 * frame["qqq_first30_return"]
    )

    vix = _normalise_bars(daily_bars["^VIX"], "^VIX")["close"]
    vxn = _normalise_bars(daily_bars["^VXN"], "^VXN")["close"]
    ratio = vxn / vix.replace(0.0, np.nan)
    frame["prior_vxn_vix_ratio_z63"] = _rolling_zscore(ratio, 63).shift(1).reindex(
        frame.index
    )
    hyg = _normalise_bars(daily_bars["HYG"], "HYG")["close"]
    lqd = _normalise_bars(daily_bars["LQD"], "LQD")["close"]
    credit_ratio = hyg / lqd.replace(0.0, np.nan)
    credit_ma20 = credit_ratio.rolling(20, min_periods=20).mean()
    frame["prior_hyg_lqd_return_20d"] = credit_ratio.pct_change(20).shift(1).reindex(
        frame.index
    )
    frame["prior_credit_risk_ratio_distance_ma20"] = (
        credit_ratio / credit_ma20.replace(0.0, np.nan) - 1.0
    ).shift(1).reindex(frame.index)
    frame["state2_episode_age"] = _episode_age(
        baseline_daily["position_state"], 2
    ).reindex(frame.index)
    frame["position_state"] = baseline_daily["position_state"].reindex(frame.index)
    frame = _build_exact_overlay_label(frame, baseline_daily, contract)
    feature_names = tuple(str(value) for value in contract["features"]["names"])
    if set(feature_names) != set(contract["features"]["names"]):
        raise AssertionError("feature contract contains duplicates")
    missing = sorted(set(feature_names).difference(frame.columns))
    if missing:
        raise AssertionError(f"pilot frame missing frozen features: {missing}")
    start = pd.Timestamp(contract["intraday_data"]["start_date"])
    end = pd.Timestamp(contract["intraday_data"]["end_date"])
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)].copy()
    frame = frame.loc[frame["position_state"].eq(2)].copy()
    frame.index.name = "session_date"
    return frame, feature_names


def _pipeline(contract: Mapping[str, Any]) -> Pipeline:
    model = contract["model"]
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy=str(model["imputer"]))),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    penalty=str(model["penalty"]),
                    C=float(model["C"]),
                    solver=str(model["solver"]),
                    class_weight=str(model["class_weight"]),
                    max_iter=int(model["max_iter"]),
                    random_state=int(model["random_state"]),
                ),
            ),
        ]
    )


def _coefficient_rows(
    model: Pipeline,
    fold: str,
    feature_names: Sequence[str],
) -> list[dict[str, Any]]:
    estimator: LogisticRegression = model.named_steps["model"]
    return [
        {
            "fold": fold,
            "feature": feature,
            "coefficient": float(estimator.coef_[0, position]),
        }
        for position, feature in enumerate(feature_names)
    ]


def _coefficient_cosines(coefficients: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pivot = coefficients.pivot(index="fold", columns="feature", values="coefficient")
    for left, right in combinations(pivot.index, 2):
        a = pivot.loc[left].to_numpy(dtype=float)
        b = pivot.loc[right].to_numpy(dtype=float)
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        rows.append(
            {
                "left_fold": left,
                "right_fold": right,
                "cosine_similarity": (
                    float(np.dot(a, b) / denominator) if denominator else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def fit_chronological_pilot(
    frame: pd.DataFrame,
    feature_names: Sequence[str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions: list[pd.DataFrame] = []
    coverage: list[dict[str, Any]] = []
    coefficients: list[dict[str, Any]] = []
    minimum = int(contract["training"]["minimum_complete_training_events"])
    percentile = float(contract["model"]["training_score_percentile_trigger"])
    for fold in contract["outer_folds"]:
        name = str(fold["fold"])
        train = frame.loc[
            (frame.index >= pd.Timestamp(fold["train_start"]))
            & (frame.index <= pd.Timestamp(fold["train_end"]))
        ].dropna(subset=list(feature_names) + ["delever_positive"])
        test = frame.loc[
            (frame.index >= pd.Timestamp(fold["test_start"]))
            & (frame.index <= pd.Timestamp(fold["test_end"]))
        ].dropna(
            subset=list(feature_names)
            + ["delever_positive", "delever_to_qqq_net_advantage"]
        )
        classes = int(train["delever_positive"].nunique())
        trainable = len(train) >= minimum and classes == 2 and len(test) > 0
        coverage.append(
            {
                "fold": name,
                "train_start": train.index.min() if len(train) else None,
                "train_end": train.index.max() if len(train) else None,
                "test_start": test.index.min() if len(test) else None,
                "test_end": test.index.max() if len(test) else None,
                "train_events": int(len(train)),
                "test_events": int(len(test)),
                "train_positive_rate": float(train["delever_positive"].mean())
                if len(train)
                else np.nan,
                "test_positive_rate": float(test["delever_positive"].mean())
                if len(test)
                else np.nan,
                "train_classes": classes,
                "trainable": trainable,
            }
        )
        if not trainable:
            continue
        model = _pipeline(contract)
        model.fit(train[list(feature_names)], train["delever_positive"].astype(int))
        training_score = model.predict_proba(train[list(feature_names)])[:, 1]
        threshold = float(np.quantile(training_score, percentile))
        score = model.predict_proba(test[list(feature_names)])[:, 1]
        result = test[
            [
                "delever_positive",
                "delever_to_qqq_net_advantage",
                "baseline_official_net_return",
                "incremental_turnover_units",
                "switch_turnover_units",
                "baseline_next_reconcile_turnover_units",
                "overlay_next_reconcile_turnover_units",
            ]
        ].copy()
        result["fold"] = name
        result["score"] = score
        result["training_score_threshold"] = threshold
        result["trigger"] = result["score"].ge(threshold)
        predictions.append(result)
        coefficients.extend(_coefficient_rows(model, name, feature_names))
    prediction_frame = (
        pd.concat(predictions).sort_index()
        if predictions
        else pd.DataFrame()
    )
    coefficient_frame = pd.DataFrame(coefficients)
    cosine = (
        _coefficient_cosines(coefficient_frame)
        if not coefficient_frame.empty
        else pd.DataFrame()
    )
    return prediction_frame, pd.DataFrame(coverage), coefficient_frame, cosine


def _assign_clusters(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events.sort_index().copy()
    dates = pd.DatetimeIndex(out.index)
    new_cluster = pd.Series(dates, index=out.index).diff().dt.days.gt(30).fillna(True)
    out["macro_cluster"] = new_cluster.cumsum().astype(int).to_numpy()
    return out


def _safe_share(values: pd.Series) -> float:
    positive = pd.to_numeric(values, errors="coerce").clip(lower=0.0)
    total = float(positive.sum())
    return float(positive.max() / total) if total > 0.0 else np.nan


def _without_best_group(events: pd.DataFrame, group: pd.Series) -> float:
    if events.empty:
        return np.nan
    aggregate = events["delever_to_qqq_net_advantage"].groupby(group).sum()
    if aggregate.empty:
        return np.nan
    return float(aggregate.sum() - aggregate.max())


def _score_metrics(
    predictions: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    if predictions.empty:
        metrics = {
            "observations": 0,
            "roc_auc": np.nan,
            "spearman": np.nan,
            "top_quintile_positive_rate_lift": np.nan,
            "top_quintile_median_advantage": np.nan,
        }
        return metrics, pd.DataFrame(), {"checks": {}, "passed": False}
    y = predictions["delever_positive"].astype(int)
    auc = float(roc_auc_score(y, predictions["score"])) if y.nunique() == 2 else np.nan
    spearman = float(
        predictions["score"].corr(
            predictions["delever_to_qqq_net_advantage"], method="spearman"
        )
    )
    ranks = predictions["score"].rank(method="first")
    quintile = pd.qcut(ranks, 5, labels=False, duplicates="drop")
    top_mask = quintile.eq(quintile.max())
    unconditional = float(y.mean())
    top_positive = float(y.loc[top_mask].mean())
    top_median = float(
        predictions.loc[top_mask, "delever_to_qqq_net_advantage"].median()
    )
    top_mean = float(
        predictions.loc[top_mask, "delever_to_qqq_net_advantage"].mean()
    )
    events = _assign_clusters(predictions.loc[predictions["trigger"]].copy())
    fold_advantage = predictions.loc[predictions["trigger"]].groupby("fold")[
        "delever_to_qqq_net_advantage"
    ].sum()
    positive_event_share = _safe_share(events["delever_to_qqq_net_advantage"])
    without_best_event = (
        float(
            events["delever_to_qqq_net_advantage"].sum()
            - events["delever_to_qqq_net_advantage"].max()
        )
        if not events.empty
        else np.nan
    )
    month = events.index.to_period("M") if not events.empty else pd.Series(dtype=str)
    without_best_month = (
        _without_best_group(events, pd.Series(month, index=events.index))
        if not events.empty
        else np.nan
    )
    thresholds = contract["validation"]["feasibility_gate"]
    checks = {
        "roc_auc": np.isfinite(auc) and auc >= float(thresholds["roc_auc_min"]),
        "spearman": np.isfinite(spearman)
        and spearman >= float(thresholds["spearman_score_advantage_min"]),
        "top_quintile_lift": top_positive - unconditional
        >= float(thresholds["top_quintile_positive_rate_lift_min"]),
        "top_quintile_median": top_median
        > float(thresholds["top_quintile_median_advantage_min"]),
        "triggered_sessions": len(events)
        >= int(thresholds["triggered_sessions_min"]),
        "macro_clusters": int(events["macro_cluster"].nunique())
        >= int(thresholds["macro_clusters_min"])
        if not events.empty
        else False,
        "positive_test_folds": int(fold_advantage.gt(0.0).sum())
        >= int(thresholds["positive_test_folds_min"]),
        "event_concentration": np.isfinite(positive_event_share)
        and positive_event_share
        <= float(thresholds["largest_positive_event_share_max"]),
        "without_best_event": np.isfinite(without_best_event)
        and without_best_event >= float(thresholds["without_best_event_min"]),
        "without_best_month": np.isfinite(without_best_month)
        and without_best_month >= float(thresholds["without_best_month_min"]),
    }
    metrics = {
        "observations": int(len(predictions)),
        "positive_rate": unconditional,
        "roc_auc": auc,
        "spearman_score_advantage": spearman,
        "top_quintile_observations": int(top_mask.sum()),
        "top_quintile_positive_rate": top_positive,
        "top_quintile_positive_rate_lift": top_positive - unconditional,
        "top_quintile_median_advantage": top_median,
        "top_quintile_mean_advantage": top_mean,
        "triggered_sessions": int(len(events)),
        "macro_clusters": int(events["macro_cluster"].nunique())
        if not events.empty
        else 0,
        "triggered_total_advantage": float(
            events["delever_to_qqq_net_advantage"].sum()
        )
        if not events.empty
        else 0.0,
        "triggered_median_advantage": float(
            events["delever_to_qqq_net_advantage"].median()
        )
        if not events.empty
        else np.nan,
        "positive_fold_count": int(fold_advantage.gt(0.0).sum()),
        "fold_triggered_advantage": fold_advantage.to_dict(),
        "largest_positive_event_share": positive_event_share,
        "without_best_event_advantage": without_best_event,
        "without_best_month_advantage": without_best_month,
    }
    return metrics, events, {"checks": checks, "passed": bool(all(checks.values()))}


def _placebo_paths(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, float]:
    if predictions.empty or events.empty:
        return pd.DataFrame(), np.nan
    actual = float(events["delever_to_qqq_net_advantage"].sum())
    rows: list[dict[str, Any]] = []
    seeds = int(contract["placebo"]["deterministic_seeds"])
    base_seed = int(contract["placebo"]["base_seed"])
    trigger_counts = events.groupby("fold").size().to_dict()
    for offset in range(seeds):
        rng = np.random.default_rng(base_seed + offset)
        selected: list[pd.DataFrame] = []
        for fold, count in trigger_counts.items():
            population = predictions.loc[predictions["fold"].eq(fold)]
            if count > len(population):
                continue
            locations = rng.choice(len(population), size=int(count), replace=False)
            selected.append(population.iloc[locations])
        placebo = pd.concat(selected) if selected else pd.DataFrame()
        total = float(placebo["delever_to_qqq_net_advantage"].sum()) if len(placebo) else 0.0
        rows.append(
            {
                "seed": base_seed + offset,
                "events": int(len(placebo)),
                "placebo_total_advantage": total,
                "actual_triggered_advantage": actual,
                "actual_beats_placebo": actual > total,
            }
        )
    table = pd.DataFrame(rows)
    return table, float(table["actual_beats_placebo"].mean())


def _strategy_daily(
    baseline: pd.DataFrame,
    frame: pd.DataFrame,
    triggered_dates: pd.DatetimeIndex,
    *,
    name: str,
) -> pd.DataFrame:
    index = baseline.index.intersection(
        pd.date_range(frame.index.min(), frame.index.max(), freq="D")
    )
    daily = baseline.reindex(index).copy()
    advantage = frame["delever_to_qqq_net_advantage"].reindex(index).fillna(0.0)
    trigger = pd.Series(False, index=index)
    trigger.loc[trigger.index.intersection(triggered_dates)] = True
    daily["overlay_trigger"] = trigger
    daily["overlay_advantage"] = advantage.where(trigger, 0.0)
    daily["net_return"] = daily["net_return"] + daily["overlay_advantage"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    daily.attrs["strategy"] = name
    return daily


def _metrics_table(strategies: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, daily in strategies.items():
        metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
        metrics["strategy"] = name
        rows.append(metrics)
    return pd.DataFrame(rows).set_index("strategy")


def _tail_and_path(
    baseline: pd.DataFrame,
    frame: pd.DataFrame,
    events: pd.DataFrame,
    strategies: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_dates = pd.DatetimeIndex(events.index) if not events.empty else pd.DatetimeIndex([])
    baseline_state2 = baseline["net_return"].reindex(frame.index).dropna()
    pilot_state2 = baseline_state2 + frame["delever_to_qqq_net_advantage"].where(
        frame.index.isin(event_dates), 0.0
    ).reindex(baseline_state2.index).fillna(0.0)
    baseline_worst = float(baseline_state2.min())
    pilot_on_baseline_worst = float(pilot_state2.loc[baseline_state2.idxmin()])
    worst_five_dates = baseline_state2.nsmallest(min(5, len(baseline_state2))).index
    worst_five_improvement = float(
        (pilot_state2.reindex(worst_five_dates) - baseline_state2.reindex(worst_five_dates)).mean()
    )
    metrics = _metrics_table(strategies)
    baseline_metrics = metrics.loc["frozen_v4_2"]
    pilot_metrics = metrics.loc["rank_triggered_intraday_meta_label"]
    drawdown_worsening_pp = max(
        0.0,
        float(
            (
                baseline_metrics["max_drawdown"]
                - pilot_metrics["max_drawdown"]
            )
            * 100.0
        ),
    )
    baseline_turnover = float(baseline["turnover_units"].reindex(strategies["frozen_v4_2"].index).sum())
    incremental_turnover = float(
        frame.loc[frame.index.intersection(event_dates), "incremental_turnover_units"].sum()
    )
    turnover_ratio = incremental_turnover / baseline_turnover if baseline_turnover else np.nan
    thresholds = contract["validation"]["tail_and_path_gate"]
    checks = {
        "worst_state2_not_worse": pilot_on_baseline_worst - baseline_worst
        >= -float(thresholds["worst_state2_session_worsening_max"]),
        "worst_five_improved": worst_five_improvement
        >= float(thresholds["worst_five_state2_mean_improvement_min"]),
        "maximum_drawdown": drawdown_worsening_pp
        <= float(thresholds["maximum_drawdown_worsening_pp_max"]),
        "incremental_turnover": np.isfinite(turnover_ratio)
        and turnover_ratio <= float(thresholds["incremental_turnover_ratio_max"]),
    }
    tail = {
        "baseline_worst_state2_return": baseline_worst,
        "pilot_return_on_baseline_worst_date": pilot_on_baseline_worst,
        "worst_state2_improvement": pilot_on_baseline_worst - baseline_worst,
        "worst_five_state2_mean_improvement": worst_five_improvement,
        "maximum_drawdown_worsening_pp": drawdown_worsening_pp,
        "baseline_turnover_units": baseline_turnover,
        "incremental_turnover_units": incremental_turnover,
        "incremental_turnover_ratio": turnover_ratio,
    }
    return tail, {"checks": checks, "passed": bool(all(checks.values()))}


def run_intraday_rank_pilot(
    intraday_bars: Mapping[str, pd.DataFrame],
    daily_bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> IntradayPilotResult:
    frame, feature_names = build_intraday_pilot_frame(
        intraday_bars, daily_bars, baseline_daily, contract
    )
    predictions, coverage, coefficients, cosines = fit_chronological_pilot(
        frame, feature_names, contract
    )
    score_metrics, events, feasibility = _score_metrics(predictions, contract)
    placebo, beaten_rate = _placebo_paths(predictions, events, contract)
    score_metrics["placebo_paths_beaten_rate"] = beaten_rate
    feasibility_checks = dict(feasibility.get("checks", {}))
    trainable = bool(len(coverage) == len(contract["outer_folds"]) and coverage["trainable"].all())
    feasibility_checks["both_folds_trainable"] = trainable
    feasibility_checks["placebo_paths"] = np.isfinite(beaten_rate) and beaten_rate >= float(
        contract["validation"]["feasibility_gate"]["placebo_paths_beaten_rate_min"]
    )
    feasibility = {
        "checks": feasibility_checks,
        "passed": bool(feasibility_checks and all(feasibility_checks.values())),
    }

    available_index = baseline_daily.index[
        (baseline_daily.index >= pd.Timestamp(contract["intraday_data"]["start_date"]))
        & (baseline_daily.index <= pd.Timestamp(contract["intraday_data"]["end_date"]))
    ]
    baseline_slice = baseline_daily.reindex(available_index).copy()
    event_dates = pd.DatetimeIndex(events.index) if not events.empty else pd.DatetimeIndex([])
    strategies = {
        "frozen_v4_2": _strategy_daily(
            baseline_slice, frame, pd.DatetimeIndex([]), name="frozen_v4_2"
        ),
        "rank_triggered_intraday_meta_label": _strategy_daily(
            baseline_slice, frame, event_dates, name="rank_triggered_intraday_meta_label"
        ),
        "always_delever_state2_at_1000": _strategy_daily(
            baseline_slice, frame, pd.DatetimeIndex(frame.dropna(subset=["delever_to_qqq_net_advantage"]).index), name="always_delever_state2_at_1000"
        ),
    }
    strategy_metrics = _metrics_table(strategies)
    tail_metrics, tail_gate = _tail_and_path(
        baseline_slice, frame, events, strategies, contract
    )
    if not trainable:
        decision = "intraday_rank_pilot_inconclusive_due_to_sample_or_class_coverage"
    elif feasibility["passed"] and tail_gate["passed"]:
        decision = "intraday_rank_mechanism_worth_prospective_collection"
    else:
        decision = "intraday_rank_mechanism_not_supported_in_recent_history"
    return IntradayPilotResult(
        frame=frame,
        feature_names=tuple(feature_names),
        predictions=predictions,
        fold_coverage=coverage,
        fold_coefficients=coefficients,
        coefficient_cosines=cosines,
        score_metrics=score_metrics,
        triggered_events=events,
        placebo_paths=placebo,
        feasibility_gate=feasibility,
        strategy_daily=strategies,
        strategy_metrics=strategy_metrics,
        tail_metrics=tail_metrics,
        tail_and_path_gate=tail_gate,
        decision=decision,
    )
