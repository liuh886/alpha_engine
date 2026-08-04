"""BYD V1.1 momentum-factor research and walk-forward XGBoost model.

The module is deliberately separate from AlphaEngine's cross-sectional XGBoost
ranker. A single stock has one observation per date, so BYD V1.1 predicts the
next 10-session open-to-open return with an expanding time-series regressor.
All predictions are out of sample, signals are decided at the close, and
positions become executable at the following open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.byd_core_tactical_v1 import (
    build_candidate_positions as build_v1_positions,
)
from src.research.byd_core_tactical_v1 import build_features as build_v1_features
from src.research.byd_single_asset_v1 import (
    BacktestResult,
    normalise_ohlcv,
    run_backtest,
    run_buy_and_hold,
)

TARGET_COLUMN = "forward_open_return_10"
BASE_FEATURE_NAMES = (
    "mom_2",
    "mom_5",
    "mom_10",
    "mom_20",
    "mom_40",
    "mom_60",
    "mom_120",
    "mom_252",
    "mom_20_skip_5",
    "mom_60_skip_5",
    "mom_120_skip_20",
    "mom_252_skip_20",
    "mom_5_minus_20",
    "mom_10_minus_40",
    "mom_20_minus_60",
    "mom_60_minus_120",
    "mom_10_over_vol20",
    "mom_20_over_vol20",
    "mom_60_over_vol60",
    "mom_120_over_vol60",
    "close_to_sma20",
    "close_to_sma60",
    "close_to_sma120",
    "close_to_sma200",
    "positive_day_ratio_10",
    "positive_day_ratio_20",
    "positive_day_ratio_60",
    "trend_slope_20",
    "trend_slope_60",
    "trend_slope_120",
    "drawdown_60",
    "drawdown_120",
    "drawdown_252",
    "drawdown_252_change_5",
    "drawdown_252_change_10",
    "drawdown_252_change_20",
    "distance_from_low_20",
    "distance_from_low_60",
    "volume_ratio_5_20",
    "volume_ratio_20_60",
    "up_down_volume_ratio_20",
    "mom20_volume_confirm",
    "mom60_volume_confirm",
)
RELATIVE_FEATURE_NAMES = (
    "relative_mom_10_csi300",
    "relative_mom_20_csi300",
    "relative_mom_60_csi300",
    "relative_mom_120_csi300",
    "residual_mom_20_csi300",
    "residual_mom_60_csi300",
    "csi300_close_to_sma20",
    "csi300_close_to_sma60",
    "csi300_close_to_sma120",
)
POSITION_MAPPINGS = (
    "xgb_binary_0_100",
    "xgb_core75_100",
    "xgb_four_state",
)


@dataclass(frozen=True)
class XGBTimeSeriesConfig:
    """Frozen BYD V1.1 XGBoost and walk-forward parameters."""

    objective: str = "reg:squarederror"
    tree_method: str = "hist"
    max_depth: int = 3
    min_child_weight: float = 20.0
    learning_rate: float = 0.03
    subsample: float = 0.80
    colsample_bytree: float = 0.80
    reg_alpha: float = 1.0
    reg_lambda: float = 10.0
    num_boost_round: int = 300
    seed: int = 42
    decision_step_sessions: int = 10
    refit_step_sessions: int = 20
    label_horizon_sessions: int = 10
    minimum_training_samples: int = 756

    def model_parameters(self) -> dict[str, object]:
        return {
            "objective": self.objective,
            "tree_method": self.tree_method,
            "max_depth": self.max_depth,
            "min_child_weight": self.min_child_weight,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "seed": self.seed,
            "verbosity": 0,
        }


@dataclass(frozen=True)
class WalkForwardResult:
    predictions: pd.DataFrame
    fit_manifest: pd.DataFrame
    feature_importance: pd.DataFrame
    latest_snapshot: dict[str, Any]


def _rolling_log_slope(close: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    centered = x - x.mean()
    denominator = float(np.square(centered).sum())

    def calculate(values: np.ndarray) -> float:
        log_values = np.log(values)
        return float(np.dot(centered, log_values - log_values.mean()) / denominator * window)

    return close.rolling(window, min_periods=window).apply(calculate, raw=True)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.replace(0.0, np.nan))


def build_momentum_dataset(
    ohlcv: pd.DataFrame,
    benchmark_ohlcv: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Build the pre-registered close-observable BYD momentum feature set."""

    daily = normalise_ohlcv(ohlcv).copy()
    close = daily["close"]
    volume = daily["volume"]
    daily_return = close.pct_change()

    for horizon in (2, 5, 10, 20, 40, 60, 120, 252):
        daily[f"mom_{horizon}"] = close.pct_change(horizon)

    daily["mom_20_skip_5"] = close.shift(5).div(close.shift(20)).sub(1.0)
    daily["mom_60_skip_5"] = close.shift(5).div(close.shift(60)).sub(1.0)
    daily["mom_120_skip_20"] = close.shift(20).div(close.shift(120)).sub(1.0)
    daily["mom_252_skip_20"] = close.shift(20).div(close.shift(252)).sub(1.0)

    daily["mom_5_minus_20"] = daily["mom_5"] - daily["mom_20"]
    daily["mom_10_minus_40"] = daily["mom_10"] - daily["mom_40"]
    daily["mom_20_minus_60"] = daily["mom_20"] - daily["mom_60"]
    daily["mom_60_minus_120"] = daily["mom_60"] - daily["mom_120"]

    vol20 = daily_return.rolling(20, min_periods=20).std(ddof=0)
    vol60 = daily_return.rolling(60, min_periods=60).std(ddof=0)
    daily["mom_10_over_vol20"] = _safe_ratio(daily["mom_10"], vol20)
    daily["mom_20_over_vol20"] = _safe_ratio(daily["mom_20"], vol20)
    daily["mom_60_over_vol60"] = _safe_ratio(daily["mom_60"], vol60)
    daily["mom_120_over_vol60"] = _safe_ratio(daily["mom_120"], vol60)

    for horizon in (20, 60, 120, 200):
        sma = close.rolling(horizon, min_periods=horizon).mean()
        daily[f"close_to_sma{horizon}"] = close.div(sma).sub(1.0)

    positive = daily_return.gt(0.0).astype(float)
    for horizon in (10, 20, 60):
        daily[f"positive_day_ratio_{horizon}"] = positive.rolling(
            horizon, min_periods=horizon
        ).mean()

    for horizon in (20, 60, 120):
        daily[f"trend_slope_{horizon}"] = _rolling_log_slope(close, horizon)

    for horizon in (60, 120, 252):
        rolling_high = close.rolling(horizon, min_periods=horizon).max()
        daily[f"drawdown_{horizon}"] = close.div(rolling_high).sub(1.0)
    for horizon in (5, 10, 20):
        daily[f"drawdown_252_change_{horizon}"] = daily["drawdown_252"].diff(
            horizon
        )
    for horizon in (20, 60):
        rolling_low = close.rolling(horizon, min_periods=horizon).min()
        daily[f"distance_from_low_{horizon}"] = close.div(rolling_low).sub(1.0)

    volume_5 = volume.rolling(5, min_periods=5).mean()
    volume_20 = volume.rolling(20, min_periods=20).mean()
    volume_60 = volume.rolling(60, min_periods=60).mean()
    daily["volume_ratio_5_20"] = _safe_ratio(volume_5, volume_20).sub(1.0)
    daily["volume_ratio_20_60"] = _safe_ratio(volume_20, volume_60).sub(1.0)
    up_volume = volume.where(daily_return.gt(0.0), 0.0).rolling(
        20, min_periods=20
    ).sum()
    down_volume = volume.where(daily_return.lt(0.0), 0.0).rolling(
        20, min_periods=20
    ).sum()
    daily["up_down_volume_ratio_20"] = _safe_ratio(up_volume, down_volume)
    daily["mom20_volume_confirm"] = daily["mom_20"] * (
        1.0 + daily["volume_ratio_5_20"]
    )
    daily["mom60_volume_confirm"] = daily["mom_60"] * (
        1.0 + daily["volume_ratio_20_60"]
    )

    feature_names = list(BASE_FEATURE_NAMES)
    if benchmark_ohlcv is not None:
        benchmark = normalise_ohlcv(benchmark_ohlcv)
        benchmark_close = benchmark["close"]
        benchmark_return = benchmark_close.pct_change().reindex(daily.index)
        aligned_benchmark_close = benchmark_close.reindex(daily.index)
        for horizon in (10, 20, 60, 120):
            benchmark_momentum = benchmark_close.pct_change(horizon).reindex(daily.index)
            daily[f"relative_mom_{horizon}_csi300"] = (
                daily[f"mom_{horizon}"] - benchmark_momentum
            )
        rolling_covariance = daily_return.rolling(60, min_periods=60).cov(
            benchmark_return
        )
        rolling_variance = benchmark_return.rolling(60, min_periods=60).var(ddof=0)
        beta60 = _safe_ratio(rolling_covariance, rolling_variance)
        residual_return = daily_return - beta60 * benchmark_return
        daily["residual_mom_20_csi300"] = (
            1.0 + residual_return
        ).rolling(20, min_periods=20).apply(np.prod, raw=True).sub(1.0)
        daily["residual_mom_60_csi300"] = (
            1.0 + residual_return
        ).rolling(60, min_periods=60).apply(np.prod, raw=True).sub(1.0)
        for horizon in (20, 60, 120):
            benchmark_sma = aligned_benchmark_close.rolling(
                horizon, min_periods=horizon
            ).mean()
            daily[f"csi300_close_to_sma{horizon}"] = (
                aligned_benchmark_close.div(benchmark_sma).sub(1.0)
            )
        feature_names.extend(RELATIVE_FEATURE_NAMES)

    daily[TARGET_COLUMN] = daily["open"].shift(-11).div(
        daily["open"].shift(-1)
    ).sub(1.0)
    feature_tuple = tuple(feature_names)
    if not set(feature_tuple).issubset(daily.columns):
        missing = sorted(set(feature_tuple) - set(daily.columns))
        raise AssertionError(f"momentum feature construction drifted: {missing}")
    return daily, feature_tuple


