"""Donor-transfer model for formal v4.2 state-2 SGOV/TQQQ budgets.

The experiment preserves the target v4.2 state trace and all state-0/state-1
allocations.  A donor-only model sets one frozen 50%, 75% or 100% TQQQ budget
for each already-confirmed target state-2 episode.  QQQ-family target assets are
never used to fit the donor model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from src.research.etf_rotation_experiment import (
    StrategyResult,
    _normalise_bars,
    _return_metrics,
)
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_cross_asset_sgov_tqqq_transfer import (
    _asset_probability_spreads,
    _breadth_frame,
    _cluster_information_contributions,
    _pipeline,
    _prediction_metrics,
    assign_macro_clusters,
    build_asset_feature_frame,
)
from src.research.v4_2_cross_asset_sgov_tqqq_transfer_runtime import (
    _v4_2_result_on_index,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vix_rotation_experiment import (
    config_from_contract,
    generate_vix_decision_states,
)
from src.research.vix_rotation_runtime import prepare_vix_rotation_runtime_data
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS as V4_2_ASSETS,
    run_bridge_allocation_comparison,
)

BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"
VARIANTS = (
    "state2_cash_residual_swap",
    "state2_defensive_only",
    "state2_offensive_only",
    "state2_joint_donor_budget",
)


@dataclass(frozen=True)
class DonorState2Model:
    """Donor formal-state2 evidence and final deterministic model."""

    donor_episodes: pd.DataFrame
    cluster_oof: pd.DataFrame
    cluster_fold_metrics: pd.DataFrame
    loao_predictions: pd.DataFrame
    loao_asset_metrics: pd.DataFrame
    asset_spreads: pd.DataFrame
    cluster_contributions: pd.DataFrame
    cluster_metrics: dict[str, Any]
    loao_metrics: dict[str, Any]
    feature_names: tuple[str, ...]
    coefficients: pd.DataFrame
    fitted_pipeline: Pipeline


def _state_age(states: pd.Series, target_state: int) -> pd.Series:
    active = states.astype(int).eq(target_state)
    groups = (~active).cumsum()
    age = active.astype(int).groupby(groups).cumsum()
    return age.where(active, 0).astype(float)


def _formal_state_daily(
    bars: Mapping[str, pd.DataFrame],
    *,
    underlying: str,
    leveraged: str,
    bridge_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, Any]:
    """Run the frozen price/VIX state machine on one donor alias pair."""

    alias = {
        "QQQI": bars[underlying],
        "QQQ": bars[underlying],
        "TQQQ": bars[leveraged],
        "^VIX": bars["^VIX"],
    }
    config = config_from_contract(bridge_contract)
    prepared = prepare_vix_rotation_runtime_data(alias, config)
    decisions = generate_vix_decision_states(prepared, config)
    daily = prepared.join(decisions)
    daily["position_state"] = daily["decision_state"].shift(1).fillna(0).astype(int)
    daily["state_1_age_sessions"] = _state_age(daily["position_state"], 1)
    return daily, config


def _episode_rows(
    daily: pd.DataFrame,
    feature_frame: pd.DataFrame,
    *,
    underlying: str,
    leveraged: str,
    cash: str,
    features: Sequence[str],
) -> pd.DataFrame:
    """Extract contiguous executed state-2 episodes and prior-close features."""

    state = daily["position_state"].astype(int)
    starts = state.eq(2) & state.shift(1, fill_value=0).ne(2)
    index = daily.index
    rows: list[dict[str, Any]] = []
    for number, execution_date in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(execution_date))
        if start_location <= 0:
            continue
        end_location = start_location
        while end_location + 1 < len(index) and int(state.iloc[end_location + 1]) == 2:
            end_location += 1
        signal_close_date = index[start_location - 1]
        if signal_close_date not in feature_frame.index:
            continue
        window = daily.iloc[start_location : end_location + 1]
        leveraged_returns = window["TQQQ_next_open_return"].dropna()
        cash_returns = feature_frame.reindex(window.index)["cash_next_open_return"].dropna()
        expected = end_location - start_location + 1
        if len(leveraged_returns) != expected or len(cash_returns) != expected:
            continue
        leveraged_log = float(np.log1p(leveraged_returns).sum())
        cash_log = float(np.log1p(cash_returns).sum())
        signal = feature_frame.loc[signal_close_date]
        output: dict[str, Any] = {
            "asset_episode_id": f"{underlying}_{number:03d}",
            "underlying": underlying,
            "leveraged": leveraged,
            "cash": cash,
            "signal_close_date": signal_close_date,
            "execution_date": execution_date,
            "episode_end_date": index[end_location],
            "holding_sessions": expected,
            "leveraged_episode_return": float(np.exp(leveraged_log) - 1.0),
            "cash_episode_return": float(np.exp(cash_log) - 1.0),
            "episode_excess_log_return": leveraged_log - cash_log,
            "positive_episode_excess": int(leveraged_log > cash_log),
        }
        for feature in features:
            output[feature] = float(signal[feature])
        rows.append(output)
    return pd.DataFrame(rows)


def _augment_feature_frame(
    frame: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    close = frame["underlying_close"]
    ma200 = close.rolling(200, min_periods=200).mean()
    out = frame.copy()
    out["underlying_distance_ma200"] = close / ma200 - 1.0
    out["state_1_age_sessions"] = daily["state_1_age_sessions"].reindex(out.index)
    return out


def build_donor_state2_panel(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build donor formal state-2 episodes and donor breadth."""

    donor_pairs = {str(key): str(value) for key, value in contract["data"]["donor_pairs"].items()}
    excluded = {
        str(value) for value in contract["boundaries"]["target_symbols_excluded_from_training"]
    }
    if set(donor_pairs).intersection(excluded) or set(donor_pairs.values()).intersection(excluded):
        raise AssertionError("target symbols leaked into donor pairs")
    breadth = _breadth_frame(
        bars,
        list(donor_pairs),
        {
            "ma_short": int(bridge_contract["price_logic"]["ma_short"]),
            "ma_medium": int(bridge_contract["price_logic"]["ma_medium"]),
        },
    )
    cash = str(contract["data"]["donor_cash_proxy"])
    features = [str(value) for value in contract["features"]]
    parts: list[pd.DataFrame] = []
    for underlying, leveraged in donor_pairs.items():
        daily, _ = _formal_state_daily(
            bars,
            underlying=underlying,
            leveraged=leveraged,
            bridge_contract=bridge_contract,
        )
        feature_frame = build_asset_feature_frame(
            bars,
            underlying=underlying,
            leveraged=leveraged,
            cash=cash,
            breadth=breadth,
            contract={
                "event_definition": {
                    "ma_short": int(bridge_contract["price_logic"]["ma_short"]),
                    "ma_medium": int(bridge_contract["price_logic"]["ma_medium"]),
                    "ma_long": int(bridge_contract["price_logic"]["ma_long"]),
                    "ma_slope_sessions": 5,
                    "drawdown_window_sessions": 63,
                    "vix_high_window": 20,
                    "vix_percentile_window": 252,
                    "vix_stress_quantile": float(bridge_contract["vix_logic"]["stress_quantile"]),
                    "vix_structural_normal_quantile": float(
                        bridge_contract["vix_logic"]["normalization_quantile"]
                    ),
                    "below_ma_short_exit_sessions": int(
                        bridge_contract["price_logic"]["exit_below_ma_short_sessions"]
                    ),
                    "shock_drawdown": float(bridge_contract["price_logic"]["shock_drawdown"]),
                    "vix_retreat_from_20d_high": float(
                        bridge_contract["vix_logic"]["easing_retreat_for_qqq"]
                    ),
                },
                "data": {"risk_reference": "^VIX"},
            },
        )
        feature_frame = _augment_feature_frame(feature_frame, daily)
        episodes = _episode_rows(
            daily,
            feature_frame,
            underlying=underlying,
            leveraged=leveraged,
            cash=cash,
            features=features,
        )
        if not episodes.empty:
            parts.append(episodes)
    if not parts:
        raise ValueError("no donor formal state-2 episodes were generated")
    panel = pd.concat(parts, ignore_index=True)
    panel = assign_macro_clusters(
        panel.rename(columns={"asset_episode_id": "asset_event_id"}),
        int(contract["clustering"]["macro_cluster_calendar_days"]),
    ).rename(columns={"asset_event_id": "asset_episode_id"})
    return panel, breadth


