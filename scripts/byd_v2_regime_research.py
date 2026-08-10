"""BYD v2.0 Regime Model Research — Issue #716.

Comprehensive experiment script: walk-forward stability, benchmark comparison,
holding inertia, and XGBoost regime classification for single-asset BYD model.

Experiments:
  1. Walk-forward stability test (focus 2022-2026)
  2. Benchmark comparison (B&H, fixed allocation, v1.x, regime model, CSI300)
  3. Position holding inertia (min holding 10/20/30/60 days)
  4. XGBoost regime classification (Bull/Neutral/Bear → position allocation)

Output: data/research/byd_v2_experiments/{timestamp}/
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# — Project root ——————————————————————————————————————————————————————
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_single_asset_v1 import (
    BacktestResult,
    _return_metrics,
    _stateful_position,
    build_features,
    normalise_ohlcv,
    run_backtest,
    run_buy_and_hold,
)

# — Constants ——————————————————————————————————————————————————————————
CANONICAL_ROOT = PROJECT_ROOT / "data" / "research" / "byd_canonical_v1_extracted"
ETF_ROOT = PROJECT_ROOT / "data" / "research" / "515180_canonical_v1_extracted"
OUTPUT_BASE = PROJECT_ROOT / "data" / "research" / "byd_v2_experiments"

RANDOM_STATE = 42
COST_BPS = 10.0
INITIAL_CAPITAL = 1.0

EXPERIMENT_WINDOWS = {
    "full": ("2012-01-01", "2026-08-03"),
    "development": ("2012-01-01", "2021-12-31"),
    "walk_forward_2022": ("2022-01-01", "2022-12-31"),
    "walk_forward_2023": ("2023-01-01", "2023-12-31"),
    "walk_forward_2024": ("2024-01-01", "2024-12-31"),
    "walk_forward_2025": ("2025-01-01", "2025-12-31"),
    "walk_forward_2026": ("2026-01-01", "2026-08-03"),
    "focus_2022_2026": ("2022-01-01", "2026-08-03"),
}

REGIME_LABEL_HORIZON = 60  # 60-day forward return for regime definition
REGIME_THRESHOLDS = {
    "bull": 0.10,   # >10% forward return = bull
    "bear": -0.10,  # <-10% forward return = bear
}

POSITION_ALLOCATIONS = {
    "byd_100": {"BYD": 1.00, "ETF": 0.00},
    "byd_75_etf_25": {"BYD": 0.75, "ETF": 0.25},
    "byd_50_etf_50": {"BYD": 0.50, "ETF": 0.50},
    "etf_100": {"BYD": 0.00, "ETF": 1.00},
}

MIN_HOLDING_PERIODS = [10, 20, 30, 60]

# — Feature definitions per Issue #716 —————————————————————————————————
# Keep effective factors from v1.x, add new ones
TREND_FACTOR_CONFIG = {
    "sma_200_state": {"window": 200, "type": "ma_state"},
    "mom_12m": {"window": 252, "type": "momentum"},
}

VALUATION_FACTOR_CONFIG = {
    "pe_percentile": {"window": 756, "type": "valuation_percentile"},
}

SENTIMENT_FACTOR_CONFIG = {
    "rsi_14": {"window": 14, "type": "rsi"},
    "rsi_extreme": {"window": 14, "type": "rsi_extreme"},
    "vol_60": {"window": 60, "type": "volatility"},
    "vol_regime": {"window": 60, "type": "vol_regime"},
}

# — Helpers ————————————————————————————————————————————————————————————


def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Rolling percentile rank (0-1) of current value within lookback window."""
    result = pd.Series(np.nan, index=series.index, dtype=float)
    values = series.values
    for i in range(len(values)):
        if i < window - 1:
            continue
        window_vals = values[i - window + 1 : i + 1]
        result.iloc[i] = (window_vals < values[i]).sum() / len(window_vals)
    return result


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.where(avg_loss.ne(0.0), 100.0)
    rsi = rsi.where(avg_gain.ne(0.0), 0.0)
    both_zero = avg_gain.eq(0.0) & avg_loss.eq(0.0)
    return rsi.where(~both_zero, 50.0)


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    x -= x.mean()
    denominator = float(np.square(x).sum())

    def slope(values: np.ndarray) -> float:
        y = np.log(np.asarray(values, dtype=float))
        return float(np.dot(x, y - y.mean()) / denominator)

    return series.rolling(window).apply(slope, raw=True)


def _stateful_position_min_hold(
    entry: pd.Series,
    exit_: pd.Series,
    min_hold: int = 10,
) -> pd.Series:
    """Stateful position with minimum holding period constraint."""
    active = False
    hold_counter = 0
    values: list[float] = []
    for enter_now, exit_now in zip(
        entry.fillna(False), exit_.fillna(False), strict=True
    ):
        if active:
            hold_counter += 1
        if active and bool(exit_now) and hold_counter >= min_hold:
            active = False
            hold_counter = 0
        elif not active and bool(enter_now):
            active = True
            hold_counter = 0
        values.append(1.0 if active else 0.0)
    return pd.Series(values, index=entry.index, dtype=float)


# — Enhanced feature builder —————————————————————————————————————————————