def _decision_dates(
    index: pd.DatetimeIndex,
    start: str,
    end: str,
    step: int,
) -> list[pd.Timestamp]:
    if step <= 0:
        raise ValueError("decision step must be positive")
    start_position = int(index.searchsorted(pd.Timestamp(start), side="left"))
    end_position = int(index.searchsorted(pd.Timestamp(end), side="right"))
    return [index[position] for position in range(start_position, end_position, step)]


def _correlation(left: pd.Series, right: pd.Series, method: str) -> float:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 3:
        return float("nan")
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method=method))


def _quintile_diagnostics(
    development_values: pd.Series,
    validation_values: pd.Series,
    validation_target: pd.Series,
) -> tuple[float, float, list[float]]:
    clean_development = development_values.dropna()
    if clean_development.nunique() < 5:
        return float("nan"), float("nan"), []
    edges = np.unique(
        np.quantile(clean_development.to_numpy(dtype=float), np.linspace(0.0, 1.0, 6))
    )
    if len(edges) < 6:
        return float("nan"), float("nan"), []
    aligned = pd.concat([validation_values, validation_target], axis=1).dropna()
    if aligned.empty:
        return float("nan"), float("nan"), []
    bins = np.searchsorted(edges[1:-1], aligned.iloc[:, 0].to_numpy(), side="right")
    grouped = pd.Series(aligned.iloc[:, 1].to_numpy(), index=bins).groupby(level=0).mean()
    means = [float(grouped.get(bucket, np.nan)) for bucket in range(5)]
    valid = pd.Series(means).dropna()
    monotonicity = (
        float(pd.Series(valid.index, index=valid.index).corr(valid, method="spearman"))
        if len(valid) >= 3
        else float("nan")
    )
    top_bottom = (
        float(means[4] - means[0])
        if np.isfinite(means[4]) and np.isfinite(means[0])
        else float("nan")
    )
    return monotonicity, top_bottom, means


