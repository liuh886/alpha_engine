"""Walk-forward recovery-quality factor model for the frozen QQQ v4.2 family.

The estimator predicts the next ten-session marginal log return of TQQQ versus
QQQ.  It never changes the v4.2 state trace.  One probability observed at the
close before a formal state-2 entry sets a frozen 50%, 75% or 100% TQQQ budget
for that contiguous state-2 episode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_sgov_defense_experiment import _chronological_metrics
from src.research.vix_rotation_experiment import _normalise_close
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS,
    run_bridge_allocation_comparison,
)

BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"
VARIANTS = (
    "current_v4_2",
    "factor_defensive_ablation",
    "factor_offensive_ablation",
    "factor_joint_budget",
)


@dataclass(frozen=True)
class FactorModelOutput:
    """Frozen factor-model predictions and audit evidence."""

    frame: pd.DataFrame
    oof_predictions: pd.DataFrame
    holdout_predictions: pd.DataFrame
    fold_metrics: pd.DataFrame
    aggregate_metrics: dict[str, Any]
    feature_names: tuple[str, ...]
    coefficients: pd.DataFrame


def _forward_sum(series: pd.Series, horizon: int) -> pd.Series:
    """Sum the next ``horizon`` observations, beginning after the current row."""

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    shifted = pd.to_numeric(series, errors="coerce").shift(-1)
    return shifted.iloc[::-1].rolling(horizon, min_periods=horizon).sum().iloc[::-1]


def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Return the percentile rank of the latest value within each rolling window."""

    def latest_rank(values: np.ndarray) -> float:
        latest = values[-1]
        return float(np.mean(values <= latest))

    return series.rolling(window, min_periods=window).apply(latest_rank, raw=True)


def _downside_volatility(returns: pd.Series, window: int) -> pd.Series:
    downside = returns.where(returns < 0.0, 0.0)
    return downside.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(252.0)


def _state_one_age(states: pd.Series) -> pd.Series:
    state_one = states.eq(1)
    groups = (~state_one).cumsum()
    age = state_one.astype(int).groupby(groups).cumsum()
    return age.where(state_one, 0).astype(float)


def build_recovery_quality_frame(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    factor_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, StrategyResult]:
    """Build the frozen feature/label frame on the unchanged v4.2 trace."""

    required = set(factor_contract["data"]["required_symbols"])
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    _, results, _, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    baseline = results[BASELINE_KEY]
    daily = baseline.daily.copy()

    qqq = _normalise_close(bars["QQQ"], "QQQ").reindex(daily.index)
    qqqe = _normalise_close(bars["QQQE"], "QQQE").reindex(daily.index)
    vix = _normalise_close(bars["^VIX"], "^VIX").reindex(daily.index)
    vxn = _normalise_close(bars["^VXN"], "^VXN").reindex(daily.index)

    qqq_return = qqq.pct_change()
    breadth_ratio = qqqe / qqq
    frame = pd.DataFrame(index=daily.index)
    frame["qqq_return_5d"] = qqq.pct_change(5)
    frame["qqq_return_20d"] = qqq.pct_change(20)
    for window in (20, 50, 200):
        average = qqq.rolling(window, min_periods=window).mean()
        frame[f"qqq_distance_ma{window}"] = qqq / average - 1.0
    frame["qqq_realized_volatility_20d"] = qqq_return.rolling(20, min_periods=20).std(
        ddof=0
    ) * np.sqrt(252.0)
    frame["qqq_downside_volatility_20d"] = _downside_volatility(qqq_return, 20)
    frame["vix_return_5d"] = vix.pct_change(5)
    frame["vix_retreat_from_20d_high"] = vix / vix.rolling(20, min_periods=20).max() - 1.0
    frame["vix_percentile_252d"] = _rolling_percentile(vix, 252)
    frame["vxn_return_5d"] = vxn.pct_change(5)
    frame["vxn_retreat_from_20d_high"] = vxn / vxn.rolling(20, min_periods=20).max() - 1.0
    frame["vxn_vix_level_ratio"] = vxn / vix
    frame["qqqe_qqq_ratio_return_5d"] = breadth_ratio.pct_change(5)
    breadth_ma20 = breadth_ratio.rolling(20, min_periods=20).mean()
    frame["qqqe_qqq_ratio_distance_ma20"] = breadth_ratio / breadth_ma20 - 1.0
    frame["state_1_age_sessions"] = _state_one_age(daily["position_state"].astype(int))

    marginal_daily = np.log1p(daily["TQQQ_next_open_return"].astype(float)) - np.log1p(
        daily["QQQ_next_open_return"].astype(float)
    )
    horizon = int(factor_contract["label"]["horizon_sessions"])
    frame["future_marginal_log_return_10d"] = _forward_sum(marginal_daily, horizon)
    frame["positive_marginal_return"] = frame["future_marginal_log_return_10d"].gt(0.0)
    frame["position_state"] = daily["position_state"].astype(int)
    frame["decision_state"] = daily["decision_state"].astype(int)
    frame["eligible_for_model"] = frame["position_state"].isin([1, 2])
    frame["QQQ_next_open_return"] = daily["QQQ_next_open_return"].astype(float)
    frame["TQQQ_next_open_return"] = daily["TQQQ_next_open_return"].astype(float)
    return frame, baseline