def build_enhanced_features(dataset: pd.DataFrame) -> pd.DataFrame:
    """Build enhanced feature set per Issue #716 specifications.

    Includes existing v1.x factors plus:
      - Trend: MA200 state, 12-month momentum
      - Valuation: PE historical percentile (proxy via price/MA200 ratio)
      - Sentiment: RSI extremes, volatility regime
    """
    frame = dataset.copy()
    close = frame["close"]

    # — Trend factors ——————————————————————————————————————————————
    frame["sma_200"] = close.rolling(200, min_periods=200).mean()
    frame["sma_60"] = close.rolling(60, min_periods=60).mean()
    frame["sma_120"] = close.rolling(120, min_periods=120).mean()

    # MA200 state: distance from MA200 as fraction
    frame["ma200_distance"] = close / frame["sma_200"] - 1.0

    # MA state categorical
    bull = close.gt(frame["sma_200"]) & frame["sma_60"].gt(frame["sma_200"])
    bear = close.lt(frame["sma_200"]) & frame["sma_60"].lt(frame["sma_200"])
    frame["ma_state"] = np.select([bull, bear], [1, -1], default=0)

    # 12-month momentum
    frame["mom_12m"] = close.pct_change(252)

    # Short momentum
    frame["mom_20"] = close.pct_change(20)
    frame["mom_60"] = close.pct_change(60)
    frame["mom_120"] = close.pct_change(120)

    # Momentum acceleration
    frame["mom_accel_20_60"] = frame["mom_20"] - frame["mom_60"]

    # — Drawdown / recovery factors ——————————————————————————————————
    high252 = close.rolling(252, min_periods=252).max()
    low20 = close.rolling(20, min_periods=20).min()
    frame["drawdown_252"] = close / high252 - 1.0
    frame["distance_from_low_20"] = close / low20 - 1.0

    # Long-term reversal
    frame["long_reversal"] = -frame["mom_12m"]

    # Weak short-term continuation
    frame["short_continuation"] = close.pct_change(5)

    # — Valuation proxy factors ——————————————————————————————————————
    frame["price_to_ma200"] = close / frame["sma_200"]
    frame["price_to_ma60"] = close / frame["sma_60"]

    # PE percentile proxy: how extended price is vs. 3-year rolling range
    high756 = close.rolling(756, min_periods=252).max()
    low756 = close.rolling(756, min_periods=252).min()
    frame["price_percentile_3y"] = (close - low756) / (high756 - low756).replace(0.0, np.nan)

    # Valuation expansion/contraction
    frame["valuation_expansion"] = frame["price_to_ma200"].diff(60)

    # — Sentiment factors ————————————————————————————————————————————
    frame["rsi_14"] = _wilder_rsi(close, 14)

    # RSI extreme zones
    frame["rsi_oversold"] = (frame["rsi_14"] < 30).astype(float)
    frame["rsi_overbought"] = (frame["rsi_14"] > 70).astype(float)
    frame["rsi_extreme"] = np.where(
        frame["rsi_14"] < 30, -1,
        np.where(frame["rsi_14"] > 70, 1, 0),
    )

    # Volatility
    daily_ret = close.pct_change()
    frame["realized_vol_20"] = daily_ret.rolling(20).std()
    frame["realized_vol_60"] = daily_ret.rolling(60).std()

    # Volatility regime
    vol_median_3y = (
        frame["realized_vol_60"]
        .rolling(756, min_periods=252)
        .median()
    )
    frame["vol_regime_high"] = (frame["realized_vol_60"] > vol_median_3y).astype(float)

    # — Trend slope ——————————————————————————————————————————————————
    frame["trend_slope_60"] = _rolling_slope(close, 60)
    frame["trend_slope_120"] = _rolling_slope(close, 120)

    # — Open return autocorrelation ——————————————————————————————————
    open_ = frame["open"]
    open_return = open_.pct_change()
    frame["open_autocorr_20"] = open_return.rolling(20).corr(open_return.shift(1))

    return frame


# — Regime label construction ————————————————————————————————————————————


def build_regime_labels(
    frame: pd.DataFrame,
    horizon: int = REGIME_LABEL_HORIZON,
    bull_threshold: float = REGIME_THRESHOLDS["bull"],
    bear_threshold: float = REGIME_THRESHOLDS["bear"],
) -> pd.DataFrame:
    """Construct Bull/Neutral/Bear regime labels from forward returns.

    Labels are determined by forward open-to-open return over `horizon` days.
    This ensures no forward-looking bias when features use only current/past data.
    """
    result = frame.copy()
    open_ = result["open"]

    # Forward open-to-open return
    eligible_entry = result.get("open_research_eligible", pd.Series(True, index=result.index))
    eligible_exit = eligible_entry.shift(-horizon).fillna(False)

    forward_return = open_.shift(-horizon) / open_ - 1.0
    valid_mask = eligible_entry.astype(bool) & eligible_exit.astype(bool)
    forward_return = forward_return.where(valid_mask)

    conditions = [
        forward_return > bull_threshold,
        forward_return < bear_threshold,
    ]
    choices = [2, 0]  # 2=Bull, 0=Bear
    result["regime_label"] = np.select(conditions, choices, default=1)  # 1=Neutral
    result["forward_return"] = forward_return

    return result


# — Feature matrix construction ——————————————————————————————————————————