def _model_table(episodes: pd.DataFrame) -> pd.DataFrame:
    return episodes.rename(
        columns={
            "positive_episode_excess": "positive_event_excess",
            "episode_excess_log_return": "event_excess_log_return",
            "asset_episode_id": "asset_event_id",
        }
    )


def _restore_episode_names(table: pd.DataFrame) -> pd.DataFrame:
    return table.rename(
        columns={
            "positive_event_excess": "positive_episode_excess",
            "event_excess_log_return": "episode_excess_log_return",
            "asset_event_id": "asset_episode_id",
        }
    )


def _fit_pipeline(
    table: pd.DataFrame,
    features: Sequence[str],
    contract: Mapping[str, Any],
) -> Pipeline:
    model = _pipeline(contract)
    model.fit(
        table[list(features)],
        table["positive_episode_excess"].astype(int),
    )
    return model


def fit_donor_state2_model(
    donor_episodes: pd.DataFrame,
    contract: Mapping[str, Any],
) -> DonorState2Model:
    """Run complete macro-cluster OOF, LOAO and final donor-only fit."""

    features = tuple(str(value) for value in contract["features"])
    excluded = {
        str(value) for value in contract["boundaries"]["target_symbols_excluded_from_training"]
    }
    leaked = set(donor_episodes["underlying"]).intersection(excluded) | set(
        donor_episodes["leveraged"]
    ).intersection(excluded)
    if leaked:
        raise AssertionError(f"target symbols leaked into donor episodes: {sorted(leaked)}")
    usable = donor_episodes.dropna(
        subset=[
            *features,
            "positive_episode_excess",
            "episode_excess_log_return",
        ]
    ).copy()
    if usable["positive_episode_excess"].nunique() < 2:
        raise ValueError("donor episodes require both label classes")

    cluster_parts: list[pd.DataFrame] = []
    cluster_rows: list[dict[str, Any]] = []
    for cluster in sorted(usable["macro_cluster_id"].unique()):
        validation = usable.loc[usable["macro_cluster_id"].eq(cluster)].copy()
        training = usable.loc[~usable["macro_cluster_id"].eq(cluster)].copy()
        if training["positive_episode_excess"].nunique() < 2:
            continue
        model = _fit_pipeline(training, features, contract)
        predicted = validation[
            [
                "asset_episode_id",
                "underlying",
                "leveraged",
                "macro_cluster_id",
                "signal_close_date",
                "positive_episode_excess",
                "episode_excess_log_return",
            ]
        ].copy()
        predicted["probability"] = model.predict_proba(validation[list(features)])[:, 1]
        predicted["training_episode_count"] = int(len(training))
        cluster_parts.append(predicted)
        metrics = _prediction_metrics(_model_table(predicted))
        metrics.update(
            {
                "macro_cluster_id": cluster,
                "validation_episodes": int(len(validation)),
                "training_episodes": int(len(training)),
            }
        )
        cluster_rows.append(metrics)
    if not cluster_parts:
        raise ValueError("no macro-cluster OOF predictions were produced")
    cluster_oof = pd.concat(cluster_parts, ignore_index=True).sort_values(
        ["signal_close_date", "underlying"]
    )
    cluster_metrics = _prediction_metrics(_model_table(cluster_oof))

    loao_parts: list[pd.DataFrame] = []
    loao_rows: list[dict[str, Any]] = []
    for asset in sorted(usable["underlying"].unique()):
        validation = usable.loc[usable["underlying"].eq(asset)].copy()
        training = usable.loc[~usable["underlying"].eq(asset)].copy()
        if training["positive_episode_excess"].nunique() < 2:
            continue
        model = _fit_pipeline(training, features, contract)
        predicted = validation[
            [
                "asset_episode_id",
                "underlying",
                "leveraged",
                "macro_cluster_id",
                "signal_close_date",
                "positive_episode_excess",
                "episode_excess_log_return",
            ]
        ].copy()
        predicted["probability"] = model.predict_proba(validation[list(features)])[:, 1]
        predicted["held_out_asset"] = asset
        loao_parts.append(predicted)
        metrics = _prediction_metrics(_model_table(predicted))
        metrics.update(
            {
                "held_out_asset": asset,
                "validation_episodes": int(len(validation)),
                "training_episodes": int(len(training)),
            }
        )
        loao_rows.append(metrics)
    if not loao_parts:
        raise ValueError("no leave-one-asset-out predictions were produced")
    loao = pd.concat(loao_parts, ignore_index=True).sort_values(["signal_close_date", "underlying"])
    loao_metrics = _prediction_metrics(_model_table(loao))
    asset_spreads = _asset_probability_spreads(_model_table(loao))
    cluster_contributions = _cluster_information_contributions(_model_table(cluster_oof))

    cluster_metrics.update(
        {
            "donor_episodes": int(len(usable)),
            "macro_clusters": int(usable["macro_cluster_id"].nunique()),
            "donor_assets": int(usable["underlying"].nunique()),
            "largest_positive_cluster_contribution_share": float(
                cluster_contributions["positive_contribution_share"].max()
            )
            if len(cluster_contributions)
            else 1.0,
            "maximum_single_asset_episode_share": float(
                usable["underlying"].value_counts(normalize=True).max()
            ),
        }
    )
    loao_metrics["positive_asset_spread_count"] = int(
        asset_spreads["high_minus_low_spread"].gt(0.0).sum()
    )

    final_model = _fit_pipeline(usable, features, contract)
    fitted = final_model.named_steps["model"]
    coefficients = pd.DataFrame(
        {
            "feature": list(features),
            "coefficient": np.asarray(fitted.coef_[0], dtype=float),
        }
    ).sort_values("coefficient", ascending=False)
    return DonorState2Model(
        donor_episodes=usable,
        cluster_oof=cluster_oof,
        cluster_fold_metrics=pd.DataFrame(cluster_rows),
        loao_predictions=loao,
        loao_asset_metrics=pd.DataFrame(loao_rows),
        asset_spreads=asset_spreads,
        cluster_contributions=cluster_contributions,
        cluster_metrics=cluster_metrics,
        loao_metrics=loao_metrics,
        feature_names=features,
        coefficients=coefficients,
        fitted_pipeline=final_model,
    )


