"""Exploratory BYD factor discovery on the governed canonical adjusted series.

This module ranks pre-registered factors by cross-period stability. It does not
promote a trading model and does not treat already-observed periods as an
untouched holdout.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FORWARD_RETURN_COLUMN = "forward_open_return_10"
PERIODS = {
    "development_a": ("2012-01-01", "2015-12-31"),
    "development_b": ("2016-01-01", "2019-12-31"),
    "confirmation_a": ("2020-01-01", "2022-12-31"),
    "confirmation_b": ("2023-01-01", "2024-12-31"),
    "retrospective_2025_plus": ("2025-01-01", "2026-08-03"),
}


@dataclass(frozen=True)
class FactorDiscoveryResult:
    dataset: pd.DataFrame
    diagnostics: pd.DataFrame
    shortlist: pd.DataFrame
    correlation: pd.DataFrame


def _rsi(close: pd.Series, window: int) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0.0).rolling(window).mean()
    loss = (-change.clip(upper=0.0)).rolling(window).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    x = x - x.mean()
    denominator = float(np.square(x).sum())

    def slope(values: np.ndarray) -> float:
        y = np.log(np.asarray(values, dtype=float))
        return float(np.dot(x, y - y.mean()) / denominator)

    return series.rolling(window).apply(slope, raw=True)


def _efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    direction = close.diff(window).abs()
    path = close.diff().abs().rolling(window).sum()
    return direction / path.replace(0.0, np.nan)


def build_factor_dataset(adjusted_bars: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(adjusted_bars.columns))
    if missing:
        raise ValueError(f"adjusted bars missing columns: {missing}")
    frame = adjusted_bars.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    frame = frame.set_index("date")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)

    close = frame["close"]
    open_ = frame["open"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"].replace(0.0, np.nan)
    daily_return = close.pct_change()
    open_return = open_.pct_change()
    features: dict[str, pd.Series] = {}

    for window in (2, 5, 10, 20, 40, 60, 120, 252):
        features[f"mom_{window}"] = close.pct_change(window)
        features[f"open_mom_{window}"] = open_.pct_change(window)
    for recent, long_window in ((5, 20), (10, 40), (20, 60), (20, 120)):
        features[f"skip_recent_{recent}_{long_window}"] = (
            close.shift(recent).pct_change(long_window - recent)
        )
    for short, long_window in ((5, 20), (10, 40), (20, 60), (20, 120)):
        features[f"momentum_accel_{short}_{long_window}"] = (
            close.pct_change(short) - close.pct_change(long_window)
        )

    for window in (20, 60, 120, 252):
        rolling_high = close.rolling(window).max()
        rolling_low = close.rolling(window).min()
        drawdown = close / rolling_high - 1.0
        distance_low = close / rolling_low - 1.0
        features[f"drawdown_{window}"] = drawdown
        features[f"distance_from_low_{window}"] = distance_low
        features[f"range_position_{window}"] = (
            (close - rolling_low) / (rolling_high - rolling_low).replace(0.0, np.nan)
        )
        features[f"trend_slope_{window}"] = _rolling_slope(close, window)
        features[f"efficiency_ratio_{window}"] = _efficiency_ratio(close, window)

    features["drawdown120_x_rebound20"] = (
        -features["drawdown_120"] * features["distance_from_low_20"]
    )
    features["drawdown252_x_rebound60"] = (
        -features["drawdown_252"] * features["distance_from_low_60"]
    )
    features["recovery_velocity_20_60"] = (
        features["distance_from_low_20"] - features["distance_from_low_60"]
    )
    features["short_continuation_long_reversal"] = (
        features["mom_2"] - features["mom_120"]
    )

    for window in (5, 10, 20):
        features[f"rsi_{window}"] = _rsi(close, window)
    for window in (20, 60):
        mean = close.rolling(window).mean()
        std = close.rolling(window).std()
        features[f"bollinger_z_{window}"] = (close - mean) / std.replace(0.0, np.nan)
        features[f"close_to_sma_{window}"] = close / mean - 1.0

    vol20 = daily_return.rolling(20).std()
    vol60 = daily_return.rolling(60).std()
    features["realized_vol_20"] = vol20
    features["realized_vol_60"] = vol60
    features["vol_compression_20_60"] = vol20 / vol60.replace(0.0, np.nan)
    features["downside_vol_20"] = daily_return.clip(upper=0.0).rolling(20).std()
    features["upside_downside_vol_ratio_20"] = (
        daily_return.clip(lower=0.0).rolling(20).std()
        / features["downside_vol_20"].replace(0.0, np.nan)
    )
    features["return_autocorr_20"] = daily_return.rolling(20).corr(daily_return.shift(1))
    features["open_return_autocorr_20"] = open_return.rolling(20).corr(open_return.shift(1))

    features["overnight_gap"] = open_ / close.shift(1) - 1.0
    features["intraday_return"] = close / open_ - 1.0
    features["intraday_range"] = (high - low) / close
    features["close_location"] = (close - low) / (high - low).replace(0.0, np.nan)
    features["gap_reversal_5"] = -features["overnight_gap"].rolling(5).sum()

    log_volume = np.log(volume)
    features["volume_z_20"] = (
        log_volume - log_volume.rolling(20).mean()
    ) / log_volume.rolling(20).std().replace(0.0, np.nan)
    features["volume_change_20"] = volume.pct_change(20)
    features["price_volume_corr_20"] = daily_return.rolling(20).corr(log_volume.diff())
    features["up_volume_share_20"] = (
        (volume.where(daily_return > 0, 0.0)).rolling(20).sum()
        / volume.rolling(20).sum().replace(0.0, np.nan)
    )
    features["rebound_volume_confirmation"] = (
        features["distance_from_low_20"] * features["volume_z_20"]
    )

    feature_frame = pd.DataFrame(features, index=frame.index)
    dataset = pd.concat([frame, feature_frame], axis=1)
    dataset[FORWARD_RETURN_COLUMN] = open_.shift(-11) / open_.shift(-1) - 1.0
    return dataset, list(features)


def _quintile_stats(frame: pd.DataFrame, factor: str) -> tuple[float, float]:
    sample = frame[[factor, FORWARD_RETURN_COLUMN]].dropna()
    if len(sample) < 50 or sample[factor].nunique() < 5:
        return float("nan"), float("nan")
    try:
        bucket = pd.qcut(sample[factor], 5, labels=False, duplicates="drop")
    except ValueError:
        return float("nan"), float("nan")
    means = sample.groupby(bucket, observed=True)[FORWARD_RETURN_COLUMN].mean()
    if len(means) < 5:
        return float("nan"), float("nan")
    spread = float(means.iloc[-1] - means.iloc[0])
    monotonicity = float(pd.Series(range(len(means))).corr(means, method="spearman"))
    return spread, monotonicity


def factor_diagnostics(
    dataset: pd.DataFrame,
    factors: list[str],
    *,
    periods: dict[str, tuple[str, str]] | None = None,
) -> pd.DataFrame:
    periods = periods or PERIODS
    rows: list[dict[str, object]] = []
    for factor in factors:
        period_ics: list[float] = []
        row: dict[str, object] = {"factor": factor}
        for name, (start, end) in periods.items():
            sample = dataset.loc[start:end, [factor, FORWARD_RETURN_COLUMN]].dropna()
            ic = float(sample[factor].corr(sample[FORWARD_RETURN_COLUMN], method="spearman")) if len(sample) >= 30 else float("nan")
            pearson = float(sample[factor].corr(sample[FORWARD_RETURN_COLUMN])) if len(sample) >= 30 else float("nan")
            spread, monotonicity = _quintile_stats(sample, factor)
            hit_rate = float(
                (np.sign(sample[factor] - sample[factor].median()) == np.sign(sample[FORWARD_RETURN_COLUMN])).mean()
            ) if len(sample) >= 30 else float("nan")
            row[f"{name}_spearman"] = ic
            row[f"{name}_pearson"] = pearson
            row[f"{name}_spread"] = spread
            row[f"{name}_monotonicity"] = monotonicity
            row[f"{name}_hit_rate"] = hit_rate
            row[f"{name}_samples"] = int(len(sample))
            if np.isfinite(ic):
                period_ics.append(ic)
        finite = np.asarray(period_ics, dtype=float)
        if finite.size:
            signs = np.sign(finite)
            dominant_sign = 1.0 if np.sum(signs > 0) >= np.sum(signs < 0) else -1.0
            oriented = finite * dominant_sign
            row["orientation"] = "positive" if dominant_sign > 0 else "negative"
            row["period_sign_consistency"] = float((oriented > 0).mean())
            row["median_oriented_ic"] = float(np.median(oriented))
            row["worst_oriented_ic"] = float(np.min(oriented))
            row["mean_abs_ic"] = float(np.mean(np.abs(finite)))
            row["stability_score"] = float(
                (oriented > 0).mean() * np.median(oriented) + 0.5 * np.min(oriented)
            )
        else:
            row.update(
                {
                    "orientation": "unknown",
                    "period_sign_consistency": 0.0,
                    "median_oriented_ic": float("nan"),
                    "worst_oriented_ic": float("nan"),
                    "mean_abs_ic": float("nan"),
                    "stability_score": float("nan"),
                }
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["period_sign_consistency", "stability_score", "mean_abs_ic"],
        ascending=False,
    ).reset_index(drop=True)


def discover_factors(adjusted_bars: pd.DataFrame) -> FactorDiscoveryResult:
    dataset, factors = build_factor_dataset(adjusted_bars)
    diagnostics = factor_diagnostics(dataset, factors)
    shortlist = diagnostics.loc[
        (diagnostics["period_sign_consistency"] >= 0.8)
        & (diagnostics["median_oriented_ic"] >= 0.02)
        & (diagnostics["worst_oriented_ic"] >= -0.01)
    ].copy()
    correlation = dataset[factors].corr(method="spearman")
    return FactorDiscoveryResult(
        dataset=dataset,
        diagnostics=diagnostics,
        shortlist=shortlist,
        correlation=correlation,
    )