FEATURE_COLUMNS = [
    "ma200_distance",
    "ma_state",
    "mom_12m",
    "mom_20",
    "mom_60",
    "mom_120",
    "mom_accel_20_60",
    "drawdown_252",
    "distance_from_low_20",
    "long_reversal",
    "short_continuation",
    "price_to_ma200",
    "price_to_ma60",
    "price_percentile_3y",
    "valuation_expansion",
    "rsi_14",
    "rsi_extreme",
    "realized_vol_20",
    "realized_vol_60",
    "vol_regime_high",
    "trend_slope_60",
    "trend_slope_120",
    "open_autocorr_20",
]


def build_feature_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Build X/y for regime classification."""
    df = frame.dropna(subset=FEATURE_COLUMNS + ["regime_label"])
    X = df[FEATURE_COLUMNS].copy()
    y = df["regime_label"].copy()
    # Remove rows where label is NaN (not enough forward data)
    valid = y.notna()
    return X.loc[valid], y.loc[valid]


# — XGBoost regime classifier ————————————————————————————————————————————


def train_regime_classifier(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    random_state: int = RANDOM_STATE,
) -> tuple[Any, np.ndarray, np.ndarray]:
    """Train XGBoost classifier for 3-class regime prediction."""
    from xgboost import XGBClassifier

    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        random_state=random_state,
        verbosity=0,
    )
    model.fit(X_train, y_train)
    pred_proba = model.predict_proba(X_test)
    pred_class = model.predict(X_test)
    return model, pred_proba, pred_class


# — Regime → Position mapping —————————————————————————————————————————————


def regime_to_position(
    regime_predictions: np.ndarray,
    allocation: str = "byd_100",
) -> pd.Series:
    """Map regime predictions to position weights.

    regime=2 (Bull)  → aggressive
    regime=1 (Neutral) → moderate
    regime=0 (Bear)  → defensive
    """
    weights = POSITION_ALLOCATIONS[allocation]
    # Map: Bull→full risk, Neutral→moderate, Bear→defensive
    regime_map = {
        2: weights["BYD"],   # Bull: risk-on
        1: weights["BYD"] * 0.7,  # Neutral: reduced
        0: 0.0,  # Bear: cash/ETF only (no BYD)
    }
    return pd.Series([regime_map.get(int(p), 0.0) for p in regime_predictions])


def regime_to_dual_position(
    regime_predictions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Map to BYD + ETF dual-asset positions."""
    strategy = {
        2: (1.00, 0.00),   # Bull: 100% BYD
        1: (0.75, 0.25),   # Neutral: 75% BYD + 25% ETF
        0: (0.00, 1.00),   # Bear: 100% ETF
    }
    byd_pos = np.array([strategy.get(int(p), (0.75, 0.25))[0] for p in regime_predictions])
    etf_pos = np.array([strategy.get(int(p), (0.75, 0.25))[1] for p in regime_predictions])
    return byd_pos, etf_pos


# — Backtest helpers ——————————————————————————————————————————————————————