def _target_feature_frame(
    bars: Mapping[str, pd.DataFrame],
    baseline: StrategyResult,
    breadth: pd.DataFrame,
    bridge_contract: Mapping[str, Any],
    cash: str,
) -> pd.DataFrame:
    feature_frame = build_asset_feature_frame(
        bars,
        underlying="QQQ",
        leveraged="TQQQ",
        cash=cash,
        breadth=breadth,
        contract={
            "event_definition": {
                "ma_short": int(bridge_contract["price_logic"]["ma_short"]),
                "ma_medium": int(bridge_contract["price_logic"]["ma_medium"]),
                "ma_long": int(bridge_contract["price_logic"]["ma_long"]),
                "ma_slope_sessions": 5,
                "drawdown_window_sessions": 63,
                "vix_high_window": 20,
                "vix_percentile_window": 252,
                "vix_stress_quantile": float(bridge_contract["vix_logic"]["stress_quantile"]),
                "vix_structural_normal_quantile": float(
                    bridge_contract["vix_logic"]["normalization_quantile"]
                ),
                "below_ma_short_exit_sessions": int(
                    bridge_contract["price_logic"]["exit_below_ma_short_sessions"]
                ),
                "shock_drawdown": float(bridge_contract["price_logic"]["shock_drawdown"]),
                "vix_retreat_from_20d_high": float(
                    bridge_contract["vix_logic"]["easing_retreat_for_qqq"]
                ),
            },
            "data": {"risk_reference": "^VIX"},
        },
    )
    feature_frame = _augment_feature_frame(
        feature_frame,
        baseline.daily.assign(state_1_age_sessions=_state_age(baseline.daily["position_state"], 1)),
    )
    return feature_frame