def _pipeline(contract: Mapping[str, Any]) -> Pipeline:
    estimator = contract["estimator"]
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    penalty=str(estimator["penalty"]),
                    C=float(estimator["C"]),
                    class_weight=str(estimator["class_weight"]),
                    solver=str(estimator["solver"]),
                    max_iter=int(estimator["max_iter"]),
                    random_state=int(estimator["random_state"]),
                ),
            ),
        ]
    )


def _prediction_metrics(
    table: pd.DataFrame,
    *,
    require_both_classes: bool = True,
) -> dict[str, Any]:
    valid = table.dropna(
        subset=["probability", "positive_marginal_return", "future_marginal_log_return_10d"]
    ).copy()
    if valid.empty:
        raise ValueError("prediction sample is empty")
    class_count = int(valid["positive_marginal_return"].nunique())
    if require_both_classes and class_count < 2:
        raise ValueError("prediction sample requires both label classes")
    probability = valid["probability"].astype(float)
    label = valid["positive_marginal_return"].astype(int)
    continuous = valid["future_marginal_log_return_10d"].astype(float)
    quartile = pd.qcut(probability.rank(method="first"), 4, labels=False)
    bottom = continuous.loc[quartile.eq(0)]
    top = continuous.loc[quartile.eq(3)]
    spread = float(top.mean() - bottom.mean())
    return {
        "observations": int(len(valid)),
        "positive_rate": float(label.mean()),
        "class_count": class_count,
        "roc_auc": (float(roc_auc_score(label, probability)) if class_count >= 2 else np.nan),
        "brier_score": float(brier_score_loss(label, probability)),
        "spearman_ic": float(probability.corr(continuous, method="spearman")),
        "top_quartile_mean_marginal_log_return": float(top.mean()),
        "bottom_quartile_mean_marginal_log_return": float(bottom.mean()),
        "top_bottom_quartile_spread": spread,
    }