def factor_diagnostics(
    dataset: pd.DataFrame,
    feature_names: tuple[str, ...],
    windows: Mapping[str, Any],
    decision_step_sessions: int = 10,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Evaluate time-series momentum factors without cross-sectional Rank IC."""

    development_dates = _decision_dates(
        dataset.index,
        str(windows["development_start"]),
        str(windows["development_end"]),
        decision_step_sessions,
    )
    validation_dates = _decision_dates(
        dataset.index,
        str(windows["validation_start"]),
        str(windows["validation_end"]),
        decision_step_sessions,
    )
    holdout_dates = _decision_dates(
        dataset.index,
        str(windows["retrospective_holdout_start"]),
        str(windows["retrospective_holdout_end"]),
        decision_step_sessions,
    )
    rows: list[dict[str, Any]] = []
    for feature in feature_names:
        development = dataset.loc[development_dates, [feature, TARGET_COLUMN]].dropna()
        validation = dataset.loc[validation_dates, [feature, TARGET_COLUMN]].dropna()
        holdout = dataset.loc[holdout_dates, [feature, TARGET_COLUMN]].dropna()
        development_spearman = _correlation(
            development[feature], development[TARGET_COLUMN], "spearman"
        )
        orientation = 1.0 if not np.isfinite(development_spearman) or development_spearman >= 0.0 else -1.0
        oriented_development = development[feature] * orientation
        oriented_validation = validation[feature] * orientation
        oriented_holdout = holdout[feature] * orientation
        threshold = float(oriented_development.median()) if not oriented_development.empty else float("nan")
        validation_prediction = oriented_validation.gt(threshold)
        validation_actual = validation[TARGET_COLUMN].gt(0.0)
        validation_hit_rate = (
            float(validation_prediction.eq(validation_actual).mean())
            if len(validation) > 0 and np.isfinite(threshold)
            else float("nan")
        )
        monotonicity, top_bottom, quintile_means = _quintile_diagnostics(
            oriented_development,
            oriented_validation,
            validation[TARGET_COLUMN],
        )
        rows.append(
            {
                "factor": feature,
                "orientation": orientation,
                "development_threshold": threshold,
                "development_spearman": development_spearman,
                "development_pearson": _correlation(
                    development[feature], development[TARGET_COLUMN], "pearson"
                ),
                "validation_spearman": _correlation(
                    oriented_validation, validation[TARGET_COLUMN], "spearman"
                ),
                "validation_pearson": _correlation(
                    oriented_validation, validation[TARGET_COLUMN], "pearson"
                ),
                "validation_direction_hit_rate": validation_hit_rate,
                "validation_quintile_monotonicity": monotonicity,
                "validation_top_bottom_spread": top_bottom,
                "validation_quintile_means": quintile_means,
                "holdout_spearman": _correlation(
                    oriented_holdout, holdout[TARGET_COLUMN], "spearman"
                ),
                "holdout_pearson": _correlation(
                    oriented_holdout, holdout[TARGET_COLUMN], "pearson"
                ),
                "development_samples": int(len(development)),
                "validation_samples": int(len(validation)),
                "holdout_samples": int(len(holdout)),
            }
        )
    diagnostics = pd.DataFrame(rows)
    eligible = diagnostics.dropna(subset=["development_spearman"]).copy()
    if eligible.empty:
        raise ValueError("no momentum factor has sufficient development evidence")
    eligible["development_abs_spearman"] = eligible["development_spearman"].abs()
    selected_row = eligible.sort_values(
        ["development_abs_spearman", "factor"], ascending=[False, True]
    ).iloc[0]
    selection = {
        "factor": str(selected_row["factor"]),
        "orientation": float(selected_row["orientation"]),
        "threshold": float(selected_row["development_threshold"]),
        "selection_rule": "maximum_absolute_development_spearman_only",
    }
    development_frame = dataset.loc[
        pd.Timestamp(str(windows["development_start"])) : pd.Timestamp(
            str(windows["development_end"])
        ),
        list(feature_names),
    ]
    correlation = development_frame.corr(method="spearman", min_periods=60)
    return diagnostics, selection, correlation


def build_single_factor_position(
    dataset: pd.DataFrame,
    factor: str,
    orientation: float,
    threshold: float,
    start: str,
    end: str,
    decision_step_sessions: int = 10,
) -> pd.Series:
    dates = _decision_dates(dataset.index, start, end, decision_step_sessions)
    decisions = pd.Series(np.nan, index=dataset.index, dtype=float)
    values = dataset.loc[dates, factor] * float(orientation)
    decisions.loc[dates] = values.gt(float(threshold)).astype(float)
    return decisions.ffill().fillna(0.0).rename("decision_position")


def walk_forward_xgb(
    dataset: pd.DataFrame,
    feature_names: tuple[str, ...],
    *,
    training_start: str,
    prediction_start: str,
    prediction_end: str,
    config: XGBTimeSeriesConfig,
) -> WalkForwardResult:
    """Produce expanding-window, embargoed XGBoost predictions."""

    import xgboost as xgb

    dates = _decision_dates(
        dataset.index,
        prediction_start,
        prediction_end,
        config.decision_step_sessions,
    )
    records: list[dict[str, Any]] = []
    fit_records: list[dict[str, Any]] = []
    importance_records: list[dict[str, Any]] = []
    model: Any | None = None
    model_id = 0
    last_fit_position: int | None = None
    index_positions = {date: position for position, date in enumerate(dataset.index)}

    for prediction_date in dates:
        prediction_position = index_positions[prediction_date]
        feature_row = dataset.loc[[prediction_date], list(feature_names)]
        if feature_row.isna().any(axis=None):
            continue
        train_end_position = prediction_position - config.label_horizon_sessions - 1
        if train_end_position < 0:
            continue
        train_end_date = dataset.index[train_end_position]
        training = dataset.loc[
            pd.Timestamp(training_start) : train_end_date,
            [*feature_names, TARGET_COLUMN],
        ].dropna()
        if len(training) < config.minimum_training_samples:
            continue
        refit = (
            model is None
            or last_fit_position is None
            or prediction_position - last_fit_position >= config.refit_step_sessions
        )
        if refit:
            model_id += 1
            dtrain = xgb.DMatrix(
                training.loc[:, list(feature_names)],
                label=training[TARGET_COLUMN],
                feature_names=list(feature_names),
            )
            model = xgb.train(
                config.model_parameters(),
                dtrain,
                num_boost_round=config.num_boost_round,
            )
            last_fit_position = prediction_position
            fit_records.append(
                {
                    "model_id": model_id,
                    "fit_for_prediction_date": prediction_date,
                    "training_start": training.index[0],
                    "training_end": training.index[-1],
                    "training_samples": int(len(training)),
                    "embargo_sessions": config.label_horizon_sessions,
                    "num_boost_round": config.num_boost_round,
                }
            )
            raw_importance = model.get_score(importance_type="gain")
            total_gain = float(sum(raw_importance.values()))
            for feature in feature_names:
                gain = float(raw_importance.get(feature, 0.0))
                importance_records.append(
                    {
                        "model_id": model_id,
                        "fit_for_prediction_date": prediction_date,
                        "feature": feature,
                        "gain": gain,
                        "gain_share": gain / total_gain if total_gain > 0.0 else 0.0,
                    }
                )
        if model is None:
            raise AssertionError("walk-forward model was not fitted")
        prediction = float(
            model.predict(
                xgb.DMatrix(feature_row, feature_names=list(feature_names))
            )[0]
        )
        actual = dataset.loc[prediction_date, TARGET_COLUMN]
        records.append(
            {
                "date": prediction_date,
                "model_id": model_id,
                "predicted_forward_return_10": prediction,
                "actual_forward_return_10": (
                    float(actual) if pd.notna(actual) else np.nan
                ),
                "training_end": train_end_date,
                "embargo_sessions": config.label_horizon_sessions,
            }
        )

    predictions = pd.DataFrame(records).set_index("date") if records else pd.DataFrame()
    if predictions.empty:
        raise ValueError("walk-forward XGBoost produced no predictions")
    fit_manifest = pd.DataFrame(fit_records)
    importance = pd.DataFrame(importance_records)

    latest_date = pd.Timestamp(prediction_end)
    if latest_date not in dataset.index:
        raise ValueError(f"latest snapshot date is not in the dataset: {latest_date.date()}")
    latest_position = index_positions[latest_date]
    latest_train_end_position = latest_position - config.label_horizon_sessions - 1
    latest_train_end = dataset.index[latest_train_end_position]
    latest_training = dataset.loc[
        pd.Timestamp(training_start) : latest_train_end,
        [*feature_names, TARGET_COLUMN],
    ].dropna()
    if len(latest_training) < config.minimum_training_samples:
        raise ValueError("latest snapshot has insufficient training samples")
    latest_model = xgb.train(
        config.model_parameters(),
        xgb.DMatrix(
            latest_training.loc[:, list(feature_names)],
            label=latest_training[TARGET_COLUMN],
            feature_names=list(feature_names),
        ),
        num_boost_round=config.num_boost_round,
    )
    latest_features = dataset.loc[[latest_date], list(feature_names)]
    if latest_features.isna().any(axis=None):
        raise ValueError("latest snapshot contains missing features")
    latest_prediction = float(
        latest_model.predict(
            xgb.DMatrix(latest_features, feature_names=list(feature_names))
        )[0]
    )
    latest_snapshot = {
        "date": latest_date,
        "prediction": latest_prediction,
        "training_end": latest_train_end,
        "training_samples": int(len(latest_training)),
        "classification": "latest_close_snapshot_not_backtest_schedule_override",
    }
    return WalkForwardResult(
        predictions=predictions,
        fit_manifest=fit_manifest,
        feature_importance=importance,
        latest_snapshot=latest_snapshot,
    )


def map_prediction_to_position(prediction: float, mapping: str) -> float:
    if mapping == "xgb_binary_0_100":
        return 1.0 if prediction > 0.0 else 0.0
    if mapping == "xgb_core75_100":
        return 1.0 if prediction > 0.0 else 0.75
    if mapping == "xgb_four_state":
        if prediction >= 0.02:
            return 1.0
        if prediction >= 0.0:
            return 0.75
        if prediction > -0.02:
            return 0.50
        return 0.0
    raise ValueError(f"unknown BYD V1.1 position mapping: {mapping}")


def build_xgb_position(
    index: pd.DatetimeIndex,
    predictions: pd.DataFrame,
    mapping: str,
) -> pd.Series:
    decisions = pd.Series(np.nan, index=index, dtype=float)
    mapped = predictions["predicted_forward_return_10"].map(
        lambda value: map_prediction_to_position(float(value), mapping)
    )
    decisions.loc[mapped.index] = mapped
    return decisions.ffill().fillna(0.0).rename("decision_position")


def _metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = pd.to_numeric(daily["net_return"], errors="coerce").dropna()
    if returns.empty:
        raise ValueError("no returns available for metrics")
    years = len(returns) / 252.0
    wealth = (1.0 + returns).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = (
        float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
        if years > 0.0 and wealth.iloc[-1] > 0.0
        else -1.0
    )
    volatility = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252.0))
        if returns.std(ddof=0) > 0.0
        else 0.0
    )
    downside_deviation = float(
        np.sqrt(returns.clip(upper=0.0).pow(2).mean()) * np.sqrt(252.0)
    )
    sortino = (
        float(returns.mean() * 252.0 / downside_deviation)
        if downside_deviation > 0.0
        else 0.0
    )
    drawdown = wealth.div(wealth.cummax()).sub(1.0)
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0
    turnover_units = float(daily["turnover_units"].sum())
    return {
        "sessions": float(len(returns)),
        "years": float(years),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover_units": turnover_units,
        "round_trips_per_year": (
            float(turnover_units / (2.0 * years)) if years > 0.0 else 0.0
        ),
        "exposure": float(daily["position_at_open"].mean()),
    }


def _slice_metrics(result: BacktestResult, start: str, end: str) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()
    if block.empty:
        raise ValueError(f"empty evaluation window {start} to {end}")
    return _metrics(block)


def _positive_quarter_concentration(
    candidate: BacktestResult,
    reference: BacktestResult,
    start: str,
    end: str,
) -> float:
    candidate_daily = candidate.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    reference_daily = reference.daily.reindex(candidate_daily.index)
    quarter = candidate_daily.index.to_period("Q")
    candidate_returns = candidate_daily.groupby(quarter)["net_return"].apply(
        lambda values: float((1.0 + values).prod() - 1.0)
    )
    reference_returns = reference_daily.groupby(quarter)["net_return"].apply(
        lambda values: float((1.0 + values).prod() - 1.0)
    )
    relative = (1.0 + candidate_returns).div(1.0 + reference_returns).sub(1.0)
    positive = relative.clip(lower=0.0)
    total = float(positive.sum())
    return float(positive.max() / total) if total > 0.0 else 1.0


def _prediction_quality(
    predictions: pd.DataFrame,
    start: str,
    end: str,
) -> dict[str, Any]:
    block = predictions.loc[pd.Timestamp(start) : pd.Timestamp(end)].dropna(
        subset=["actual_forward_return_10"]
    )
    if block.empty:
        return {
            "samples": 0,
            "spearman": float("nan"),
            "pearson": float("nan"),
            "direction_hit_rate": float("nan"),
            "annual_hit_rates": {},
            "years_above_50pct": 0,
        }
    predicted = block["predicted_forward_return_10"]
    actual = block["actual_forward_return_10"]
    annual_hits = (
        predicted.gt(0.0)
        .eq(actual.gt(0.0))
        .groupby(block.index.year)
        .mean()
    )
    return {
        "samples": int(len(block)),
        "spearman": _correlation(predicted, actual, "spearman"),
        "pearson": _correlation(predicted, actual, "pearson"),
        "direction_hit_rate": float(predicted.gt(0.0).eq(actual.gt(0.0)).mean()),
        "annual_hit_rates": {str(year): float(value) for year, value in annual_hits.items()},
        "years_above_50pct": int(annual_hits.gt(0.50).sum()),
    }


def _aggregate_feature_importance(
    importance: pd.DataFrame,
    validation_end: str,
) -> tuple[pd.DataFrame, float]:
    if importance.empty:
        return pd.DataFrame(columns=["feature", "mean_gain_share"]), 1.0
    eligible = importance.loc[
        pd.to_datetime(importance["fit_for_prediction_date"])
        <= pd.Timestamp(validation_end)
    ]
    aggregate = (
        eligible.groupby("feature", as_index=False)["gain_share"]
        .mean()
        .rename(columns={"gain_share": "mean_gain_share"})
        .sort_values("mean_gain_share", ascending=False)
    )
    maximum = float(aggregate["mean_gain_share"].max()) if not aggregate.empty else 1.0
    return aggregate, maximum


def evaluate_byd_v1_1(
    ohlcv: pd.DataFrame,
    contract: Mapping[str, Any],
    benchmark_ohlcv: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Evaluate factors, XGBoost mappings, baselines, and holdout contradiction."""

    dataset, feature_names = build_momentum_dataset(ohlcv, benchmark_ohlcv)
    windows = contract["windows"]
    costs = contract["costs"]
    xgb_config = XGBTimeSeriesConfig(**contract["xgboost"])
    factor_table, factor_selection, factor_correlation = factor_diagnostics(
        dataset,
        feature_names,
        windows,
        decision_step_sessions=xgb_config.decision_step_sessions,
    )
    factor_position = build_single_factor_position(
        dataset,
        factor_selection["factor"],
        factor_selection["orientation"],
        factor_selection["threshold"],
        str(windows["development_start"]),
        str(windows["retrospective_holdout_end"]),
        xgb_config.decision_step_sessions,
    )
    walk_forward = walk_forward_xgb(
        dataset,
        feature_names,
        training_start=str(windows["development_start"]),
        prediction_start=str(windows["oos_prediction_start"]),
        prediction_end=str(windows["retrospective_holdout_end"]),
        config=xgb_config,
    )

    primary_cost = float(costs["primary_bps_per_turnover_unit"])
    stress_cost = float(max(costs["stress_bps_per_turnover_unit"]))
    buy_hold = run_buy_and_hold(dataset, primary_cost)
    buy_hold_stress = run_buy_and_hold(dataset, stress_cost)
    v1_features = build_v1_features(ohlcv)
    v1_position = build_v1_positions(v1_features)["core75_regime_mom_120"]
    v1 = run_backtest(v1_features, v1_position, primary_cost, "byd_v1_rule_baseline")
    v1_stress = run_backtest(
        v1_features, v1_position, stress_cost, "byd_v1_rule_baseline_stress"
    )
    constant75_position = pd.Series(0.75, index=dataset.index, dtype=float)
    constant75 = run_backtest(
        dataset, constant75_position, primary_cost, "constant_75pct_byd"
    )
    factor_result = run_backtest(
        dataset, factor_position, primary_cost, "best_development_single_factor"
    )

    validation_start = str(windows["validation_start"])
    validation_end = str(windows["validation_end"])
    holdout_start = str(windows["retrospective_holdout_start"])
    holdout_end = str(windows["retrospective_holdout_end"])
    buy_hold_validation = _slice_metrics(buy_hold, validation_start, validation_end)
    v1_validation = _slice_metrics(v1, validation_start, validation_end)
    v1_stress_validation = _slice_metrics(
        v1_stress, validation_start, validation_end
    )
    aggregate_importance, maximum_importance = _aggregate_feature_importance(
        walk_forward.feature_importance, validation_end
    )
    prediction_quality = _prediction_quality(
        walk_forward.predictions,
        str(windows["oos_prediction_start"]),
        validation_end,
    )

    candidate_results: dict[str, BacktestResult] = {}
    candidate_stress_results: dict[str, BacktestResult] = {}
    candidate_rows: list[dict[str, Any]] = []
    for mapping in POSITION_MAPPINGS:
        position = build_xgb_position(
            dataset.index, walk_forward.predictions, mapping
        )
        result = run_backtest(dataset, position, primary_cost, mapping)
        stress = run_backtest(dataset, position, stress_cost, f"{mapping}_stress")
        candidate_results[mapping] = result
        candidate_stress_results[mapping] = stress
        validation = _slice_metrics(result, validation_start, validation_end)
        validation_stress = _slice_metrics(
            stress, validation_start, validation_end
        )
        positive_quarter_share = _positive_quarter_concentration(
            result, v1, validation_start, validation_end
        )
        gates = {
            "validation_cagr_above_buy_hold": validation["cagr"]
            > buy_hold_validation["cagr"],
            "validation_cagr_above_v1": validation["cagr"]
            > v1_validation["cagr"],
            "validation_total_return_above_buy_hold": validation["total_return"]
            > buy_hold_validation["total_return"],
            "validation_total_return_above_v1": validation["total_return"]
            > v1_validation["total_return"],
            "validation_drawdown_not_worse_3pp": validation["max_drawdown"]
            >= buy_hold_validation["max_drawdown"] - 0.03,
            "validation_calmar_not_below_v1": validation["calmar"]
            >= v1_validation["calmar"],
            "stress_40_total_return_above_v1": validation_stress["total_return"]
            > v1_stress_validation["total_return"],
            "positive_quarter_concentration_cap": positive_quarter_share <= 0.60,
            "validation_prediction_spearman_positive": prediction_quality[
                "spearman"
            ]
            > 0.0,
            "feature_importance_concentration_cap": maximum_importance <= 0.40,
            "three_oos_years_hit_rate_above_50pct": prediction_quality[
                "years_above_50pct"
            ]
            >= 3,
        }
        candidate_rows.append(
            {
                "mapping": mapping,
                "validation_metrics": validation,
                "validation_stress_40_metrics": validation_stress,
                "positive_quarter_share": positive_quarter_share,
                "gates": gates,
                "validation_pass": all(gates.values()),
            }
        )

    passing = [row for row in candidate_rows if row["validation_pass"]]
    passing.sort(
        key=lambda row: (
            row["validation_metrics"]["cagr"],
            row["validation_metrics"]["calmar"],
            row["validation_metrics"]["max_drawdown"],
        ),
        reverse=True,
    )
    selected_mapping = passing[0]["mapping"] if passing else None
    decision = "byd_v1_1_xgb_not_supported"
    holdout: dict[str, Any] | None = None
    if selected_mapping is not None:
        selected = candidate_results[selected_mapping]
        selected_stress = candidate_stress_results[selected_mapping]
        selected_holdout = _slice_metrics(selected, holdout_start, holdout_end)
        selected_holdout_stress = _slice_metrics(
            selected_stress, holdout_start, holdout_end
        )
        v1_holdout = _slice_metrics(v1, holdout_start, holdout_end)
        buy_hold_holdout = _slice_metrics(buy_hold, holdout_start, holdout_end)
        holdout_gates = {
            "holdout_total_return_positive": selected_holdout["total_return"] > 0.0,
            "holdout_cagr_not_below_v1": selected_holdout["cagr"]
            >= v1_holdout["cagr"],
            "holdout_total_return_not_below_v1": selected_holdout["total_return"]
            >= v1_holdout["total_return"],
            "holdout_drawdown_not_worse_3pp": selected_holdout["max_drawdown"]
            >= buy_hold_holdout["max_drawdown"] - 0.03,
            "holdout_stress_40_positive": selected_holdout_stress["total_return"]
            > 0.0,
        }
        holdout = {
            "classification": "retrospective_holdout",
            "candidate_metrics": selected_holdout,
            "candidate_stress_40_metrics": selected_holdout_stress,
            "v1_metrics": v1_holdout,
            "buy_hold_metrics": buy_hold_holdout,
            "gates": holdout_gates,
            "pass": all(holdout_gates.values()),
        }
        if holdout["pass"]:
            decision = "byd_v1_1_xgb_supported"

    latest_prediction = float(walk_forward.latest_snapshot["prediction"])
    latest_targets = {
        mapping: map_prediction_to_position(latest_prediction, mapping)
        for mapping in POSITION_MAPPINGS
    }
    return {
        "experiment_id": str(contract["experiment_id"]),
        "parent_issue": int(contract["parent_issue"]),
        "research_only": True,
        "trade_ready": False,
        "decision": decision,
        "selected_mapping": selected_mapping,
        "feature_names": list(feature_names),
        "market_relative_features_enabled": benchmark_ohlcv is not None,
        "factor_selection": factor_selection,
        "factor_diagnostics": factor_table.to_dict(orient="records"),
        "factor_correlation": factor_correlation,
        "walk_forward_predictions": walk_forward.predictions,
        "fit_manifest": walk_forward.fit_manifest,
        "feature_importance": walk_forward.feature_importance,
        "aggregate_feature_importance": aggregate_importance,
        "maximum_mean_feature_importance_share": maximum_importance,
        "prediction_quality": prediction_quality,
        "candidate_rows": candidate_rows,
        "baselines": {
            "buy_hold_validation": buy_hold_validation,
            "v1_rule_validation": v1_validation,
            "constant75_validation": _slice_metrics(
                constant75, validation_start, validation_end
            ),
            "best_single_factor_validation": _slice_metrics(
                factor_result, validation_start, validation_end
            ),
            "buy_hold_stress_validation": _slice_metrics(
                buy_hold_stress, validation_start, validation_end
            ),
        },
        "retrospective_holdout": holdout,
        "latest_snapshot": walk_forward.latest_snapshot,
        "latest_mapping_targets": latest_targets,
        "dataset": dataset,
        "candidate_results": candidate_results,
        "candidate_stress_results": candidate_stress_results,
        "baseline_results": {
            "buy_hold": buy_hold,
            "v1_rule": v1,
            "constant75": constant75,
            "best_single_factor": factor_result,
        },
    }