def compute_metrics(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
) -> dict[str, float]:
    """Compute comprehensive performance metrics."""
    clean = returns.dropna()
    if clean.empty:
        return {}

    years = len(clean) / 252.0
    wealth = (1.0 + clean).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and wealth.iloc[-1] > 0 else -1.0
    volatility = float(clean.std(ddof=0) * np.sqrt(252.0))
    sharpe = float(clean.mean() / clean.std(ddof=0) * np.sqrt(252.0)) if clean.std(ddof=0) > 0 else 0.0

    downside = clean.clip(upper=0.0)
    downside_dev = float(np.sqrt((downside.pow(2)).mean()) * np.sqrt(252.0))
    sortino = float(clean.mean() * 252.0 / downside_dev) if downside_dev > 0 else 0.0

    max_dd = float((wealth / wealth.cummax() - 1.0).min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0

    metrics = {
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "n_sessions": float(len(clean)),
        "years": years,
    }
    if benchmark_returns is not None:
        excess = clean - benchmark_returns.reindex(clean.index).fillna(0.0)
        metrics["excess_return"] = float((1.0 + excess).prod() - 1.0)
        metrics["information_ratio"] = (
            float(excess.mean() / excess.std(ddof=0) * np.sqrt(252.0))
            if excess.std(ddof=0) > 0 else 0.0
        )
    return metrics


def run_single_asset_backtest(
    frame: pd.DataFrame,
    position: pd.Series,
    cost_bps: float = COST_BPS,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Run backtest with single-asset position series."""
    daily = frame[["open", "close"]].copy()
    pos_aligned = position.reindex(daily.index).fillna(0.0)

    # Execute at next open
    daily["position"] = pos_aligned.shift(1).fillna(0.0)
    daily["asset_return"] = daily["open"].shift(-1) / daily["open"] - 1.0
    daily = daily.iloc[:-1].copy()

    # Turnover costs
    daily["turnover"] = daily["position"].diff().abs()
    daily["turnover"].iloc[0] = abs(daily["position"].iloc[0])
    daily["cost"] = daily["turnover"] * cost_bps / 10000.0
    daily["gross_return"] = daily["position"] * daily["asset_return"]
    daily["net_return"] = daily["gross_return"] - daily["cost"]

    metrics = compute_metrics(daily["net_return"])
    metrics["total_turnover"] = float(daily["turnover"].sum())
    metrics["avg_position"] = float(daily["position"].mean())

    return daily, metrics


def run_dual_asset_backtest(
    frame: pd.DataFrame,
    byd_position: pd.Series,
    etf_position: pd.Series,
    cost_bps: float = COST_BPS,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Run backtest with dual-asset (BYD + ETF) positions."""
    daily = frame[["byd_open", "etf_open"]].copy() if "byd_open" in frame.columns else frame[["open", "close"]].copy()

    byd_aligned = byd_position.reindex(daily.index).fillna(0.0)
    etf_aligned = etf_position.reindex(daily.index).fillna(0.0)

    if "byd_open" in daily.columns:
        daily["byd_pos"] = byd_aligned.shift(1).fillna(0.0)
        daily["etf_pos"] = etf_aligned.shift(1).fillna(0.0)
        daily["byd_ret"] = daily["byd_open"].shift(-1) / daily["byd_open"] - 1.0
        daily["etf_ret"] = daily["etf_open"].shift(-1) / daily["etf_open"] - 1.0
        daily = daily.iloc[:-1].copy()
        daily["turnover"] = (
            daily["byd_pos"].diff().abs() + daily["etf_pos"].diff().abs()
        )
        daily["turnover"].iloc[0] = abs(daily["byd_pos"].iloc[0]) + abs(daily["etf_pos"].iloc[0])
        daily["gross_return"] = (
            daily["byd_pos"] * daily["byd_ret"] + daily["etf_pos"] * daily["etf_ret"]
        )
    else:
        # Single-asset fallback (when ETF data is unavailable)
        daily["position"] = byd_aligned.shift(1).fillna(0.0)
        daily["asset_return"] = daily["open"].shift(-1) / daily["open"] - 1.0
        daily = daily.iloc[:-1].copy()
        daily["turnover"] = daily["position"].diff().abs()
        daily["turnover"].iloc[0] = abs(daily["position"].iloc[0])
        daily["gross_return"] = daily["position"] * daily["asset_return"]

    daily["cost"] = daily["turnover"] * cost_bps / 10000.0
    daily["net_return"] = daily["gross_return"] - daily["cost"]

    metrics = compute_metrics(daily["net_return"])
    metrics["total_turnover"] = float(daily["turnover"].sum())

    return daily, metrics


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 1: Walk-forward stability test
# ═══════════════════════════════════════════════════════════════════════════


def run_experiment_1_walk_forward(frame: pd.DataFrame) -> dict[str, Any]:
    """Walk-forward stability test with expanding training windows.

    Tests whether the XGBoost regime classifier maintains predictive power
    across different market periods, particularly 2022-2026.
    """
    print("=" * 70)
    print("Experiment 1: Walk-forward Stability Test")
    print("=" * 70)

    labeled = build_regime_labels(frame)
    X_all, y_all = build_feature_matrix(labeled)

    # Define walk-forward splits
    splits = [
        ("2012-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        ("2012-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
        ("2012-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
        ("2012-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
        ("2012-01-01", "2025-12-31", "2026-01-01", "2026-08-03"),
    ]

    results = []
    for train_start, train_end, test_start, test_end in splits:
        train_mask = (X_all.index >= train_start) & (X_all.index <= train_end)
        test_mask = (X_all.index >= test_start) & (X_all.index <= test_end)

        X_train = X_all.loc[train_mask]
        y_train = y_all.loc[train_mask]
        X_test = X_all.loc[test_mask]
        y_test = y_all.loc[test_mask]

        if len(X_train) < 100 or len(X_test) < 30:
            print(f"  Skipping {test_start}→{test_end}: insufficient data")
            continue

        model, proba, preds = train_regime_classifier(X_train, y_train, X_test)

        accuracy = float((preds == y_test.values).mean())
        # Weighted: correct direction (bull vs bear) matters more
        pred_direction = np.where(preds == 2, 1, np.where(preds == 0, -1, 0))
        true_direction = np.where(y_test.values == 2, 1, np.where(y_test.values == 0, -1, 0))
        direction_accuracy = float((pred_direction == true_direction).mean())

        # Regime distribution
        _, pred_counts = np.unique(preds, return_counts=True)
        pred_dist = dict(zip(["bear", "neutral", "bull"], pred_counts / len(preds)))

        split_result = {
            "train_period": f"{train_start}→{train_end}",
            "test_period": f"{test_start}→{test_end}",
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "accuracy": accuracy,
            "direction_accuracy": direction_accuracy,
            "predicted_regime_distribution": pred_dist,
            "actual_regime_distribution": {
                "bear": float((y_test == 0).mean()),
                "neutral": float((y_test == 1).mean()),
                "bull": float((y_test == 2).mean()),
            },
        }

        # Run backtest for this split
        frame.loc[X_test.index].copy()
        position = regime_to_position(preds, allocation="byd_100")
        position.index = X_test.index

        # Fill non-test dates with NaN for position
        full_position = pd.Series(np.nan, index=frame.index, dtype=float)
        full_position.loc[position.index] = position.values

        _, bt_metrics = run_single_asset_backtest(frame, full_position)
        split_result["backtest"] = bt_metrics

        results.append(split_result)
        print(
            f"  {test_start}→{test_end}: accuracy={accuracy:.3f}, "
            f"dir_accuracy={direction_accuracy:.3f}, "
            f"sharpe={bt_metrics.get('sharpe', 0):.3f}"
        )

    # Stability score: std of accuracy across splits
    accuracies = [r["accuracy"] for r in results]
    stability_score = float(np.std(accuracies)) if len(accuracies) > 1 else 0.0

    summary = {
        "splits": results,
        "n_splits": len(results),
        "mean_accuracy": float(np.mean(accuracies)) if accuracies else 0.0,
        "std_accuracy": stability_score,
        "stability_assessment": (
            "stable" if stability_score < 0.10 else "moderate" if stability_score < 0.20 else "unstable"
        ),
    }
    print(f"  Stability: mean_acc={summary['mean_accuracy']:.3f}, "
          f"std={stability_score:.3f} → {summary['stability_assessment']}")
    return summary


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 2: Benchmark comparison
# ═══════════════════════════════════════════════════════════════════════════


def run_experiment_2_benchmarks(frame: pd.DataFrame) -> dict[str, Any]:
    """Compare all benchmarks over the focus period 2022-2026.

    Benchmarks:
      1. BYD Buy & Hold
      2. BYD 75% + 515180 25% fixed
      3. BYD v1.x model (trend_20_60)
      4. XGBoost Regime Model
      5. CSI300 proxy (BYD behavior benchmark — same asset, different rules)
    """
    print("\n" + "=" * 70)
    print("Experiment 2: Benchmark Comparison")
    print("=" * 70)

    focus_mask = (frame.index >= "2022-01-01") & (frame.index <= "2026-08-03")
    focus = frame.loc[focus_mask].copy()

    benchmarks = {}

    # 1. BYD Buy & Hold
    bh_position = pd.Series(1.0, index=focus.index, dtype=float)
    _, bh_metrics = run_single_asset_backtest(focus, bh_position)
    benchmarks["byd_buy_hold"] = bh_metrics
    print(f"  BYD Buy & Hold: CAGR={bh_metrics['cagr']:.4f}, "
          f"Sharpe={bh_metrics['sharpe']:.3f}, MaxDD={bh_metrics['max_drawdown']:.4f}")

    # 2. BYD 75% + 515180 25% fixed
    fixed_7525_position = pd.Series(0.75, index=focus.index, dtype=float)
    _, f7525_metrics = run_single_asset_backtest(focus, fixed_7525_position)
    benchmarks["byd_75_etf_25_fixed"] = f7525_metrics
    print(f"  BYD 75%+ETF 25%: CAGR={f7525_metrics['cagr']:.4f}, "
          f"Sharpe={f7525_metrics['sharpe']:.3f}, MaxDD={f7525_metrics['max_drawdown']:.4f}")

    # 3. BYD v1.x model (trend_20_60)
    v1_features = build_features(frame[["open", "high", "low", "close", "volume"]])
    v1_positions = {}
    v1_close = v1_features["close"]
    v1_positions["trend_20_60"] = _stateful_position(
        entry=v1_close.gt(v1_features["sma_60"]) & v1_features["sma_20"].gt(v1_features["sma_60"]),
        exit_=v1_close.lt(v1_features["sma_20"]) | v1_features["sma_20"].lt(v1_features["sma_60"]),
    )
    v1_position = v1_positions["trend_20_60"].reindex(focus.index).fillna(0.0)
    _, v1_metrics = run_single_asset_backtest(focus, v1_position)
    benchmarks["byd_v1_trend_20_60"] = v1_metrics
    print(f"  BYD v1.x trend_20_60: CAGR={v1_metrics['cagr']:.4f}, "
          f"Sharpe={v1_metrics['sharpe']:.3f}, MaxDD={v1_metrics['max_drawdown']:.4f}")

    # 4. XGBoost Regime Model (train on pre-2022, test on 2022-2026)
    labeled = build_regime_labels(frame)
    X_all, y_all = build_feature_matrix(labeled)

    train_mask = (X_all.index >= "2012-01-01") & (X_all.index <= "2021-12-31")
    test_mask = (X_all.index >= "2022-01-01") & (X_all.index <= "2026-08-03")

    X_train = X_all.loc[train_mask]
    y_train = y_all.loc[train_mask]
    X_test = X_all.loc[test_mask]

    if len(X_train) >= 100 and len(X_test) >= 30:
        model, proba, preds = train_regime_classifier(X_train, y_train, X_test)

        # Dual allocation strategy
        byd_pos, etf_pos = regime_to_dual_position(preds)
        pd.Series(byd_pos, index=X_test.index, dtype=float)
        # For single-asset evaluation, use BYD position only
        regime_position = pd.Series(byd_pos, index=X_test.index, dtype=float)

        # Full period position (NaN outside test = no position)
        full_position = pd.Series(np.nan, index=focus.index, dtype=float)
        full_position.loc[regime_position.index] = regime_position.values

        _, regime_metrics = run_single_asset_backtest(focus, full_position)

        # Regime distribution
        _, counts = np.unique(preds, return_counts=True)
        regimes = dict(zip(["bear", "neutral", "bull"], counts))

        benchmarks["xgboost_regime_model"] = {
            **regime_metrics,
            "regime_distribution": regimes,
            "n_bull_signals": int(regimes.get("bull", 0)),
            "n_neutral_signals": int(regimes.get("neutral", 0)),
            "n_bear_signals": int(regimes.get("bear", 0)),
        }
        print(f"  XGBoost Regime: CAGR={regime_metrics['cagr']:.4f}, "
              f"Sharpe={regime_metrics['sharpe']:.3f}, MaxDD={regime_metrics['max_drawdown']:.4f}")
        print(f"    Regime distribution: {regimes}")
    else:
        benchmarks["xgboost_regime_model"] = {"error": "insufficient data"}
        print("  XGBoost Regime: SKIPPED (insufficient data)")

    # 5. CSI300 proxy benchmark (equity index benchmark)
    # We use a simple SMA crossover as a proxy market-timing benchmark
    close = focus["close"]
    sma120 = close.rolling(120).mean()
    csi300_position = (close > sma120).astype(float)
    _, csi300_metrics = run_single_asset_backtest(focus, csi300_position)
    benchmarks["csi300_proxy"] = csi300_metrics
    print(f"  CSI300 Proxy: CAGR={csi300_metrics['cagr']:.4f}, "
          f"Sharpe={csi300_metrics['sharpe']:.3f}, MaxDD={csi300_metrics['max_drawdown']:.4f}")

    # Comparison table
    comparison_rows = []
    for name, metrics in benchmarks.items():
        if "error" in metrics:
            continue
        comparison_rows.append({
            "benchmark": name,
            "cagr": round(metrics.get("cagr", 0), 4),
            "max_drawdown": round(metrics.get("max_drawdown", 0), 4),
            "sharpe": round(metrics.get("sharpe", 0), 4),
            "calmar": round(metrics.get("calmar", 0), 4),
            "sortino": round(metrics.get("sortino", 0), 4),
            "total_turnover": round(metrics.get("total_turnover", 0), 4),
            "avg_position": round(metrics.get("avg_position", 0), 4),
        })

    comparison_df = pd.DataFrame(comparison_rows).set_index("benchmark")
    print("\n  Comparison Summary:")
    print(comparison_df.to_string())

    return {"benchmarks": benchmarks, "comparison_table": comparison_rows}


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 3: Position holding inertia test
# ═══════════════════════════════════════════════════════════════════════════


def run_experiment_3_holding_inertia(frame: pd.DataFrame) -> dict[str, Any]:
    """Test minimum holding period constraints to reduce overtrading.

    Tests min holding periods: 10, 20, 30, 60 days.
    Uses the regime model signals but enforces minimum holding constraints.
    """
    print("\n" + "=" * 70)
    print("Experiment 3: Position Holding Inertia Test")
    print("=" * 70)

    focus_mask = (frame.index >= "2022-01-01") & (frame.index <= "2026-08-03")

    # Train regime model on pre-2022
    labeled = build_regime_labels(frame)
    X_all, y_all = build_feature_matrix(labeled)
    train_mask = (X_all.index >= "2012-01-01") & (X_all.index <= "2021-12-31")
    test_mask = (X_all.index >= "2022-01-01") & (X_all.index <= "2026-08-03")

    X_train = X_all.loc[train_mask]
    y_train = y_all.loc[train_mask]
    X_test = X_all.loc[test_mask]

    if len(X_train) < 100 or len(X_test) < 30:
        print("  Insufficient data for regime model training")
        return {"error": "insufficient data"}

    model, proba, preds = train_regime_classifier(X_train, y_train, X_test)
    focus = frame.loc[focus_mask].copy()

    # Base regime position (no min hold)
    base_position = pd.Series(preds, index=X_test.index, dtype=float)
    # Convert to binary long/cash for inertia testing
    # regime=2 (bull) → 1.0, regime=1 (neutral) → 0.75, regime=0 (bear) → 0.0
    binary_long = base_position.map({2: 1.0, 1: 1.0, 0: 0.0})
    binary_exit = base_position.map({2: 0.0, 1: 0.0, 0: 1.0})

    results = {}
    for min_hold in MIN_HOLDING_PERIODS:
        constrained = _stateful_position_min_hold(
            entry=binary_long > 0.5,
            exit_=binary_exit > 0.5,
            min_hold=min_hold,
        )
        constrained.index = X_test.index

        full_pos = pd.Series(np.nan, index=focus.index, dtype=float)
        full_pos.loc[constrained.index] = constrained.values

        _, metrics = run_single_asset_backtest(focus, full_pos)

        # Count trades
        trade_changes = constrained.diff().abs()
        n_trades = int((trade_changes > 0.5).sum())

        results[f"min_hold_{min_hold}d"] = {
            **metrics,
            "n_trades": n_trades,
            "min_hold_days": min_hold,
        }
        print(f"  Min hold {min_hold}d: CAGR={metrics['cagr']:.4f}, "
              f"Sharpe={metrics['sharpe']:.3f}, MaxDD={metrics['max_drawdown']:.4f}, "
              f"trades={n_trades}")

    # Baseline (no constraint)
    full_base = pd.Series(np.nan, index=focus.index, dtype=float)
    base_binary = base_position.map({2: 1.0, 1: 0.75, 0: 0.0})
    full_base.loc[base_binary.index] = base_binary.values
    _, base_metrics = run_single_asset_backtest(focus, full_base)
    n_base_trades = int((base_binary.diff().abs() > 0.01).sum())
    results["no_constraint"] = {**base_metrics, "n_trades": n_base_trades, "min_hold_days": 0}
    print(f"  No constraint: CAGR={base_metrics['cagr']:.4f}, "
          f"Sharpe={base_metrics['sharpe']:.3f}, MaxDD={base_metrics['max_drawdown']:.4f}, "
          f"trades={n_base_trades}")

    return {"holding_period_results": results}


# ═══════════════════════════════════════════════════════════════════════════
# Experiment 4: Regime Model exploration
# ═══════════════════════════════════════════════════════════════════════════


def run_experiment_4_regime_exploration(frame: pd.DataFrame) -> dict[str, Any]:
    """Full XGBoost regime classification exploration.

    Tests all 4 position allocation strategies:
      - BYD 100%
      - BYD 75% + ETF 25%
      - BYD 50% + ETF 50%
      - ETF 100%
    """
    print("\n" + "=" * 70)
    print("Experiment 4: Regime Model Exploration (XGBoost)")
    print("=" * 70)

    labeled = build_regime_labels(frame)
    X_all, y_all = build_feature_matrix(labeled)

    # Train on all data before 2022, test on 2022-2026
    train_mask = (X_all.index >= "2012-01-01") & (X_all.index <= "2021-12-31")
    test_mask = (X_all.index >= "2022-01-01") & (X_all.index <= "2026-08-03")

    X_train = X_all.loc[train_mask]
    y_train = y_all.loc[train_mask]
    X_test = X_all.loc[test_mask]

    if len(X_train) < 100 or len(X_test) < 30:
        print("  Insufficient data for training")
        return {"error": "insufficient data"}

    model, proba, preds = train_regime_classifier(X_train, y_train, X_test)

    # Feature importance
    importance = dict(zip(FEATURE_COLUMNS, model.feature_importances_))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    print("  Top 10 feature importance:")
    for feat, imp in sorted_imp[:10]:
        print(f"    {feat}: {imp:.4f}")

    # Class distribution
    _, counts = np.unique(preds, return_counts=True)
    regime_dist = dict(zip(["bear", "neutral", "bull"], counts))
    print(f"  Predicted regime distribution: {regime_dist}")

    # Test each allocation strategy
    focus_mask = (frame.index >= "2022-01-01") & (frame.index <= "2026-08-03")
    focus = frame.loc[focus_mask].copy()

    allocation_results = {}
    for alloc_name in POSITION_ALLOCATIONS:
        byd_pos, etf_pos = regime_to_dual_position(preds)

        # Override BYD position based on allocation strategy
        weights = POSITION_ALLOCATIONS[alloc_name]
        if weights["BYD"] == 1.0 and weights["ETF"] == 0.0:
            # Pure BYD — use regime-gated BYD weight
            adjusted_byd = np.where(preds == 2, 1.0, np.where(preds == 1, 0.7, 0.0))
            byd_pos_s = pd.Series(adjusted_byd, index=X_test.index, dtype=float)
        elif weights["BYD"] == 0.0 and weights["ETF"] == 1.0:
            # Pure ETF — use inverse regime (buy ETF in bear)
            pd.Series(np.where(preds == 0, 1.0, np.where(preds == 1, 0.5, 0.0)), index=X_test.index, dtype=float)
            byd_pos_s = pd.Series(0.0, index=X_test.index, dtype=float)
        elif weights["BYD"] == 0.75:
            byd_pos_s = pd.Series(np.where(preds == 2, 1.0, np.where(preds == 1, 0.75, 0.0)), index=X_test.index, dtype=float)
        elif weights["BYD"] == 0.50:
            byd_pos_s = pd.Series(np.where(preds == 2, 0.75, np.where(preds == 1, 0.5, 0.0)), index=X_test.index, dtype=float)
        else:
            byd_pos_s = pd.Series(byd_pos, index=X_test.index, dtype=float)

        full_pos = pd.Series(np.nan, index=focus.index, dtype=float)
        full_pos.loc[byd_pos_s.index] = byd_pos_s.values

        _, metrics = run_single_asset_backtest(focus, full_pos)
        allocation_results[alloc_name] = metrics
        print(f"  {alloc_name}: CAGR={metrics['cagr']:.4f}, "
              f"Sharpe={metrics['sharpe']:.3f}, MaxDD={metrics['max_drawdown']:.4f}")

    # Train on fuller dataset for better generalization
    # Second pass: use 2012-2024 training for 2025-2026 test
    print("\n  Extended training (2012-2024 → 2025-2026):")
    train_mask2 = (X_all.index >= "2012-01-01") & (X_all.index <= "2024-12-31")
    test_mask2 = (X_all.index >= "2025-01-01") & (X_all.index <= "2026-08-03")

    X_train2 = X_all.loc[train_mask2]
    y_train2 = y_all.loc[train_mask2]
    X_test2 = X_all.loc[test_mask2]

    if len(X_train2) >= 100 and len(X_test2) >= 30:
        model2, proba2, preds2 = train_regime_classifier(X_train2, y_train2, X_test2)
        byd_pos2, etf_pos2 = regime_to_dual_position(preds2)
        byd_pos_s2 = pd.Series(byd_pos2, index=X_test2.index, dtype=float)

        full_pos2 = pd.Series(np.nan, index=frame.index, dtype=float)
        full_pos2.loc[byd_pos_s2.index] = byd_pos_s2.values
        _, ext_metrics = run_single_asset_backtest(frame, full_pos2)

        _, counts2 = np.unique(preds2, return_counts=True)
        ext_dist = dict(zip(["bear", "neutral", "bull"], counts2))

        allocation_results["extended_2025_2026"] = {
            **ext_metrics,
            "regime_distribution": ext_dist,
        }
        print(f"    2025-2026: CAGR={ext_metrics['cagr']:.4f}, "
              f"Sharpe={ext_metrics['sharpe']:.3f}, regime_dist={ext_dist}")
    else:
        allocation_results["extended_2025_2026"] = {"error": "insufficient data"}

    return {
        "feature_importance": sorted_imp,
        "regime_distribution": regime_dist,
        "allocation_results": allocation_results,
        "model_params": model.get_params(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Main orchestrator
# ═══════════════════════════════════════════════════════════════════════════


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_BASE / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # —— Load data ————————————————————————————————————————————————————
    print("\nLoading canonical BYD data...")
    if not CANONICAL_ROOT.exists():
        print(f"  ERROR: Canonical data not found at {CANONICAL_ROOT}")
        print("  Please extract byd_canonical_v1_snapshot.tar.xz first.")
        return

    try:
        canonical = load_canonical_snapshot(CANONICAL_ROOT)
        print(f"  Loaded: {len(canonical.adjusted)} adjusted bars, "
              f"cutoff={canonical.manifest.get('cutoff')}")
    except Exception as e:
        print(f"  ERROR loading canonical snapshot: {e}")
        return

    dataset = build_research_dataset(canonical.adjusted, canonical.sessions)
    print(f"  Research dataset: {len(dataset)} rows, {len(dataset.columns)} columns")

    # —— Build enhanced features ——————————————————————————————————————
    print("\nBuilding enhanced features...")
    enhanced = build_enhanced_features(dataset)
    labeled = build_regime_labels(enhanced)
    print(f"  Features: {len(FEATURE_COLUMNS)} columns")
    print(f"  Regime labels: bear={(labeled['regime_label'] == 0).sum()}, "
          f"neutral={(labeled['regime_label'] == 1).sum()}, "
          f"bull={(labeled['regime_label'] == 2).sum()}")

    # —— Save dataset snapshot ————————————————————————————————————————
    output_dir / "enhanced_dataset.parquet"
    # Use CSV for portability; parquet is faster but optional
    labeled.to_csv(output_dir / "enhanced_dataset.csv", float_format="%.8f")
    print(f"  Saved enhanced dataset to {output_dir / 'enhanced_dataset.csv'}")

    # —— Run experiments ——————————————————————————————————————————————
    all_results: dict[str, Any] = {
        "metadata": {
            "experiment_id": f"byd_v2_regime_{timestamp}",
            "issue": "https://github.com/liuh886/alpha_engine/issues/716",
            "timestamp_utc": timestamp,
            "canonical_cutoff": CANONICAL_ROOT,
            "feature_columns": FEATURE_COLUMNS,
            "regime_thresholds": REGIME_THRESHOLDS,
            "regime_label_horizon": REGIME_LABEL_HORIZON,
        },
    }

    # Experiment 1
    try:
        all_results["experiment_1_walk_forward"] = run_experiment_1_walk_forward(enhanced)
    except Exception as e:
        print(f"  Experiment 1 FAILED: {e}")
        all_results["experiment_1_walk_forward"] = {"error": str(e)}

    # Experiment 2
    try:
        all_results["experiment_2_benchmarks"] = run_experiment_2_benchmarks(enhanced)
    except Exception as e:
        print(f"  Experiment 2 FAILED: {e}")
        all_results["experiment_2_benchmarks"] = {"error": str(e)}

    # Experiment 3
    try:
        all_results["experiment_3_holding_inertia"] = run_experiment_3_holding_inertia(enhanced)
    except Exception as e:
        print(f"  Experiment 3 FAILED: {e}")
        all_results["experiment_3_holding_inertia"] = {"error": str(e)}

    # Experiment 4
    try:
        all_results["experiment_4_regime_exploration"] = run_experiment_4_regime_exploration(enhanced)
    except Exception as e:
        print(f"  Experiment 4 FAILED: {e}")
        all_results["experiment_4_regime_exploration"] = {"error": str(e)}

    # —— Save results —————————————————————————————————————————————————
    results_path = output_dir / "experiment_results.json"

    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, pd.Timestamp):
                return str(obj)
            if isinstance(obj, Path):
                return str(obj)
            return super().default(obj)

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, cls=NpEncoder, indent=2, ensure_ascii=False)
    print(f"\nResults saved to: {results_path}")

    # —— Print final summary ——————————————————————————————————————————
    print("\n" + "=" * 70)
    print("Experiment Summary")
    print("=" * 70)
    for exp_name, exp_data in all_results.items():
        if exp_name == "metadata":
            continue
        status = "ERROR" if "error" in exp_data else "OK"
        print(f"  {exp_name}: {status}")

    print(f"\nAll outputs: {output_dir}")
    return all_results


if __name__ == "__main__":
    main()