def fit_walk_forward_factor_model(
    frame: pd.DataFrame,
    contract: Mapping[str, Any],
) -> FactorModelOutput:
    """Fit purged expanding folds and one final pre-holdout estimator."""

    features = tuple(str(value) for value in contract["features"])
    missing = sorted(set(features) - set(frame.columns))
    if missing:
        raise ValueError(f"factor frame missing features: {missing}")

    development_end = pd.Timestamp(contract["data"]["model_development_end"])
    holdout_start = pd.Timestamp(contract["data"]["reserved_holdout_start"])
    walk = contract["walk_forward"]
    purge = int(walk["purge_sessions"])
    first_year = int(walk["first_validation_year"])
    last_year = int(walk["last_validation_year"])

    usable = frame.loc[frame["eligible_for_model"]].copy()
    usable = usable.dropna(subset=["future_marginal_log_return_10d"])
    usable["positive_marginal_return"] = usable["positive_marginal_return"].astype(int)

    fold_rows: list[dict[str, Any]] = []
    oof_parts: list[pd.DataFrame] = []
    for year in range(first_year, last_year + 1):
        validation = usable.loc[usable.index.year == year].copy()
        if validation.empty:
            continue
        first_location = int(usable.index.get_indexer([validation.index.min()])[0])
        cutoff_location = max(first_location - purge, 0)
        cutoff = usable.index[cutoff_location]
        training = usable.loc[(usable.index < cutoff) & (usable.index <= development_end)].copy()
        if training.empty or training.index.year.nunique() < int(walk["minimum_training_years"]):
            continue
        if training["positive_marginal_return"].nunique() < 2:
            continue
        model = _pipeline(contract)
        model.fit(training[list(features)], training["positive_marginal_return"])
        probability = model.predict_proba(validation[list(features)])[:, 1]
        predicted = validation[
            ["positive_marginal_return", "future_marginal_log_return_10d"]
        ].copy()
        predicted["probability"] = probability
        predicted["validation_year"] = year
        oof_parts.append(predicted)
        metrics = _prediction_metrics(predicted, require_both_classes=False)
        metrics.update(
            {
                "validation_year": year,
                "training_start": training.index.min(),
                "training_end": training.index.max(),
                "validation_start": validation.index.min(),
                "validation_end": validation.index.max(),
            }
        )
        fold_rows.append(metrics)

    if not oof_parts:
        raise ValueError("no valid walk-forward folds were produced")
    oof = pd.concat(oof_parts).sort_index()
    fold_metrics = pd.DataFrame(fold_rows).sort_values("validation_year")
    aggregate = _prediction_metrics(oof, require_both_classes=True)
    positive_spreads = fold_metrics["top_bottom_quartile_spread"].clip(lower=0.0)
    aggregate["validation_years"] = int(len(fold_metrics))
    aggregate["positive_validation_year_rate"] = float(
        fold_metrics["top_bottom_quartile_spread"].gt(0.0).mean()
    )
    aggregate["largest_positive_year_share"] = (
        float(positive_spreads.max() / positive_spreads.sum())
        if float(positive_spreads.sum()) > 0.0
        else 1.0
    )

    holdout_location = int(usable.index.searchsorted(holdout_start))
    final_cutoff_location = max(holdout_location - purge, 0)
    final_cutoff = usable.index[final_cutoff_location]
    final_training = usable.loc[
        (usable.index < final_cutoff) & (usable.index <= development_end)
    ].copy()
    if final_training["positive_marginal_return"].nunique() < 2:
        raise ValueError("final training sample requires both label classes")
    final_model = _pipeline(contract)
    final_model.fit(final_training[list(features)], final_training["positive_marginal_return"])

    holdout = frame.loc[frame.index >= holdout_start].copy()
    holdout_probability = final_model.predict_proba(holdout[list(features)])[:, 1]
    holdout_predictions = holdout[
        ["positive_marginal_return", "future_marginal_log_return_10d", "position_state"]
    ].copy()
    holdout_predictions["probability"] = holdout_probability

    model = final_model.named_steps["model"]
    coefficients = pd.DataFrame(
        {
            "feature": list(features),
            "coefficient": np.asarray(model.coef_[0], dtype=float),
        }
    ).sort_values("coefficient", ascending=False)
    aggregate["final_training_start"] = final_training.index.min()
    aggregate["final_training_end"] = final_training.index.max()
    aggregate["holdout_start"] = holdout.index.min()
    return FactorModelOutput(
        frame=frame,
        oof_predictions=oof,
        holdout_predictions=holdout_predictions,
        fold_metrics=fold_metrics,
        aggregate_metrics=aggregate,
        feature_names=features,
        coefficients=coefficients,
    )


