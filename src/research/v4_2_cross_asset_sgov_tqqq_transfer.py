"""Cross-asset independent recovery events for an SGOV/TQQQ challenger.

The donor model is fitted only on non-QQQ underlying/3x ETF pairs. QQQ, TQQQ,
QQQI, SGOV and VXN are final target-evaluation inputs and are excluded from
model fitting. Donor events are non-overlapping shock cycles and validation
leaves out complete macro date clusters.
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

from src.research.etf_rotation_experiment import (
    StrategyResult,
    _normalise_bars,
    _return_metrics,
)
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS as V4_2_ASSETS,
    run_bridge_allocation_comparison,
)

BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"
TARGET_STRATEGIES = (
    "buy_hold_sgov",
    "static_50_sgov_50_tqqq",
    "structural_only",
    "event_only",
    "joint_structural_event",
)


@dataclass(frozen=True)
class ClusterTransferModel:
    """Frozen donor model and cluster-isolated evidence."""

    donor_events: pd.DataFrame
    oof_predictions: pd.DataFrame
    fold_metrics: pd.DataFrame
    asset_spreads: pd.DataFrame
    cluster_contributions: pd.DataFrame
    aggregate_metrics: dict[str, Any]
    feature_names: tuple[str, ...]
    coefficients: pd.DataFrame
    fitted_pipeline: Pipeline


def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    def latest_rank(values: np.ndarray) -> float:
        latest = values[-1]
        return float(np.mean(values <= latest))

    return series.rolling(window, min_periods=window).apply(latest_rank, raw=True)


def _next_open_return(open_price: pd.Series) -> pd.Series:
    return open_price.shift(-1) / open_price - 1.0


def _breadth_frame(
    bars: Mapping[str, pd.DataFrame],
    underlyings: Sequence[str],
    config: Mapping[str, Any],
) -> pd.DataFrame:
    ma_short = int(config["ma_short"])
    ma_medium = int(config["ma_medium"])
    closes: dict[str, pd.Series] = {}
    for symbol in underlyings:
        closes[symbol] = _normalise_bars(bars[symbol], symbol)["close"]
    panel = pd.concat(closes, axis=1).sort_index()
    above_short = pd.DataFrame(index=panel.index)
    above_medium = pd.DataFrame(index=panel.index)
    for symbol in underlyings:
        close = panel[symbol]
        above_short[symbol] = close.gt(
            close.rolling(ma_short, min_periods=ma_short).mean()
        )
        above_medium[symbol] = close.gt(
            close.rolling(ma_medium, min_periods=ma_medium).mean()
        )
    return pd.DataFrame(
        {
            "donor_breadth_above_ma20": above_short.mean(axis=1),
            "donor_breadth_above_ma50": above_medium.mean(axis=1),
        }
    )


def build_asset_feature_frame(
    bars: Mapping[str, pd.DataFrame],
    *,
    underlying: str,
    leveraged: str,
    cash: str,
    breadth: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Build close-observable features and next-open economic returns."""

    event = contract["event_definition"]
    risk_symbol = str(contract["data"]["risk_reference"])
    underlying_bars = _normalise_bars(bars[underlying], underlying)
    leveraged_bars = _normalise_bars(bars[leveraged], leveraged)
    cash_bars = _normalise_bars(bars[cash], cash)
    vix_bars = _normalise_bars(bars[risk_symbol], risk_symbol)

    frame = pd.concat(
        {
            "underlying_open": underlying_bars["open"],
            "underlying_close": underlying_bars["close"],
            "leveraged_open": leveraged_bars["open"],
            "leveraged_close": leveraged_bars["close"],
            "cash_open": cash_bars["open"],
            "cash_close": cash_bars["close"],
            "vix_close": vix_bars["close"],
        },
        axis=1,
    ).join(breadth, how="left")
    frame = frame.sort_index()
    close = frame["underlying_close"]
    ma_short_n = int(event["ma_short"])
    ma_medium_n = int(event["ma_medium"])
    ma_long_n = int(event["ma_long"])
    slope_n = int(event["ma_slope_sessions"])
    drawdown_n = int(event["drawdown_window_sessions"])
    vix_high_n = int(event["vix_high_window"])
    vix_percentile_n = int(event["vix_percentile_window"])

    frame["ma20"] = close.rolling(ma_short_n, min_periods=ma_short_n).mean()
    frame["ma50"] = close.rolling(ma_medium_n, min_periods=ma_medium_n).mean()
    frame["ma200"] = close.rolling(ma_long_n, min_periods=ma_long_n).mean()
    frame["underlying_return_5d"] = close.pct_change(5)
    frame["underlying_return_20d"] = close.pct_change(20)
    frame["underlying_distance_ma20"] = close / frame["ma20"] - 1.0
    frame["underlying_distance_ma50"] = close / frame["ma50"] - 1.0
    frame["underlying_ma20_slope_5d"] = (
        frame["ma20"] / frame["ma20"].shift(slope_n) - 1.0
    )
    daily_return = close.pct_change()
    frame["underlying_realized_volatility_20d"] = (
        daily_return.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252.0)
    )
    rolling_high = close.rolling(drawdown_n, min_periods=drawdown_n).max()
    frame["underlying_drawdown_63d"] = close / rolling_high - 1.0

    vix = frame["vix_close"]
    frame["vix_return_5d"] = vix.pct_change(5)
    frame["vix_retreat_from_20d_high"] = (
        vix / vix.rolling(vix_high_n, min_periods=vix_high_n).max() - 1.0
    )
    frame["vix_percentile_252d"] = _rolling_percentile(vix, vix_percentile_n)
    frame["vix_stress"] = frame["vix_percentile_252d"].ge(
        float(event["vix_stress_quantile"])
    )
    frame["vix_structural_normal"] = frame["vix_percentile_252d"].lt(
        float(event["vix_structural_normal_quantile"])
    )

    below = close.lt(frame["ma20"])
    below_n = int(event["below_ma_short_exit_sessions"])
    frame["below_ma20_exit"] = (
        below.rolling(below_n, min_periods=below_n).sum().eq(below_n)
    )
    frame["shock"] = frame["underlying_drawdown_63d"].le(
        -abs(float(event["shock_drawdown"]))
    )
    frame["entry_ready"] = (
        close.gt(frame["ma20"])
        & frame["underlying_ma20_slope_5d"].gt(0.0)
        & frame["vix_retreat_from_20d_high"].le(
            -abs(float(event["vix_retreat_from_20d_high"]))
        )
    )
    frame["structural_bull"] = (
        close.gt(frame["ma200"])
        & frame["ma50"].gt(frame["ma200"])
        & frame["vix_structural_normal"]
    )
    frame["leveraged_next_open_return"] = _next_open_return(
        frame["leveraged_open"]
    )
    frame["cash_next_open_return"] = _next_open_return(frame["cash_open"])
    return frame.dropna(
        subset=[
            "underlying_open",
            "underlying_close",
            "leveraged_open",
            "leveraged_close",
            "cash_open",
            "cash_close",
            "vix_close",
        ]
    )