def build_target_state2_episodes(
    bars: Mapping[str, pd.DataFrame],
    baseline: StrategyResult,
    breadth: pd.DataFrame,
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
    cash: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_frame = _target_feature_frame(bars, baseline, breadth, bridge_contract, cash)
    episodes = _episode_rows(
        baseline.daily,
        feature_frame,
        underlying="QQQ",
        leveraged="TQQQ",
        cash=cash,
        features=[str(value) for value in contract["features"]],
    )
    if episodes.empty:
        raise ValueError("no target formal state-2 episodes were generated")
    return episodes, feature_frame


def predict_target_episodes_walk_forward(
    target_episodes: pd.DataFrame,
    donor_episodes: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Fit only donor episodes strictly earlier than each target calendar year."""

    features = tuple(str(value) for value in contract["features"])
    predictions: list[pd.DataFrame] = []
    for year, validation in target_episodes.groupby(
        pd.to_datetime(target_episodes["signal_close_date"]).dt.year
    ):
        cutoff = pd.Timestamp(year=int(year), month=1, day=1)
        training = donor_episodes.loc[
            pd.to_datetime(donor_episodes["signal_close_date"]).lt(cutoff)
        ].copy()
        if len(training) < 10 or training["positive_episode_excess"].nunique() < 2:
            continue
        model = _fit_pipeline(training, features, contract)
        predicted = validation.copy()
        predicted["probability"] = model.predict_proba(validation[list(features)])[:, 1]
        predicted["training_cutoff"] = cutoff
        predicted["training_episode_count"] = int(len(training))
        predicted["training_asset_count"] = int(training["underlying"].nunique())
        predictions.append(predicted)
    if not predictions:
        raise ValueError("no target walk-forward probabilities were produced")
    out = pd.concat(predictions, ignore_index=True).sort_values("execution_date")
    low = float(contract["strategy_mapping"]["probability_low_below"])
    high = float(contract["strategy_mapping"]["probability_high_at_or_above"])
    out["probability_bucket"] = "medium"
    out.loc[out["probability"].lt(low), "probability_bucket"] = "low"
    out.loc[out["probability"].ge(high), "probability_bucket"] = "high"
    return out


def _episode_bucket_trace(
    baseline_daily: pd.DataFrame,
    predicted_episodes: pd.DataFrame,
) -> pd.DataFrame:
    trace = pd.DataFrame(index=baseline_daily.index)
    trace["probability"] = np.nan
    trace["probability_bucket"] = "not_state_2"
    trace["episode_id"] = ""
    for episode in predicted_episodes.itertuples(index=False):
        active = (trace.index >= pd.Timestamp(episode.execution_date)) & (
            trace.index <= pd.Timestamp(episode.episode_end_date)
        )
        trace.loc[active, "probability"] = float(episode.probability)
        trace.loc[active, "probability_bucket"] = str(episode.probability_bucket)
        trace.loc[active, "episode_id"] = str(episode.asset_episode_id)
    state2 = baseline_daily["position_state"].astype(int).eq(2)
    if trace.loc[state2, "probability"].isna().any():
        missing_dates = trace.index[state2 & trace["probability"].isna()]
        raise ValueError(
            f"missing target episode probabilities for {len(missing_dates)} state-2 sessions"
        )
    return trace


def _variant_tqqq_weight(bucket: str, variant: str) -> float:
    if variant == "state2_cash_residual_swap":
        return 0.75
    if variant == "state2_defensive_only":
        return 0.50 if bucket == "low" else 0.75
    if variant == "state2_offensive_only":
        return 1.00 if bucket == "high" else 0.75
    if variant == "state2_joint_donor_budget":
        return {"low": 0.50, "medium": 0.75, "high": 1.00}[bucket]
    raise ValueError(f"unknown state2 variant: {variant}")


def run_state2_cash_budget(
    baseline: StrategyResult,
    cash_returns: pd.Series,
    predicted_episodes: pd.DataFrame,
    index: pd.DatetimeIndex,
    contract: Mapping[str, Any],
    variant: str,
) -> StrategyResult:
    """Change only formal state-2 weights on one exact comparison calendar."""

    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    daily = baseline.daily.reindex(index).copy()
    required = [
        "position_state",
        *[f"weight_{asset}" for asset in V4_2_ASSETS],
        *[f"{asset}_next_open_return" for asset in V4_2_ASSETS],
    ]
    if daily[required].isna().any().any():
        raise AssertionError("target baseline contains missing exact-calendar values")
    daily["cash_next_open_return"] = cash_returns.reindex(index)
    if daily["cash_next_open_return"].isna().any():
        raise AssertionError("cash sleeve contains missing exact-calendar returns")
    trace = _episode_bucket_trace(daily, predicted_episodes)
    daily = daily.join(trace)

    weights = pd.DataFrame(
        {
            "QQQI": daily["weight_QQQI"],
            "QQQ": daily["weight_QQQ"],
            "TQQQ": daily["weight_TQQQ"],
            "cash": 0.0,
        },
        index=index,
    )
    state2 = daily["position_state"].astype(int).eq(2)
    for date in index[state2]:
        bucket = str(daily.at[date, "probability_bucket"])
        tqqq = _variant_tqqq_weight(bucket, variant)
        weights.at[date, "QQQI"] = 0.0
        weights.at[date, "QQQ"] = 0.0
        weights.at[date, "TQQQ"] = tqqq
        weights.at[date, "cash"] = 1.0 - tqqq
    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("state2 cash-budget weights must sum to one")
    if (weights < -1e-12).any().any() or (weights > 1.0 + 1e-12).any().any():
        raise AssertionError("state2 cash-budget weights must stay in [0,1]")

    daily["weight_QQQI"] = weights["QQQI"]
    daily["weight_QQQ"] = weights["QQQ"]
    daily["weight_TQQQ"] = weights["TQQQ"]
    daily["weight_cash"] = weights["cash"]
    daily["gross_return"] = (
        daily["weight_QQQI"] * daily["QQQI_next_open_return"]
        + daily["weight_QQQ"] * daily["QQQ_next_open_return"]
        + daily["weight_TQQQ"] * daily["TQQQ_next_open_return"]
        + daily["weight_cash"] * daily["cash_next_open_return"]
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    changed = weights.ne(weights.shift()).any(axis=1)
    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(contract["boundaries"]["annual_risk_free_rate"]),
    )
    metrics.update(
        {
            "strategy": variant,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "switch_count": int(max(int(changed.sum()) - 1, 0)),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
            "average_cash_weight": float(daily["weight_cash"].mean()),
            "low_state2_sessions": int((state2 & daily["probability_bucket"].eq("low")).sum()),
            "medium_state2_sessions": int(
                (state2 & daily["probability_bucket"].eq("medium")).sum()
            ),
            "high_state2_sessions": int((state2 & daily["probability_bucket"].eq("high")).sum()),
        }
    )
    trades = daily.loc[
        changed,
        [
            "position_state",
            "probability",
            "probability_bucket",
            "episode_id",
            "weight_QQQI",
            "weight_QQQ",
            "weight_TQQQ",
            "weight_cash",
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(variant, daily, trades, metrics)


def _calendar_relative_returns(
    candidate: StrategyResult, baseline: StrategyResult
) -> dict[str, float]:
    aligned = pd.concat(
        [
            candidate.daily["net_return"].rename("candidate"),
            baseline.daily["net_return"].rename("baseline"),
        ],
        axis=1,
    ).dropna()
    output: dict[str, float] = {}
    for year, group in aligned.groupby(aligned.index.year):
        candidate_return = float((1.0 + group["candidate"]).prod() - 1.0)
        baseline_return = float((1.0 + group["baseline"]).prod() - 1.0)
        output[str(int(year))] = candidate_return - baseline_return
    return output


def state2_episode_attribution(
    predicted_episodes: pd.DataFrame,
    candidate: StrategyResult,
    baseline: StrategyResult,
) -> pd.DataFrame:
    aligned = pd.concat(
        [
            candidate.daily["net_return"].rename("candidate"),
            baseline.daily["net_return"].rename("baseline"),
        ],
        axis=1,
    ).dropna()
    rows: list[dict[str, Any]] = []
    for episode in predicted_episodes.itertuples(index=False):
        window = aligned.loc[
            (aligned.index >= pd.Timestamp(episode.execution_date))
            & (aligned.index <= pd.Timestamp(episode.episode_end_date))
        ]
        if window.empty:
            continue
        candidate_log = float(np.log1p(window["candidate"]).sum())
        baseline_log = float(np.log1p(window["baseline"]).sum())
        rows.append(
            {
                "asset_episode_id": episode.asset_episode_id,
                "signal_close_date": episode.signal_close_date,
                "execution_date": episode.execution_date,
                "episode_end_date": episode.episode_end_date,
                "probability": float(episode.probability),
                "probability_bucket": str(episode.probability_bucket),
                "candidate_return": float(np.exp(candidate_log) - 1.0),
                "v4_2_return": float(np.exp(baseline_log) - 1.0),
                "relative_return": float(np.exp(candidate_log - baseline_log) - 1.0),
            }
        )
    return pd.DataFrame(rows)


def _scope_index(
    baseline: StrategyResult,
    cash_returns: pd.Series,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DatetimeIndex:
    index = baseline.daily.index.intersection(cash_returns.dropna().index)
    index = index[(index >= start) & (index <= end)].sort_values()
    if len(index) < 40:
        raise ValueError("state2 target scope is too short")
    return pd.DatetimeIndex(index)


def _donor_gate(
    model: DonorState2Model,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    cluster = contract["validation"]["macro_cluster_oof"]
    loao = contract["validation"]["leave_one_asset_out"]
    cm = model.cluster_metrics
    lm = model.loao_metrics
    checks = {
        "minimum_donor_episodes": int(cm["donor_episodes"])
        >= int(cluster["minimum_donor_episodes"]),
        "minimum_macro_clusters": int(cm["macro_clusters"])
        >= int(cluster["minimum_macro_clusters"]),
        "cluster_auc": np.isfinite(float(cm["roc_auc"]))
        and float(cm["roc_auc"]) >= float(cluster["roc_auc_min"]),
        "cluster_ic": np.isfinite(float(cm["spearman_ic"]))
        and float(cm["spearman_ic"]) >= float(cluster["spearman_ic_min"]),
        "cluster_spread": float(cm["top_bottom_quartile_spread"]) > 0.0,
        "cluster_concentration": float(cm["largest_positive_cluster_contribution_share"])
        <= float(cluster["largest_positive_cluster_contribution_max"]),
        "asset_episode_share": float(cm["maximum_single_asset_episode_share"])
        <= float(cluster["maximum_single_asset_episode_share"]),
        "loao_auc": np.isfinite(float(lm["roc_auc"]))
        and float(lm["roc_auc"]) >= float(loao["roc_auc_min"]),
        "loao_ic": np.isfinite(float(lm["spearman_ic"]))
        and float(lm["spearman_ic"]) >= float(loao["spearman_ic_min"]),
        "loao_spread": float(lm["top_bottom_quartile_spread"]) > 0.0,
        "loao_positive_assets": int(lm["positive_asset_spread_count"])
        >= int(loao["positive_asset_spread_count_min"]),
    }
    return {
        "checks": checks,
        "cluster_metrics": cm,
        "loao_metrics": lm,
        "passed": bool(all(checks.values())),
    }


def _primary_gate(
    results: Mapping[str, StrategyResult],
    attribution: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["primary_target_gate"]
    baseline = results["frozen_v4_2"]
    joint = results["state2_joint_donor_budget"]
    cagr_delta_pp = (float(joint.metrics["cagr"]) - float(baseline.metrics["cagr"])) * 100.0
    drawdown_worsening_pp = max(
        0.0,
        (float(baseline.metrics["max_drawdown"]) - float(joint.metrics["max_drawdown"])) * 100.0,
    )
    calmar_delta = float(joint.metrics["calmar"]) - float(baseline.metrics["calmar"])
    calendar = _calendar_relative_returns(joint, baseline)
    positive_years = int(sum(value > 0.0 for value in calendar.values()))
    positive_events = (
        attribution["relative_return"].clip(lower=0.0)
        if not attribution.empty
        else pd.Series(dtype=float)
    )
    event_share = (
        float(positive_events.max() / positive_events.sum())
        if len(positive_events) and float(positive_events.sum()) > 0.0
        else 1.0
    )
    turnover_increase = (
        float(joint.metrics["turnover_units"]) / float(baseline.metrics["turnover_units"]) - 1.0
    )
    ablation_wins: dict[str, dict[str, bool]] = {}
    for key in (
        "state2_cash_residual_swap",
        "state2_defensive_only",
        "state2_offensive_only",
    ):
        comparator = results[key]
        ablation_wins[key] = {
            "cagr": float(joint.metrics["cagr"]) > float(comparator.metrics["cagr"]),
            "max_drawdown": float(joint.metrics["max_drawdown"])
            > float(comparator.metrics["max_drawdown"]),
            "sortino": float(joint.metrics["sortino"]) > float(comparator.metrics["sortino"]),
            "calmar": float(joint.metrics["calmar"]) > float(comparator.metrics["calmar"]),
        }
    counts = {key: int(sum(values.values())) for key, values in ablation_wins.items()}
    checks = {
        "cagr_improvement": cagr_delta_pp >= float(thresholds["cagr_improvement_vs_v4_2_pp_min"]),
        "max_drawdown": drawdown_worsening_pp
        <= float(thresholds["max_drawdown_worsening_vs_v4_2_pp_max"]),
        "calmar_improvement": calmar_delta >= float(thresholds["calmar_improvement_vs_v4_2_min"]),
        "sortino": float(joint.metrics["sortino"]) >= float(baseline.metrics["sortino"]),
        "positive_years": positive_years >= int(thresholds["positive_relative_calendar_years_min"]),
        "episode_concentration": event_share
        <= float(thresholds["largest_positive_episode_share_max"]),
        "turnover": turnover_increase <= float(thresholds["turnover_increase_max"]),
        **{
            f"beats_{key}": count >= int(thresholds["ablation_metrics_to_beat_min"])
            for key, count in counts.items()
        },
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_pp": cagr_delta_pp,
            "max_drawdown_worsening_pp": drawdown_worsening_pp,
            "calmar_delta": calmar_delta,
            "calendar_relative_returns": calendar,
            "positive_relative_calendar_years": positive_years,
            "largest_positive_episode_share": event_share,
            "turnover_increase": turnover_increase,
            "ablation_wins": ablation_wins,
            "ablation_win_counts": counts,
        },
        "passed": bool(all(checks.values())),
    }


def _contradiction_gate(
    quarantine: Mapping[str, StrategyResult],
    actual: Mapping[str, StrategyResult],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["contradiction_gate"]
    q_base = quarantine["frozen_v4_2"]
    q_joint = quarantine["state2_joint_donor_budget"]
    a_base = actual["frozen_v4_2"]
    a_joint = actual["state2_joint_donor_budget"]
    q_cagr = float(q_joint.metrics["cagr"]) - float(q_base.metrics["cagr"])
    q_calmar = float(q_joint.metrics["calmar"]) - float(q_base.metrics["calmar"])
    a_cagr = float(a_joint.metrics["cagr"]) - float(a_base.metrics["cagr"])
    a_calmar = float(a_joint.metrics["calmar"]) - float(a_base.metrics["calmar"])
    a_drawdown_worsening_pp = max(
        0.0,
        (float(a_base.metrics["max_drawdown"]) - float(a_joint.metrics["max_drawdown"])) * 100.0,
    )
    checks = {
        "quarantine_not_jointly_negative": not (q_cagr < 0.0 and q_calmar < 0.0),
        "actual_not_jointly_negative": not (a_cagr < 0.0 and a_calmar < 0.0),
        "actual_drawdown": a_drawdown_worsening_pp
        <= float(thresholds["actual_max_drawdown_worsening_pp_max"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "quarantine_cagr_delta": q_cagr,
            "quarantine_calmar_delta": q_calmar,
            "actual_cagr_delta": a_cagr,
            "actual_calmar_delta": a_calmar,
            "actual_drawdown_worsening_pp": a_drawdown_worsening_pp,
        },
        "passed": bool(all(checks.values())),
    }


def run_donor_state2_sgov_tqqq(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[
    DonorState2Model,
    dict[str, pd.DataFrame],
    dict[str, dict[str, StrategyResult]],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run donor evidence and three target scopes with an unchanged v4.2 trace."""

    required = {str(value) for value in contract["data"]["required_symbols"]}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    donor_episodes, breadth = build_donor_state2_panel(bars, bridge_contract, contract)
    model = fit_donor_state2_model(donor_episodes, contract)

    _, actual_base_results, _, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    _, proxy_base_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    actual_full = actual_base_results[BASELINE_KEY]
    proxy_full = proxy_base_results[BASELINE_KEY]

    target_proxy_episodes, proxy_feature_frame = build_target_state2_episodes(
        bars,
        proxy_full,
        breadth,
        bridge_contract,
        contract,
        str(contract["data"]["donor_cash_proxy"]),
    )
    target_actual_episodes, actual_feature_frame = build_target_state2_episodes(
        bars,
        actual_full,
        breadth,
        bridge_contract,
        contract,
        str(contract["data"]["actual_cash_asset"]),
    )
    proxy_predictions = predict_target_episodes_walk_forward(
        target_proxy_episodes, donor_episodes, contract
    )
    actual_predictions = predict_target_episodes_walk_forward(
        target_actual_episodes, donor_episodes, contract
    )

    scopes = {
        "primary": {
            "baseline": proxy_full,
            "feature_frame": proxy_feature_frame,
            "predictions": proxy_predictions,
            "cash": "BIL",
            "start": pd.Timestamp(contract["validation"]["primary_target_start"]),
            "end": pd.Timestamp(contract["validation"]["primary_target_end"]),
        },
        "quarantine": {
            "baseline": proxy_full,
            "feature_frame": proxy_feature_frame,
            "predictions": proxy_predictions,
            "cash": "BIL",
            "start": pd.Timestamp(contract["validation"]["quarantine_proxy_start"]),
            "end": pd.Timestamp(contract["validation"]["quarantine_proxy_end"]),
        },
        "actual": {
            "baseline": actual_full,
            "feature_frame": actual_feature_frame,
            "predictions": actual_predictions,
            "cash": "SGOV",
            "start": max(
                pd.Timestamp(contract["validation"]["actual_start"]),
                actual_full.daily.index.min(),
            ),
            "end": min(
                actual_full.daily.index.max(),
                actual_feature_frame.index.max(),
            ),
        },
    }
    results_by_scope: dict[str, dict[str, StrategyResult]] = {}
    attribution_by_scope: dict[str, pd.DataFrame] = {}
    headline_by_scope: dict[str, pd.DataFrame] = {}
    predictions_by_scope: dict[str, pd.DataFrame] = {}

    for scope, spec in scopes.items():
        cash_returns = spec["feature_frame"]["cash_next_open_return"]
        index = _scope_index(
            spec["baseline"],
            cash_returns,
            spec["start"],
            spec["end"],
        )
        predictions = (
            spec["predictions"]
            .loc[
                pd.to_datetime(spec["predictions"]["execution_date"]).between(
                    spec["start"], spec["end"]
                )
            ]
            .copy()
        )
        if predictions.empty:
            raise ValueError(f"{scope} has no target state-2 predictions")
        baseline = _v4_2_result_on_index(spec["baseline"], index, contract, "frozen_v4_2")
        scope_results: dict[str, StrategyResult] = {"frozen_v4_2": baseline}
        for variant in VARIANTS:
            scope_results[variant] = run_state2_cash_budget(
                spec["baseline"],
                cash_returns,
                predictions,
                index,
                contract,
                variant,
            )
            if not baseline.daily["position_state"].equals(
                scope_results[variant].daily["position_state"]
            ):
                raise AssertionError(f"{scope} {variant} changed the v4.2 state trace")
            outside = baseline.daily["position_state"].astype(int).ne(2)
            for asset in V4_2_ASSETS:
                if not np.allclose(
                    baseline.daily.loc[outside, f"weight_{asset}"],
                    scope_results[variant].daily.loc[outside, f"weight_{asset}"],
                ):
                    raise AssertionError(f"{scope} {variant} changed state0/state1 {asset} weights")
        results_by_scope[scope] = scope_results
        predictions_by_scope[scope] = predictions
        headline_by_scope[scope] = pd.DataFrame(
            [dict(result.metrics) for result in scope_results.values()]
        ).set_index("strategy")
        attribution_by_scope[scope] = state2_episode_attribution(
            predictions,
            scope_results["state2_joint_donor_budget"],
            baseline,
        )

    donor_gate = _donor_gate(model, contract)
    primary_gate = _primary_gate(
        results_by_scope["primary"],
        attribution_by_scope["primary"],
        contract,
    )
    contradiction_gate = _contradiction_gate(
        results_by_scope["quarantine"],
        results_by_scope["actual"],
        contract,
    )
    shadow = bool(donor_gate["passed"] and primary_gate["passed"] and contradiction_gate["passed"])
    if not donor_gate["passed"]:
        decision = "donor_formal_state2_transfer_signal_not_stable"
    elif not primary_gate["passed"]:
        decision = "state2_cash_budget_does_not_beat_v4_2_primary_window"
    elif not contradiction_gate["passed"]:
        decision = "state2_cash_budget_blocked_by_later_contradiction"
    else:
        decision = "state2_cash_budget_prospective_shadow_supported"

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "post_result_hypothesis": True,
        "target_excluded_from_training": True,
        "state_trace_unchanged": True,
        "state_0_state_1_allocations_unchanged": True,
        "donor_gate": donor_gate,
        "primary_gate": primary_gate,
        "contradiction_gate": contradiction_gate,
        "scope_samples": {
            scope: {
                "start": results["frozen_v4_2"].daily.index.min(),
                "end": results["frozen_v4_2"].daily.index.max(),
                "observations": int(len(results["frozen_v4_2"].daily)),
                "predicted_episodes": int(len(predictions_by_scope[scope])),
                "bucket_counts": predictions_by_scope[scope]["probability_bucket"]
                .value_counts()
                .to_dict(),
            }
            for scope, results in results_by_scope.items()
        },
        "tail_risk": {
            scope: {key: tail_risk_metrics(result) for key, result in results.items()}
            for scope, results in results_by_scope.items()
        },
        "decision": decision,
        "shadow_candidate_authorized": shadow,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return (
        model,
        predictions_by_scope,
        headline_by_scope,
        results_by_scope,
        attribution_by_scope,
        diagnostics,
    )