def _episode_budget_trace(
    states: pd.Series,
    close_probability: pd.Series,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Read one prior-close probability and freeze the bucket for each state-2 episode."""

    mapping = contract["strategy_mapping"]
    low = float(mapping["probability_low_below"])
    high = float(mapping["probability_high_at_or_above"])
    execution_probability = close_probability.shift(1)
    active_bucket = "baseline"
    active_probability = np.nan
    previous_state = 0
    buckets: list[str] = []
    probabilities: list[float] = []
    entries: list[bool] = []
    for state, probability in zip(states.astype(int), execution_probability, strict=True):
        entry = state == 2 and previous_state != 2
        if entry:
            active_probability = float(probability) if pd.notna(probability) else 0.50
            if active_probability < low:
                active_bucket = "low"
            elif active_probability >= high:
                active_bucket = "high"
            else:
                active_bucket = "baseline"
        elif state != 2:
            active_bucket = "baseline"
            active_probability = np.nan
        buckets.append(active_bucket if state == 2 else "not_state_2")
        probabilities.append(active_probability if state == 2 else np.nan)
        entries.append(entry)
        previous_state = state
    return pd.DataFrame(
        {
            "factor_bucket": buckets,
            "factor_probability_at_entry": probabilities,
            "state_2_episode_entry": entries,
        },
        index=states.index,
    )


def _variant_tqqq_weight(bucket: str, variant: str) -> float:
    if bucket == "not_state_2":
        return 0.0
    if variant == "current_v4_2":
        return 0.75
    if variant == "factor_defensive_ablation":
        return 0.50 if bucket == "low" else 0.75
    if variant == "factor_offensive_ablation":
        return 1.00 if bucket == "high" else 0.75
    if variant == "factor_joint_budget":
        return {"low": 0.50, "baseline": 0.75, "high": 1.00}[bucket]
    raise ValueError(f"unknown factor-budget variant: {variant}")


def run_factor_budget_backtest(
    baseline: StrategyResult,
    close_probability: pd.Series,
    contract: Mapping[str, Any],
    variant: str,
) -> StrategyResult:
    """Execute one episode-frozen factor budget on the unchanged v4.2 states."""

    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    daily = baseline.daily.copy()
    trace = _episode_budget_trace(daily["position_state"], close_probability, contract)
    daily = daily.join(trace)
    weights = daily[[f"weight_{asset}" for asset in ASSETS]].copy()
    weights.columns = list(ASSETS)
    state_two = daily["position_state"].eq(2)
    for date in daily.index[state_two]:
        bucket = str(daily.at[date, "factor_bucket"])
        tqqq = _variant_tqqq_weight(bucket, variant)
        weights.at[date, "QQQI"] = 0.0
        weights.at[date, "QQQ"] = 1.0 - tqqq
        weights.at[date, "TQQQ"] = tqqq
    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("factor-budget weights must sum to one")
    if (weights < -1e-12).any().any():
        raise AssertionError("factor-budget weights cannot be negative")
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]
    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"] for asset in ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    weight_change = weights.loc[daily.index].ne(weights.loc[daily.index].shift()).any(axis=1)
    metrics.update(
        {
            "strategy": variant,
            "switch_count": int(max(int(weight_change.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "low_state_2_sessions": int(
                (daily["position_state"].eq(2) & daily["factor_bucket"].eq("low")).sum()
            ),
            "baseline_state_2_sessions": int(
                (daily["position_state"].eq(2) & daily["factor_bucket"].eq("baseline")).sum()
            ),
            "high_state_2_sessions": int(
                (daily["position_state"].eq(2) & daily["factor_bucket"].eq("high")).sum()
            ),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
        }
    )
    trade_columns = [
        "position_state",
        "position_label",
        "executed_reason",
        "factor_bucket",
        "factor_probability_at_entry",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "turnover_units",
        "transaction_cost",
    ]
    trades = daily.loc[weight_change, trade_columns].reset_index(names="date")
    return StrategyResult(variant, daily, trades, metrics)


def factor_budget_episodes(
    result: StrategyResult,
    baseline: StrategyResult,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Attribute every formal state-2 episode against fixed v4.2."""

    states = result.daily["position_state"].astype(int)
    starts = states.eq(2) & states.shift(1, fill_value=0).ne(2)
    index = result.daily.index
    rows: list[dict[str, Any]] = []
    for number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and int(states.iloc[end_location + 1]) == 2:
            end_location += 1
        candidate_slice = result.daily.iloc[start_location : end_location + 1]
        baseline_slice = baseline.daily.iloc[start_location : end_location + 1]
        candidate_log = float(np.log1p(candidate_slice["net_return"]).sum())
        baseline_log = float(np.log1p(baseline_slice["net_return"]).sum())
        relative = float(np.exp(candidate_log - baseline_log) - 1.0)
        marginal_path = np.log1p(candidate_slice["net_return"]) - np.log1p(
            baseline_slice["net_return"]
        )
        cumulative_relative = np.exp(marginal_path.cumsum()) - 1.0
        row: dict[str, Any] = {
            "event_id": f"state2_{number:03d}",
            "entry_date": start,
            "exit_date": index[end_location],
            "sessions": int(end_location - start_location + 1),
            "factor_probability": float(result.daily.loc[start, "factor_probability_at_entry"]),
            "factor_bucket": str(result.daily.loc[start, "factor_bucket"]),
            "candidate_return": float(np.exp(candidate_log) - 1.0),
            "v4_2_return": float(np.exp(baseline_log) - 1.0),
            "relative_return": relative,
            "relative_mfe": float(cumulative_relative.max()),
            "relative_mae": float(cumulative_relative.min()),
        }
        for horizon in horizons:
            window = result.daily.iloc[start_location : start_location + int(horizon)]
            if len(window) != int(horizon):
                row[f"qqq_return_{horizon}d"] = np.nan
                row[f"tqqq_return_{horizon}d"] = np.nan
                continue
            row[f"qqq_return_{horizon}d"] = float(
                (1.0 + window["QQQ_next_open_return"]).prod() - 1.0
            )
            row[f"tqqq_return_{horizon}d"] = float(
                (1.0 + window["TQQQ_next_open_return"]).prod() - 1.0
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _calendar_relative_returns(
    candidate: StrategyResult, baseline: StrategyResult
) -> dict[str, float]:
    aligned = pd.concat(
        [candidate.daily["net_return"], baseline.daily["net_return"]], axis=1
    ).dropna()
    aligned.columns = ["candidate", "baseline"]
    output: dict[str, float] = {}
    for year, group in aligned.groupby(aligned.index.year):
        candidate_return = float((1.0 + group["candidate"]).prod() - 1.0)
        baseline_return = float((1.0 + group["baseline"]).prod() - 1.0)
        output[str(int(year))] = candidate_return - baseline_return
    return output


def _factor_gate(model: FactorModelOutput, contract: Mapping[str, Any]) -> dict[str, Any]:
    thresholds = contract["validation"]["factor_gate"]
    metrics = model.aggregate_metrics
    checks = {
        "aggregate_oof_auc": float(metrics["roc_auc"])
        >= float(thresholds["aggregate_oof_auc_min"]),
        "aggregate_oof_spearman_ic": float(metrics["spearman_ic"])
        >= float(thresholds["aggregate_oof_spearman_ic_min"]),
        "top_bottom_quartile_spread": float(metrics["top_bottom_quartile_spread"]) > 0.0,
        "positive_validation_year_rate": float(metrics["positive_validation_year_rate"])
        >= float(thresholds["positive_validation_year_rate_min"]),
        "largest_positive_year_share": float(metrics["largest_positive_year_share"])
        <= float(thresholds["largest_positive_year_share_max"]),
    }
    return {"checks": checks, "metrics": metrics, "passed": bool(all(checks.values()))}


def _strategy_gate(
    actual_results: Mapping[str, StrategyResult],
    proxy_results: Mapping[str, StrategyResult],
    actual_episodes: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["strategy_gate"]
    baseline = actual_results["current_v4_2"]
    joint = actual_results["factor_joint_budget"]
    proxy_baseline = proxy_results["current_v4_2"]
    proxy_joint = proxy_results["factor_joint_budget"]
    cagr_delta_pp = (float(joint.metrics["cagr"]) - float(baseline.metrics["cagr"])) * 100.0
    max_drawdown_worsening_pp = max(
        0.0,
        (float(baseline.metrics["max_drawdown"]) - float(joint.metrics["max_drawdown"])) * 100.0,
    )
    calmar_delta = float(joint.metrics["calmar"]) - float(baseline.metrics["calmar"])
    calendar = _calendar_relative_returns(joint, baseline)
    positive_calendar_years = int(sum(value > 0.0 for value in calendar.values()))
    positive_events = actual_episodes["relative_return"].clip(lower=0.0)
    largest_positive_episode_share = (
        float(positive_events.max() / positive_events.sum())
        if len(positive_events) and float(positive_events.sum()) > 0.0
        else 1.0
    )
    turnover_increase = (
        float(joint.metrics["turnover_units"]) / float(baseline.metrics["turnover_units"]) - 1.0
    )
    ablation_wins: dict[str, dict[str, bool]] = {}
    for key in ("factor_defensive_ablation", "factor_offensive_ablation"):
        comparator = actual_results[key]
        ablation_wins[key] = {
            "cagr": float(joint.metrics["cagr"]) > float(comparator.metrics["cagr"]),
            "max_drawdown": float(joint.metrics["max_drawdown"])
            > float(comparator.metrics["max_drawdown"]),
            "sortino": float(joint.metrics["sortino"]) > float(comparator.metrics["sortino"]),
            "calmar": float(joint.metrics["calmar"]) > float(comparator.metrics["calmar"]),
        }
    ablation_win_counts = {key: int(sum(values.values())) for key, values in ablation_wins.items()}
    actual_cagr_sign = np.sign(float(joint.metrics["cagr"]) - float(baseline.metrics["cagr"]))
    proxy_cagr_sign = np.sign(
        float(proxy_joint.metrics["cagr"]) - float(proxy_baseline.metrics["cagr"])
    )
    actual_calmar_sign = np.sign(float(joint.metrics["calmar"]) - float(baseline.metrics["calmar"]))
    proxy_calmar_sign = np.sign(
        float(proxy_joint.metrics["calmar"]) - float(proxy_baseline.metrics["calmar"])
    )
    checks = {
        "cagr_improvement": cagr_delta_pp >= float(thresholds["cagr_improvement_vs_v4_2_pp_min"]),
        "max_drawdown_not_materially_worse": max_drawdown_worsening_pp
        <= float(thresholds["max_drawdown_worsening_vs_v4_2_pp_max"]),
        "calmar_improvement": calmar_delta >= float(thresholds["calmar_improvement_vs_v4_2_min"]),
        "sortino_not_below": float(joint.metrics["sortino"]) >= float(baseline.metrics["sortino"]),
        "positive_relative_calendar_years": positive_calendar_years
        >= int(thresholds["positive_relative_calendar_years_min"]),
        "event_concentration": largest_positive_episode_share
        <= float(thresholds["largest_positive_episode_share_max"]),
        "turnover": turnover_increase <= float(thresholds["turnover_increase_max"]),
        "beats_defensive_ablation": ablation_win_counts["factor_defensive_ablation"]
        >= int(thresholds["ablation_metrics_to_beat_min"]),
        "beats_offensive_ablation": ablation_win_counts["factor_offensive_ablation"]
        >= int(thresholds["ablation_metrics_to_beat_min"]),
        "actual_proxy_cagr_direction": actual_cagr_sign == proxy_cagr_sign,
        "actual_proxy_calmar_direction": actual_calmar_sign == proxy_calmar_sign,
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_pp": cagr_delta_pp,
            "max_drawdown_worsening_pp": max_drawdown_worsening_pp,
            "calmar_delta": calmar_delta,
            "calendar_relative_returns": calendar,
            "positive_relative_calendar_years": positive_calendar_years,
            "largest_positive_episode_share": largest_positive_episode_share,
            "turnover_increase": turnover_increase,
            "ablation_wins": ablation_wins,
            "ablation_win_counts": ablation_win_counts,
        },
        "passed": bool(all(checks.values())),
    }


def run_recovery_quality_factor_experiment(
    actual_bars: Mapping[str, pd.DataFrame],
    proxy_bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    factor_contract: Mapping[str, Any],
) -> tuple[
    FactorModelOutput,
    dict[str, pd.DataFrame],
    dict[str, dict[str, StrategyResult]],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run the frozen model, actual/proxy backtests and promotion gates."""

    proxy_frame, proxy_full_baseline = build_recovery_quality_frame(
        proxy_bars, bridge_contract, factor_contract
    )
    model = fit_walk_forward_factor_model(proxy_frame, factor_contract)
    actual_frame, actual_full_baseline = build_recovery_quality_frame(
        actual_bars, bridge_contract, factor_contract
    )
    holdout_start = pd.Timestamp(factor_contract["data"]["reserved_holdout_start"])
    close_probability = model.holdout_predictions["probability"].copy()

    scopes: dict[str, tuple[pd.DataFrame, StrategyResult]] = {
        "actual": (actual_frame, actual_full_baseline),
        "qqq_proxy": (proxy_frame, proxy_full_baseline),
    }
    results_by_scope: dict[str, dict[str, StrategyResult]] = {}
    episodes_by_scope: dict[str, pd.DataFrame] = {}
    headline_by_scope: dict[str, pd.DataFrame] = {}
    for scope, (frame, full_baseline) in scopes.items():
        start = max(holdout_start, frame.index.min())
        baseline_daily = full_baseline.daily.loc[full_baseline.daily.index >= start].copy()
        baseline = StrategyResult(
            "current_v4_2",
            baseline_daily,
            full_baseline.trades.loc[pd.to_datetime(full_baseline.trades["date"]).ge(start)].copy(),
            {},
        )
        baseline.metrics = _return_metrics(baseline.daily["net_return"], annual_risk_free_rate=0.0)
        baseline.metrics.update(
            {
                "strategy": "current_v4_2",
                "turnover_units": float(baseline.daily["turnover_units"].sum()),
                "transaction_cost_paid": float(baseline.daily["transaction_cost"].sum()),
            }
        )
        probability = close_probability.reindex(baseline.daily.index)
        scope_results = {
            variant: run_factor_budget_backtest(baseline, probability, factor_contract, variant)
            for variant in VARIANTS
        }
        baseline_states = scope_results["current_v4_2"].daily["position_state"]
        for key, result in scope_results.items():
            if not baseline_states.equals(result.daily["position_state"]):
                raise AssertionError(f"{scope} {key} changed the v4.2 state trace")
        results_by_scope[scope] = scope_results
        headline_by_scope[scope] = pd.DataFrame(
            [dict(result.metrics) for result in scope_results.values()]
        ).set_index("strategy")
        episodes_by_scope[scope] = factor_budget_episodes(
            scope_results["factor_joint_budget"],
            scope_results["current_v4_2"],
            [int(value) for value in factor_contract["validation"]["event_horizons"]],
        )

    factor_gate = _factor_gate(model, factor_contract)
    strategy_gate = _strategy_gate(
        results_by_scope["actual"],
        results_by_scope["qqq_proxy"],
        episodes_by_scope["actual"],
        factor_contract,
    )
    shadow = bool(factor_gate["passed"] and strategy_gate["passed"])
    if not factor_gate["passed"]:
        decision = "recovery_quality_factor_has_no_stable_oof_signal"
    elif not strategy_gate["passed"]:
        decision = "factor_budget_does_not_stably_beat_v4_2"
    else:
        decision = "factor_budget_shadow_supported"
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "model_development_end": factor_contract["data"]["model_development_end"],
        "reserved_holdout_start": factor_contract["data"]["reserved_holdout_start"],
        "factor_gate": factor_gate,
        "strategy_gate": strategy_gate,
        "tail_risk": {
            scope: {key: tail_risk_metrics(result) for key, result in results.items()}
            for scope, results in results_by_scope.items()
        },
        "chronological": {
            scope: [
                row for result in results.values() for row in _chronological_metrics(result, 0.60)
            ]
            for scope, results in results_by_scope.items()
        },
        "decision": decision,
        "shadow_candidate_authorized": shadow,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return (
        model,
        headline_by_scope,
        results_by_scope,
        episodes_by_scope,
        diagnostics,
    )