def _path_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    equity = (1.0 + returns.astype(float)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def build_nonoverlapping_events(
    frame: pd.DataFrame,
    *,
    underlying: str,
    leveraged: str,
    cash: str,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Admit at most one recovery event per locked shock cycle."""

    event = contract["event_definition"]
    features = [str(value) for value in contract["features"]]
    max_holding = int(event["max_event_holding_sessions"])
    cooldown = int(event["cycle_cooldown_sessions"])
    recovered_level = -abs(float(event["cycle_recovery_drawdown"]))

    rows: list[dict[str, Any]] = []
    index = frame.index
    cycle_active = False
    cycle_locked = False
    shock_position: int | None = None
    last_event_end = -10_000
    position = 0
    while position < len(frame) - 1:
        drawdown = frame.iloc[position]["underlying_drawdown_63d"]
        if cycle_locked and (
            (pd.notna(drawdown) and float(drawdown) > recovered_level)
            or position - last_event_end >= cooldown
        ):
            cycle_locked = False

        if (
            not cycle_active
            and not cycle_locked
            and bool(frame.iloc[position]["shock"])
        ):
            cycle_active = True
            shock_position = position

        if (
            cycle_active
            and shock_position is not None
            and position > shock_position
            and bool(frame.iloc[position]["entry_ready"])
            and position + 1 < len(frame)
        ):
            signal_position = position
            execution_position = position + 1
            max_end = min(execution_position + max_holding - 1, len(frame) - 2)
            end_position = max_end
            exit_reason = "max_holding"
            for cursor in range(execution_position, max_end + 1):
                row = frame.iloc[cursor]
                if bool(row["below_ma20_exit"]):
                    end_position = cursor
                    exit_reason = "two_closes_below_ma20"
                    break
                if bool(row["vix_stress"]):
                    end_position = cursor
                    exit_reason = "vix_stress"
                    break

            leveraged_returns = frame["leveraged_next_open_return"].iloc[
                execution_position : end_position + 1
            ].dropna()
            cash_returns = frame["cash_next_open_return"].iloc[
                execution_position : end_position + 1
            ].dropna()
            expected_length = end_position - execution_position + 1
            if (
                len(leveraged_returns) == expected_length
                and len(cash_returns) == expected_length
                and expected_length > 0
            ):
                leveraged_log = float(np.log1p(leveraged_returns).sum())
                cash_log = float(np.log1p(cash_returns).sum())
                signal = frame.iloc[signal_position]
                output: dict[str, Any] = {
                    "underlying": underlying,
                    "leveraged": leveraged,
                    "cash": cash,
                    "shock_date": index[shock_position],
                    "signal_close_date": index[signal_position],
                    "execution_date": index[execution_position],
                    "event_end_date": index[end_position],
                    "holding_sessions": expected_length,
                    "exit_reason": exit_reason,
                    "leveraged_event_return": float(np.exp(leveraged_log) - 1.0),
                    "cash_event_return": float(np.exp(cash_log) - 1.0),
                    "event_excess_log_return": leveraged_log - cash_log,
                    "positive_event_excess": int(leveraged_log > cash_log),
                    "leveraged_event_max_drawdown": _path_drawdown(
                        leveraged_returns
                    ),
                }
                for feature in features:
                    output[feature] = float(signal[feature])
                rows.append(output)

            cycle_active = False
            cycle_locked = True
            last_event_end = end_position
            shock_position = None
            position = end_position + 1
            continue

        if (
            cycle_active
            and shock_position is not None
            and position > shock_position
            and pd.notna(drawdown)
            and float(drawdown) > recovered_level
        ):
            cycle_active = False
            shock_position = None
        position += 1

    events = pd.DataFrame(rows)
    if events.empty:
        return events
    events = events.sort_values("execution_date").reset_index(drop=True)
    previous_end = events["event_end_date"].shift(1)
    overlap = events["execution_date"].lt(previous_end)
    if bool(overlap.fillna(False).any()):
        raise AssertionError(f"{underlying} recovery events overlap")
    events["asset_event_id"] = [
        f"{underlying}_{number:03d}" for number in range(1, len(events) + 1)
    ]
    return events


def assign_macro_clusters(
    events: pd.DataFrame, calendar_days: int
) -> pd.DataFrame:
    """Assign one cluster to events whose starts share one macro window."""

    if events.empty:
        return events.copy()
    ordered = events.sort_values(
        ["signal_close_date", "underlying", "asset_event_id"]
    ).reset_index(drop=True)
    cluster_number = 0
    cluster_anchor: pd.Timestamp | None = None
    cluster_ids: list[str] = []
    for value in pd.to_datetime(ordered["signal_close_date"]):
        date = pd.Timestamp(value)
        if cluster_anchor is None or (date - cluster_anchor).days > calendar_days:
            cluster_number += 1
            cluster_anchor = date
        cluster_ids.append(f"macro_{cluster_number:03d}")
    ordered["macro_cluster_id"] = cluster_ids
    return ordered


def build_donor_event_panel(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build six donor event sets without any QQQ-family fitting input."""

    donor_pairs = {
        str(key): str(value)
        for key, value in contract["data"]["donor_pairs"].items()
    }
    excluded = {
        str(value)
        for value in contract["boundaries"][
            "target_symbols_excluded_from_training"
        ]
    }
    if set(donor_pairs).intersection(excluded) or set(
        donor_pairs.values()
    ).intersection(excluded):
        raise AssertionError("target symbols leaked into donor pairs")

    breadth = _breadth_frame(
        bars,
        list(donor_pairs),
        contract["event_definition"],
    )
    cash = str(contract["data"]["donor_cash_proxy"])
    event_parts: list[pd.DataFrame] = []
    frames: dict[str, pd.DataFrame] = {}
    for underlying, leveraged in donor_pairs.items():
        frame = build_asset_feature_frame(
            bars,
            underlying=underlying,
            leveraged=leveraged,
            cash=cash,
            breadth=breadth,
            contract=contract,
        )
        frames[underlying] = frame
        events = build_nonoverlapping_events(
            frame,
            underlying=underlying,
            leveraged=leveraged,
            cash=cash,
            contract=contract,
        )
        if not events.empty:
            event_parts.append(events)
    if not event_parts:
        raise ValueError("no donor events were generated")
    panel = pd.concat(event_parts, ignore_index=True)
    panel = assign_macro_clusters(
        panel, int(contract["event_definition"]["macro_cluster_calendar_days"])
    )
    return panel, frames


def _pipeline(contract: Mapping[str, Any]) -> Pipeline:
    estimator = contract["estimator"]
    return Pipeline(
        [
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


def _prediction_metrics(table: pd.DataFrame) -> dict[str, Any]:
    valid = table.dropna(
        subset=["probability", "positive_event_excess", "event_excess_log_return"]
    ).copy()
    if valid.empty:
        raise ValueError("prediction sample is empty")
    probability = valid["probability"].astype(float)
    label = valid["positive_event_excess"].astype(int)
    continuous = valid["event_excess_log_return"].astype(float)
    quartile = pd.qcut(
        probability.rank(method="first"), 4, labels=False, duplicates="drop"
    )
    bottom = continuous.loc[quartile.eq(int(quartile.min()))]
    top = continuous.loc[quartile.eq(int(quartile.max()))]
    return {
        "observations": int(len(valid)),
        "positive_rate": float(label.mean()),
        "roc_auc": (
            float(roc_auc_score(label, probability))
            if label.nunique() >= 2
            else float("nan")
        ),
        "brier_score": float(brier_score_loss(label, probability)),
        "spearman_ic": float(probability.corr(continuous, method="spearman")),
        "top_quartile_mean_excess_log_return": float(top.mean()),
        "bottom_quartile_mean_excess_log_return": float(bottom.mean()),
        "top_bottom_quartile_spread": float(top.mean() - bottom.mean()),
    }


def _asset_probability_spreads(oof: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for asset, group in oof.groupby("underlying"):
        local = group.sort_values("probability").copy()
        split = max(len(local) // 2, 1)
        low = local.iloc[:split]["event_excess_log_return"]
        high = local.iloc[split:]["event_excess_log_return"]
        rows.append(
            {
                "underlying": asset,
                "events": int(len(local)),
                "high_probability_mean_excess": float(high.mean())
                if len(high)
                else float("nan"),
                "low_probability_mean_excess": float(low.mean())
                if len(low)
                else float("nan"),
                "high_minus_low_spread": float(high.mean() - low.mean())
                if len(high) and len(low)
                else float("nan"),
            }
        )
    return pd.DataFrame(rows).sort_values("underlying").reset_index(drop=True)


def _cluster_information_contributions(oof: pd.DataFrame) -> pd.DataFrame:
    local = oof.copy()
    p_centered = local["probability"] - local["probability"].mean()
    y_centered = (
        local["event_excess_log_return"]
        - local["event_excess_log_return"].mean()
    )
    local["positive_information_contribution"] = (
        p_centered * y_centered
    ).clip(lower=0.0)
    result = (
        local.groupby("macro_cluster_id", as_index=False)[
            "positive_information_contribution"
        ]
        .sum()
        .sort_values("positive_information_contribution", ascending=False)
        .reset_index(drop=True)
    )
    total = float(result["positive_information_contribution"].sum())
    result["positive_contribution_share"] = (
        result["positive_information_contribution"] / total
        if total > 0.0
        else 0.0
    )
    return result


def fit_cluster_transfer_model(
    donor_events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> ClusterTransferModel:
    """Fit leave-one-macro-cluster-out OOF and one final donor-only model."""

    features = tuple(str(value) for value in contract["features"])
    development_end = pd.Timestamp(contract["data"]["model_development_end"])
    excluded = {
        str(value)
        for value in contract["boundaries"][
            "target_symbols_excluded_from_training"
        ]
    }
    development = donor_events.loc[
        pd.to_datetime(donor_events["signal_close_date"]).le(development_end)
    ].copy()
    if development.empty:
        raise ValueError("donor development sample is empty")
    leaked = set(development["underlying"]).intersection(excluded) | set(
        development["leveraged"]
    ).intersection(excluded)
    if leaked:
        raise AssertionError(
            f"target symbols leaked into donor training: {sorted(leaked)}"
        )
    development = development.dropna(
        subset=[*features, "positive_event_excess", "event_excess_log_return"]
    ).copy()

    oof_parts: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    for cluster_id in sorted(development["macro_cluster_id"].unique()):
        validation = development.loc[
            development["macro_cluster_id"].eq(cluster_id)
        ].copy()
        training = development.loc[
            ~development["macro_cluster_id"].eq(cluster_id)
        ].copy()
        if training["positive_event_excess"].nunique() < 2:
            continue
        model = _pipeline(contract)
        model.fit(
            training[list(features)],
            training["positive_event_excess"].astype(int),
        )
        predicted = validation[
            [
                "asset_event_id",
                "underlying",
                "leveraged",
                "macro_cluster_id",
                "signal_close_date",
                "positive_event_excess",
                "event_excess_log_return",
            ]
        ].copy()
        predicted["probability"] = model.predict_proba(
            validation[list(features)]
        )[:, 1]
        predicted["training_event_count"] = int(len(training))
        predicted["training_cluster_count"] = int(
            training["macro_cluster_id"].nunique()
        )
        oof_parts.append(predicted)
        fold_metrics = _prediction_metrics(predicted)
        fold_metrics.update(
            {
                "macro_cluster_id": cluster_id,
                "validation_events": int(len(validation)),
                "training_events": int(len(training)),
                "training_clusters": int(
                    training["macro_cluster_id"].nunique()
                ),
                "validation_start": pd.to_datetime(
                    validation["signal_close_date"]
                ).min(),
                "validation_end": pd.to_datetime(
                    validation["signal_close_date"]
                ).max(),
            }
        )
        fold_rows.append(fold_metrics)

    if not oof_parts:
        raise ValueError("no cluster-isolated OOF predictions were produced")
    oof = pd.concat(oof_parts, ignore_index=True).sort_values(
        ["signal_close_date", "underlying"]
    )
    aggregate = _prediction_metrics(oof)
    asset_spreads = _asset_probability_spreads(oof)
    cluster_contributions = _cluster_information_contributions(oof)
    aggregate.update(
        {
            "donor_events": int(len(development)),
            "macro_clusters": int(development["macro_cluster_id"].nunique()),
            "donor_assets": int(development["underlying"].nunique()),
            "positive_asset_spread_count": int(
                asset_spreads["high_minus_low_spread"].gt(0.0).sum()
            ),
            "largest_positive_cluster_contribution_share": float(
                cluster_contributions["positive_contribution_share"].max()
            )
            if len(cluster_contributions)
            else 1.0,
            "maximum_single_asset_event_share": float(
                development["underlying"].value_counts(normalize=True).max()
            ),
            "training_assets": sorted(
                development["underlying"].unique().tolist()
            ),
            "development_end": development_end,
        }
    )

    final_model = _pipeline(contract)
    final_model.fit(
        development[list(features)],
        development["positive_event_excess"].astype(int),
    )
    fitted = final_model.named_steps["model"]
    coefficients = pd.DataFrame(
        {
            "feature": list(features),
            "coefficient": np.asarray(fitted.coef_[0], dtype=float),
        }
    ).sort_values("coefficient", ascending=False)
    return ClusterTransferModel(
        donor_events=development,
        oof_predictions=oof,
        fold_metrics=pd.DataFrame(fold_rows)
        .sort_values("macro_cluster_id")
        .reset_index(drop=True),
        asset_spreads=asset_spreads,
        cluster_contributions=cluster_contributions,
        aggregate_metrics=aggregate,
        feature_names=features,
        coefficients=coefficients,
        fitted_pipeline=final_model,
    )


def build_target_events(
    bars: Mapping[str, pd.DataFrame],
    donor_frames: Mapping[str, pd.DataFrame],
    model: ClusterTransferModel,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build QQQ events and score them with the frozen donor-only model."""

    donor_breadth = pd.concat(
        [
            frame[
                ["donor_breadth_above_ma20", "donor_breadth_above_ma50"]
            ]
            for frame in donor_frames.values()
        ],
        axis=0,
    )
    donor_breadth = donor_breadth.groupby(level=0).mean().sort_index()
    target = contract["data"]["target_pair"]
    frame = build_asset_feature_frame(
        bars,
        underlying=str(target["underlying"]),
        leveraged=str(target["leveraged"]),
        cash=str(contract["data"]["target_cash_asset"]),
        breadth=donor_breadth,
        contract=contract,
    )
    events = build_nonoverlapping_events(
        frame,
        underlying=str(target["underlying"]),
        leveraged=str(target["leveraged"]),
        cash=str(contract["data"]["target_cash_asset"]),
        contract=contract,
    )
    if events.empty:
        raise ValueError("no target QQQ events were generated")
    events["probability"] = model.fitted_pipeline.predict_proba(
        events[list(model.feature_names)]
    )[:, 1]
    low = float(contract["strategy"]["probability_low_below"])
    high = float(contract["strategy"]["probability_high_at_or_above"])
    events["probability_bucket"] = "medium"
    events.loc[events["probability"].lt(low), "probability_bucket"] = "low"
    events.loc[events["probability"].ge(high), "probability_bucket"] = "high"
    return events, frame


def _target_weight_from_bucket(bucket: str) -> float:
    return {"low": 0.0, "medium": 0.5, "high": 1.0}[bucket]


def _target_weight_schedules(
    frame: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, pd.Series]:
    structural_signal = frame["structural_bull"].astype(bool)
    structural = (
        structural_signal.shift(1).fillna(False).astype(float)
        * float(contract["strategy"]["structural_tqqq_weight"])
    )
    event_weight = pd.Series(np.nan, index=frame.index, dtype=float)
    for event in events.itertuples(index=False):
        active = (frame.index >= pd.Timestamp(event.execution_date)) & (
            frame.index <= pd.Timestamp(event.event_end_date)
        )
        event_weight.loc[active] = _target_weight_from_bucket(
            str(event.probability_bucket)
        )

    joint = structural.copy()
    joint.loc[event_weight.notna()] = event_weight.loc[event_weight.notna()]
    return {
        "buy_hold_sgov": pd.Series(0.0, index=frame.index),
        "static_50_sgov_50_tqqq": pd.Series(0.5, index=frame.index),
        "structural_only": structural,
        "event_only": event_weight.fillna(0.0),
        "joint_structural_event": joint,
    }


def _backtest_target_weights(
    frame: pd.DataFrame,
    tqqq_weight: pd.Series,
    contract: Mapping[str, Any],
    strategy: str,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> StrategyResult:
    daily = frame[
        ["cash_next_open_return", "leveraged_next_open_return"]
    ].copy()
    daily["weight_TQQQ"] = tqqq_weight.reindex(daily.index)
    daily["weight_SGOV"] = 1.0 - daily["weight_TQQQ"]
    if start is not None:
        daily = daily.loc[daily.index >= start].copy()
    if end is not None:
        daily = daily.loc[daily.index <= end].copy()
    daily = daily.dropna(
        subset=[
            "cash_next_open_return",
            "leveraged_next_open_return",
            "weight_TQQQ",
        ]
    )
    weights = daily[["weight_SGOV", "weight_TQQQ"]]
    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("target SGOV/TQQQ weights must sum to one")
    if (weights < -1e-12).any().any() or (
        weights > 1.0 + 1e-12
    ).any().any():
        raise AssertionError("target weights must stay in [0, 1]")
    daily["gross_return"] = (
        daily["weight_SGOV"] * daily["cash_next_open_return"]
        + daily["weight_TQQQ"] * daily["leveraged_next_open_return"]
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(
        contract["boundaries"]["transaction_cost_bps_per_turnover_unit"]
    )
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    change = weights.ne(weights.shift()).any(axis=1)
    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(
            contract["boundaries"]["annual_risk_free_rate"]
        ),
    )
    metrics.update(
        {
            "strategy": strategy,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "switch_count": int(max(int(change.sum()) - 1, 0)),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
            "pct_time_sgov": float(daily["weight_TQQQ"].eq(0.0).mean()),
            "pct_time_full_tqqq": float(
                daily["weight_TQQQ"].eq(1.0).mean()
            ),
        }
    )
    trades = daily.loc[
        change,
        [
            "weight_SGOV",
            "weight_TQQQ",
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(strategy, daily, trades, metrics)


def _rebuild_v4_2_scope(
    result: StrategyResult,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    contract: Mapping[str, Any],
    strategy: str,
) -> StrategyResult:
    daily = result.daily.loc[
        (result.daily.index >= start) & (result.daily.index <= end)
    ].copy()
    weights = daily[[f"weight_{asset}" for asset in V4_2_ASSETS]].copy()
    daily["gross_return"] = sum(
        weights[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in V4_2_ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(
        contract["boundaries"]["transaction_cost_bps_per_turnover_unit"]
    )
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.dropna(subset=["net_return"])
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(
            contract["boundaries"]["annual_risk_free_rate"]
        ),
    )
    metrics.update(
        {
            "strategy": strategy,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
        }
    )
    trades = daily.loc[
        weights.ne(weights.shift()).any(axis=1),
        [
            *[f"weight_{asset}" for asset in V4_2_ASSETS],
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(strategy, daily, trades, metrics)


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


def target_event_attribution(
    events: pd.DataFrame,
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
    for event in events.itertuples(index=False):
        start = pd.Timestamp(event.execution_date)
        end = pd.Timestamp(event.event_end_date)
        window = aligned.loc[(aligned.index >= start) & (aligned.index <= end)]
        if window.empty:
            continue
        candidate_log = float(np.log1p(window["candidate"]).sum())
        baseline_log = float(np.log1p(window["baseline"]).sum())
        rows.append(
            {
                "asset_event_id": event.asset_event_id,
                "execution_date": start,
                "event_end_date": end,
                "probability": float(event.probability),
                "probability_bucket": str(event.probability_bucket),
                "candidate_return": float(np.exp(candidate_log) - 1.0),
                "v4_2_return": float(np.exp(baseline_log) - 1.0),
                "relative_return": float(
                    np.exp(candidate_log - baseline_log) - 1.0
                ),
            }
        )
    return pd.DataFrame(rows)


def _donor_gate(
    model: ClusterTransferModel,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["donor_gate"]
    metrics = model.aggregate_metrics
    checks = {
        "minimum_asset_events": int(metrics["donor_events"])
        >= int(thresholds["minimum_asset_events"]),
        "minimum_macro_clusters": int(metrics["macro_clusters"])
        >= int(thresholds["minimum_macro_clusters"]),
        "aggregate_oof_auc": np.isfinite(float(metrics["roc_auc"]))
        and float(metrics["roc_auc"])
        >= float(thresholds["aggregate_oof_auc_min"]),
        "aggregate_oof_spearman_ic": np.isfinite(float(metrics["spearman_ic"]))
        and float(metrics["spearman_ic"])
        >= float(thresholds["aggregate_oof_spearman_ic_min"]),
        "top_bottom_quartile_spread": float(
            metrics["top_bottom_quartile_spread"]
        )
        > 0.0,
        "positive_asset_spread_count": int(
            metrics["positive_asset_spread_count"]
        )
        >= int(thresholds["positive_asset_spread_count_min"]),
        "largest_positive_cluster_contribution": float(
            metrics["largest_positive_cluster_contribution_share"]
        )
        <= float(thresholds["largest_positive_cluster_contribution_max"]),
        "maximum_single_asset_event_share": float(
            metrics["maximum_single_asset_event_share"]
        )
        <= float(thresholds["maximum_single_asset_event_share"]),
    }
    return {
        "checks": checks,
        "metrics": metrics,
        "passed": bool(all(checks.values())),
    }


def _strategy_gate(
    actual: Mapping[str, StrategyResult],
    proxy: Mapping[str, StrategyResult],
    actual_events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["strategy_gate"]
    baseline = actual["current_v4_2"]
    joint = actual["joint_structural_event"]
    proxy_baseline = proxy["qqq_proxy_v4_2"]
    proxy_joint = proxy["joint_structural_event"]
    cagr_delta_pp = (
        float(joint.metrics["cagr"]) - float(baseline.metrics["cagr"])
    ) * 100.0
    drawdown_worsening_pp = max(
        0.0,
        (
            float(baseline.metrics["max_drawdown"])
            - float(joint.metrics["max_drawdown"])
        )
        * 100.0,
    )
    calmar_delta = float(joint.metrics["calmar"]) - float(
        baseline.metrics["calmar"]
    )
    calendar = _calendar_relative_returns(joint, baseline)
    positive_years = int(sum(value > 0.0 for value in calendar.values()))
    positive_events = (
        actual_events["relative_return"].clip(lower=0.0)
        if not actual_events.empty
        else pd.Series(dtype=float)
    )
    event_share = (
        float(positive_events.max() / positive_events.sum())
        if len(positive_events) and float(positive_events.sum()) > 0.0
        else 1.0
    )
    turnover_increase = (
        float(joint.metrics["turnover_units"])
        / float(baseline.metrics["turnover_units"])
        - 1.0
    )

    ablation_wins: dict[str, dict[str, bool]] = {}
    for comparator_key in ("structural_only", "event_only"):
        comparator = actual[comparator_key]
        ablation_wins[comparator_key] = {
            "cagr": float(joint.metrics["cagr"])
            > float(comparator.metrics["cagr"]),
            "max_drawdown": float(joint.metrics["max_drawdown"])
            > float(comparator.metrics["max_drawdown"]),
            "sortino": float(joint.metrics["sortino"])
            > float(comparator.metrics["sortino"]),
            "calmar": float(joint.metrics["calmar"])
            > float(comparator.metrics["calmar"]),
        }
    ablation_counts = {
        key: int(sum(values.values())) for key, values in ablation_wins.items()
    }
    actual_cagr_sign = np.sign(
        float(joint.metrics["cagr"]) - float(baseline.metrics["cagr"])
    )
    proxy_cagr_sign = np.sign(
        float(proxy_joint.metrics["cagr"])
        - float(proxy_baseline.metrics["cagr"])
    )
    actual_calmar_sign = np.sign(
        float(joint.metrics["calmar"]) - float(baseline.metrics["calmar"])
    )
    proxy_calmar_sign = np.sign(
        float(proxy_joint.metrics["calmar"])
        - float(proxy_baseline.metrics["calmar"])
    )
    checks = {
        "actual_cagr_improvement": cagr_delta_pp
        >= float(thresholds["actual_cagr_improvement_vs_v4_2_pp_min"]),
        "actual_max_drawdown_not_materially_worse": drawdown_worsening_pp
        <= float(
            thresholds["actual_max_drawdown_worsening_vs_v4_2_pp_max"]
        ),
        "actual_calmar_improvement": calmar_delta
        >= float(thresholds["actual_calmar_improvement_vs_v4_2_min"]),
        "actual_sortino_not_below": float(joint.metrics["sortino"])
        >= float(baseline.metrics["sortino"]),
        "positive_relative_calendar_years": positive_years
        >= int(thresholds["positive_relative_calendar_years_min"]),
        "target_event_concentration": event_share
        <= float(thresholds["largest_positive_target_event_share_max"]),
        "turnover": turnover_increase
        <= float(thresholds["turnover_increase_vs_v4_2_max"]),
        "beats_structural_only": ablation_counts["structural_only"]
        >= int(thresholds["ablation_metrics_to_beat_min"]),
        "beats_event_only": ablation_counts["event_only"]
        >= int(thresholds["ablation_metrics_to_beat_min"]),
        "actual_proxy_cagr_direction": actual_cagr_sign == proxy_cagr_sign,
        "actual_proxy_calmar_direction": actual_calmar_sign
        == proxy_calmar_sign,
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_pp": cagr_delta_pp,
            "max_drawdown_worsening_pp": drawdown_worsening_pp,
            "calmar_delta": calmar_delta,
            "calendar_relative_returns": calendar,
            "positive_relative_calendar_years": positive_years,
            "largest_positive_target_event_share": event_share,
            "turnover_increase": turnover_increase,
            "ablation_wins": ablation_wins,
            "ablation_win_counts": ablation_counts,
        },
        "passed": bool(all(checks.values())),
    }


def run_cross_asset_sgov_tqqq_transfer(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[
    ClusterTransferModel,
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, dict[str, StrategyResult]],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run donor event learning and actual/proxy target comparisons."""

    required = {str(value) for value in contract["data"]["required_symbols"]}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    donor_events, donor_frames = build_donor_event_panel(bars, contract)
    model = fit_cluster_transfer_model(donor_events, contract)
    target_events, target_frame = build_target_events(
        bars, donor_frames, model, contract
    )
    schedules = _target_weight_schedules(target_frame, target_events, contract)

    _, actual_base_results, _, _ = run_bridge_allocation_comparison(
        bars, bridge_contract
    )
    proxy_bars = alias_qqqi_to_qqq(bars)
    _, proxy_base_results, _, _ = run_bridge_allocation_comparison(
        proxy_bars, bridge_contract
    )
    actual_base_full = actual_base_results[BASELINE_KEY]
    proxy_base_full = proxy_base_results[BASELINE_KEY]

    target_available = target_frame.dropna(
        subset=["cash_next_open_return", "leveraged_next_open_return"]
    )
    common_end = min(
        target_available.index.max(),
        actual_base_full.daily.index.max(),
        proxy_base_full.daily.index.max(),
    )
    actual_start = max(
        target_available.index.min(), actual_base_full.daily.index.min()
    )
    proxy_start = max(
        target_available.index.min(), proxy_base_full.daily.index.min()
    )
    if actual_start >= common_end or proxy_start >= common_end:
        raise ValueError("target comparison windows are invalid")

    results_by_scope: dict[str, dict[str, StrategyResult]] = {
        "actual": {},
        "qqq_proxy": {},
    }
    actual_baseline = _rebuild_v4_2_scope(
        actual_base_full,
        start=actual_start,
        end=common_end,
        contract=contract,
        strategy="current_v4_2",
    )
    proxy_baseline = _rebuild_v4_2_scope(
        proxy_base_full,
        start=proxy_start,
        end=common_end,
        contract=contract,
        strategy="qqq_proxy_v4_2",
    )
    results_by_scope["actual"]["current_v4_2"] = actual_baseline
    results_by_scope["qqq_proxy"]["qqq_proxy_v4_2"] = proxy_baseline

    for strategy, weights in schedules.items():
        results_by_scope["actual"][strategy] = _backtest_target_weights(
            target_frame,
            weights,
            contract,
            strategy,
            start=actual_start,
            end=common_end,
        )
        results_by_scope["qqq_proxy"][strategy] = _backtest_target_weights(
            target_frame,
            weights,
            contract,
            strategy,
            start=proxy_start,
            end=common_end,
        )

    for scope, results in results_by_scope.items():
        indices = [result.daily.index for result in results.values()]
        common = indices[0]
        for index in indices[1:]:
            if not common.equals(index):
                raise AssertionError(f"{scope} comparator indices diverged")

    headlines = {
        scope: pd.DataFrame(
            [dict(result.metrics) for result in results.values()]
        ).set_index("strategy")
        for scope, results in results_by_scope.items()
    }
    event_attribution = {
        "actual": target_event_attribution(
            target_events,
            results_by_scope["actual"]["joint_structural_event"],
            actual_baseline,
        ),
        "qqq_proxy": target_event_attribution(
            target_events,
            results_by_scope["qqq_proxy"]["joint_structural_event"],
            proxy_baseline,
        ),
    }
    donor_gate = _donor_gate(model, contract)
    strategy_gate = _strategy_gate(
        results_by_scope["actual"],
        results_by_scope["qqq_proxy"],
        event_attribution["actual"],
        contract,
    )
    shadow = bool(donor_gate["passed"] and strategy_gate["passed"])
    if not donor_gate["passed"]:
        decision = "cross_asset_donor_signal_not_stable"
    elif not strategy_gate["passed"]:
        decision = "sgov_tqqq_transfer_does_not_stably_beat_v4_2"
    else:
        decision = "cross_asset_sgov_tqqq_shadow_supported"

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "target_excluded_from_training": True,
        "training_assets": model.aggregate_metrics["training_assets"],
        "donor_gate": donor_gate,
        "strategy_gate": strategy_gate,
        "actual_sample_start": actual_start,
        "proxy_sample_start": proxy_start,
        "sample_end": common_end,
        "target_event_count": int(len(target_events)),
        "target_bucket_counts": target_events[
            "probability_bucket"
        ].value_counts().to_dict(),
        "tail_risk": {
            scope: {
                key: tail_risk_metrics(result)
                for key, result in results.items()
            }
            for scope, results in results_by_scope.items()
        },
        "decision": decision,
        "shadow_candidate_authorized": shadow,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return (
        model,
        target_events,
        headlines,
        results_by_scope,
        event_attribution,
        diagnostics,
    )
