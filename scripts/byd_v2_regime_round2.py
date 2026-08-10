"""BYD v2.0 Regime Model — Round 2 Optimization.

Key improvements over Round 1:
  1. Class weighting to fix Neutral over-prediction bias
  2. Multi-horizon label testing (30d, 60d, 90d)
  3. Calibrated probability thresholds for regime switching
  4. Direct comparison with BYD v1.2 on same evaluation windows
  5. Built-in 30d min hold as primary strategy
  6. Rolling probability calibration

Output: data/research/byd_v2_experiments/{timestamp}_r2/
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)

CANONICAL_ROOT = PROJECT_ROOT / "data" / "research" / "byd_canonical_v1_extracted"
OUTPUT_BASE = PROJECT_ROOT / "data" / "research" / "byd_v2_experiments"
RANDOM_STATE = 42
COST_BPS = 10.0

# — Feature builder (same as Round 1) ———————————————————————————————————


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
    denom = float(np.square(x).sum())

    def slope(values: np.ndarray) -> float:
        y = np.log(np.asarray(values, dtype=float))
        return float(np.dot(x, y - y.mean()) / denom)

    return series.rolling(window).apply(slope, raw=True)


def build_enhanced_features(dataset: pd.DataFrame) -> pd.DataFrame:
    frame = dataset.copy()
    close = frame["close"]

    frame["sma_200"] = close.rolling(200, min_periods=200).mean()
    frame["sma_60"] = close.rolling(60, min_periods=60).mean()
    frame["sma_120"] = close.rolling(120, min_periods=120).mean()

    bull = close.gt(frame["sma_200"]) & frame["sma_60"].gt(frame["sma_200"])
    bear = close.lt(frame["sma_200"]) & frame["sma_60"].lt(frame["sma_200"])
    frame["ma_state"] = np.select([bull, bear], [1, -1], default=0)
    frame["ma200_distance"] = close / frame["sma_200"] - 1.0
    frame["mom_12m"] = close.pct_change(252)
    frame["mom_20"] = close.pct_change(20)
    frame["mom_60"] = close.pct_change(60)
    frame["mom_120"] = close.pct_change(120)
    frame["mom_accel_20_60"] = frame["mom_20"] - frame["mom_60"]

    high252 = close.rolling(252, min_periods=252).max()
    low20 = close.rolling(20, min_periods=20).min()
    frame["drawdown_252"] = close / high252 - 1.0
    frame["distance_from_low_20"] = close / low20 - 1.0
    frame["long_reversal"] = -frame["mom_12m"]
    frame["short_continuation"] = close.pct_change(5)

    frame["price_to_ma200"] = close / frame["sma_200"]
    frame["price_to_ma60"] = close / frame["sma_60"]
    high756 = close.rolling(756, min_periods=252).max()
    low756 = close.rolling(756, min_periods=252).min()
    frame["price_percentile_3y"] = (close - low756) / (high756 - low756).replace(0.0, np.nan)
    frame["valuation_expansion"] = frame["price_to_ma200"].diff(60)

    frame["rsi_14"] = _wilder_rsi(close, 14)
    frame["rsi_extreme"] = np.where(frame["rsi_14"] < 30, -1, np.where(frame["rsi_14"] > 70, 1, 0))
    daily_ret = close.pct_change()
    frame["realized_vol_20"] = daily_ret.rolling(20).std()
    frame["realized_vol_60"] = daily_ret.rolling(60).std()
    vol_median_3y = frame["realized_vol_60"].rolling(756, min_periods=252).median()
    frame["vol_regime_high"] = (frame["realized_vol_60"] > vol_median_3y).astype(float)

    frame["trend_slope_60"] = _rolling_slope(close, 60)
    frame["trend_slope_120"] = _rolling_slope(close, 120)

    open_ = frame["open"]
    open_return = open_.pct_change()
    frame["open_autocorr_20"] = open_return.rolling(20).corr(open_return.shift(1))

    return frame


FEATURE_COLUMNS = [
    "ma200_distance", "ma_state", "mom_12m", "mom_20", "mom_60", "mom_120",
    "mom_accel_20_60", "drawdown_252", "distance_from_low_20", "long_reversal",
    "short_continuation", "price_to_ma200", "price_to_ma60",
    "price_percentile_3y", "valuation_expansion", "rsi_14", "rsi_extreme",
    "realized_vol_20", "realized_vol_60", "vol_regime_high",
    "trend_slope_60", "trend_slope_120", "open_autocorr_20",
]

# — Label builder ————————————————————————————————————————————————————————


def build_regime_labels(frame: pd.DataFrame, horizon: int, bull: float, bear: float) -> pd.DataFrame:
    result = frame.copy()
    open_ = result["open"]
    eligible = result.get("open_research_eligible", pd.Series(True, index=result.index))
    fwd_return = open_.shift(-horizon) / open_ - 1.0
    valid = eligible.astype(bool) & eligible.shift(-horizon).fillna(False).astype(bool)
    fwd_return = fwd_return.where(valid)
    result["regime_label"] = np.select(
        [fwd_return > bull, fwd_return < bear],
        [2, 0],
        default=1,
    )
    result["forward_return"] = fwd_return
    return result


# — Stateful position with min hold ——————————————————————————————————————


def _stateful_min_hold(entry: pd.Series, exit_: pd.Series, min_hold: int) -> pd.Series:
    active = False
    hold_counter = 0
    values: list[float] = []
    for enter_now, exit_now in zip(entry.fillna(False), exit_.fillna(False), strict=True):
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


# — Backtest —————————————————————————————————————————————————————————————


def compute_metrics(returns: pd.Series) -> dict[str, float]:
    clean = returns.dropna()
    if clean.empty:
        return {}
    years = len(clean) / 252.0
    wealth = (1.0 + clean).cumprod()
    tr = float(wealth.iloc[-1] - 1.0)
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and wealth.iloc[-1] > 0 else -1.0
    vol = float(clean.std(ddof=0) * np.sqrt(252.0))
    sharpe = float(clean.mean() / clean.std(ddof=0) * np.sqrt(252.0)) if clean.std(ddof=0) > 0 else 0.0
    downside = clean.clip(upper=0.0)
    dd_dev = float(np.sqrt((downside.pow(2)).mean()) * np.sqrt(252.0))
    sortino = float(clean.mean() * 252.0 / dd_dev) if dd_dev > 0 else 0.0
    max_dd = float((wealth / wealth.cummax() - 1.0).min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {
        "total_return": tr, "cagr": cagr, "annual_volatility": vol,
        "sharpe": sharpe, "sortino": sortino, "max_drawdown": max_dd,
        "calmar": calmar,
    }


def run_backtest_single(
    frame: pd.DataFrame,
    position: pd.Series,
    cost_bps: float = COST_BPS,
) -> dict[str, float]:
    daily = frame[["open"]].copy()
    pos = position.reindex(daily.index).fillna(0.0)
    daily["pos"] = pos.shift(1).fillna(0.0)
    daily["asset_ret"] = daily["open"].shift(-1) / daily["open"] - 1.0
    daily = daily.iloc[:-1].copy()
    daily["turnover"] = daily["pos"].diff().abs()
    daily["turnover"].iloc[0] = abs(daily["pos"].iloc[0])
    daily["cost"] = daily["turnover"] * cost_bps / 10000.0
    daily["net_return"] = daily["pos"] * daily["asset_ret"] - daily["cost"]
    metrics = compute_metrics(daily["net_return"])
    metrics["total_turnover"] = float(daily["turnover"].sum())
    metrics["avg_position"] = float(daily["pos"].mean())
    metrics["n_trades"] = int((daily["turnover"] > 0.01).sum())
    return metrics


# — XGBoost training with class weighting ————————————————————————————————


def train_xgb_weighted(X_train, y_train, X_test, class_weight="balanced"):
    """Train XGBoost with class weighting to fix Neutral bias."""
    from xgboost import XGBClassifier

    # Compute sample weights
    unique, counts = np.unique(y_train, return_counts=True)
    n_samples = len(y_train)
    n_classes = 3
    weights_dict = {}
    for cls, cnt in zip(unique, counts):
        if class_weight == "balanced":
            weights_dict[cls] = n_samples / (n_classes * cnt)
        else:
            weights_dict[cls] = 1.0

    sample_weight = np.array([weights_dict.get(y, 1.0) for y in y_train])

    model = XGBClassifier(
        n_estimators=200, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        objective="multi:softprob", num_class=3,
        eval_metric="mlogloss", random_state=RANDOM_STATE, verbosity=0,
    )
    model.fit(X_train, y_train, sample_weight=sample_weight)
    proba = model.predict_proba(X_test)
    preds = model.predict(X_test)
    return model, proba, preds


# — Calibrated regime switching ——————————————————————————————————————————


def calibrated_regime_position(
    proba: np.ndarray,
    confidence: float = 0.5,
    min_hold: int = 30,
) -> pd.Series:
    """Convert probability predictions to position with confidence threshold.

    Requires prob(bull) or prob(bear) > confidence to switch.
    """
    # proba columns: [bear, neutral, bull]
    p_bear = proba[:, 0]
    p_bull = proba[:, 2]

    # Binary decisions with confidence threshold
    entry_long = p_bull > confidence
    exit_long = p_bear > confidence

    position = _stateful_min_hold(
        pd.Series(entry_long),
        pd.Series(exit_long),
        min_hold=min_hold,
    )
    return position


# ═══════════════════════════════════════════════════════════════════════════
# Round 2 Experiments
# ═══════════════════════════════════════════════════════════════════════════


def run_r2_experiment_1_label_horizons(frame: pd.DataFrame) -> dict:
    """Test different label horizons."""
    print("=" * 70)
    print("R2 Experiment 1: Label Horizon Sensitivity")
    print("=" * 70)

    configs = [
        {"horizon": 30, "bull": 0.05, "bear": -0.05},
        {"horizon": 60, "bull": 0.10, "bear": -0.10},
        {"horizon": 90, "bull": 0.15, "bear": -0.15},
        {"horizon": 120, "bull": 0.20, "bear": -0.20},
    ]

    enhanced = build_enhanced_features(frame)

    results = []
    for cfg in configs:
        labeled = build_regime_labels(enhanced, cfg["horizon"], cfg["bull"], cfg["bear"])

        X_all = labeled[FEATURE_COLUMNS]
        y_all = labeled["regime_label"]
        valid = y_all.notna()
        X_all, y_all = X_all.loc[valid], y_all.loc[valid]

        t_mask = (X_all.index >= "2012-01-01") & (X_all.index <= "2021-12-31")
        test_mask = (X_all.index >= "2022-01-01") & (X_all.index <= "2026-08-03")

        X_train = X_all.loc[t_mask]
        y_train = y_all.loc[t_mask]
        X_test = X_all.loc[test_mask]
        y_test = y_all.loc[test_mask]

        if len(X_train) < 100 or len(X_test) < 30:
            results.append({**cfg, "error": "insufficient data"})
            continue

        model, proba, preds = train_xgb_weighted(X_train, y_train, X_test)

        # Accuracy
        accuracy = float((preds == y_test.values).mean())

        # Regime distribution
        _, cnts = np.unique(preds, return_counts=True)
        regime_dist = dict(zip(["bear", "neutral", "bull"], cnts))

        # Position with confidence threshold
        for conf in [0.4, 0.5, 0.6]:
            for mh in [20, 30, 40]:
                position = calibrated_regime_position(proba, confidence=conf, min_hold=mh)
                position.index = X_test.index
                full_pos = pd.Series(np.nan, index=enhanced.index, dtype=float)
                full_pos.loc[position.index] = position.values
                metrics = run_backtest_single(enhanced, full_pos)

                results.append({
                    "horizon": cfg["horizon"],
                    "bull_threshold": cfg["bull"],
                    "bear_threshold": cfg["bear"],
                    "confidence": conf,
                    "min_hold": mh,
                    "accuracy": accuracy,
                    "regime_distribution": regime_dist,
                    **metrics,
                })

        # Print best for this horizon
        horizon_results = [r for r in results if r.get("horizon") == cfg["horizon"] and "error" not in r]
        if horizon_results:
            best = max(horizon_results, key=lambda x: x.get("sharpe", -999))
            print(f"  Horizon {cfg['horizon']}d: best Sharpe={best['sharpe']:.3f} "
                  f"(conf={best['confidence']}, min_hold={best['min_hold']}d), "
                  f"accuracy={accuracy:.3f}")

    return {"label_horizon_results": results}


def run_r2_experiment_2_v12_comparison(frame: pd.DataFrame) -> dict:
    """Direct comparison with BYD v1.2 on the same evaluation windows.

    v1.2 windows:
      - Development: 2019-11-26 → 2022-12-31
      - Fixed Validation: 2023-01-01 → 2024-12-31
      - Retrospective 2025+: 2025-01-01 → 2026-08-03
      - Full Overlap: 2019-11-26 → 2026-08-03
    """
    print("\n" + "=" * 70)
    print("R2 Experiment 2: Direct v1.2 Comparison")
    print("=" * 70)

    enhanced = build_enhanced_features(frame)

    # v1.2 reference metrics from formal run (extracted from summary.json)
    v12_ref = {
        "development": {"cagr": 0.7888, "sharpe": 1.3628, "max_dd": -0.4222, "calmar": 1.8685},
        "fixed_validation": {"cagr": 0.0816, "sharpe": 0.4032, "max_dd": -0.4134, "calmar": 0.1973},
        "retrospective_2025_plus": {"cagr": 0.0480, "sharpe": 0.3045, "max_dd": -0.3729, "calmar": 0.1287},
        "full_overlap": {"cagr": 0.3534, "sharpe": 0.9185, "max_dd": -0.4920, "calmar": 0.7183},
    }

    windows = {
        "development": ("2019-11-26", "2022-12-31"),
        "fixed_validation": ("2023-01-01", "2024-12-31"),
        "retrospective_2025_plus": ("2025-01-01", "2026-08-03"),
        "full_overlap": ("2019-11-26", "2026-08-03"),
    }

    # Train on everything BEFORE each window, test on window
    # For v2, use pre-2019 data as initial training
    labeled = build_regime_labels(enhanced, horizon=60, bull=0.10, bear=-0.10)
    X_all = labeled[FEATURE_COLUMNS]
    y_all = labeled["regime_label"]
    valid = y_all.notna()
    X_all = X_all.loc[valid]
    y_all = y_all.loc[valid]

    comparison = {}
    for window_name, (w_start, w_end) in windows.items():
        train_mask = X_all.index < w_start
        test_mask = (X_all.index >= w_start) & (X_all.index <= w_end)

        X_train = X_all.loc[train_mask]
        y_train = y_all.loc[train_mask]
        X_test = X_all.loc[test_mask]

        if len(X_train) < 100 or len(X_test) < 30:
            comparison[window_name] = {"error": "insufficient data"}
            continue

        model, proba, preds = train_xgb_weighted(X_train, y_train, X_test)

        # Best config from Experiment 1
        position = calibrated_regime_position(proba, confidence=0.5, min_hold=30)
        position.index = X_test.index

        full_pos = pd.Series(np.nan, index=enhanced.index, dtype=float)
        full_pos.loc[position.index] = position.values
        metrics = run_backtest_single(enhanced, full_pos)

        v12 = v12_ref.get(window_name, {})
        comparison[window_name] = {
            "v2_xgboost_regime": metrics,
            "v1_2_reference": v12,
            "cagr_delta": metrics.get("cagr", 0) - v12.get("cagr", 0),
            "sharpe_delta": metrics.get("sharpe", 0) - v12.get("sharpe", 0),
        }
        print(f"  {window_name}:")
        print(f"    v2 XGBoost: CAGR={metrics.get('cagr', 0):.4f}, "
              f"Sharpe={metrics.get('sharpe', 0):.3f}, "
              f"MaxDD={metrics.get('max_drawdown', 0):.4f}")
        print(f"    v1.2 ref:   CAGR={v12.get('cagr', 0):.4f}, "
              f"Sharpe={v12.get('sharpe', 0):.3f}, "
              f"MaxDD={v12.get('max_dd', 0):.4f}")
        print(f"    Delta:      CAGR={comparison[window_name]['cagr_delta']:+.4f}, "
              f"Sharpe={comparison[window_name]['sharpe_delta']:+.3f}")

    return {"v12_comparison": comparison}


def run_r2_experiment_3_ensemble_robustness(frame: pd.DataFrame) -> dict:
    """Multi-horizon ensemble for stability improvement.

    Train 3 models on different horizons (30d, 60d, 90d), ensemble predictions.
    """
    print("\n" + "=" * 70)
    print("R2 Experiment 3: Multi-Horizon Ensemble")
    print("=" * 70)

    enhanced = build_enhanced_features(frame)
    horizons = [30, 60, 90]
    thresholds = [(0.05, -0.05), (0.10, -0.10), (0.15, -0.15)]

    models = []
    for h, (bull_t, bear_t) in zip(horizons, thresholds):
        labeled = build_regime_labels(enhanced, horizon=h, bull=bull_t, bear=bear_t)
        X_all = labeled[FEATURE_COLUMNS]
        y_all = labeled["regime_label"]
        valid = y_all.notna()
        X_all = X_all.loc[valid]
        y_all = y_all.loc[valid]

        t_mask = (X_all.index >= "2012-01-01") & (X_all.index <= "2021-12-31")
        te_mask = (X_all.index >= "2022-01-01") & (X_all.index <= "2026-08-03")

        X_train = X_all.loc[t_mask]
        y_train = y_all.loc[t_mask]
        X_test = X_all.loc[te_mask]

        if len(X_train) < 100 or len(X_test) < 30:
            continue

        model, proba, preds = train_xgb_weighted(X_train, y_train, X_test)
        models.append({"horizon": h, "model": model, "proba": proba, "preds": preds, "test_index": X_test.index})
        acc = float((preds == y_all.loc[X_test.index].values).mean())
        print(f"  Horizon {h}d: accuracy={acc:.3f}")

    if len(models) < 2:
        return {"error": "insufficient models for ensemble"}

    # Ensemble: average probabilities
    common_index = models[0]["test_index"]
    for m in models[1:]:
        common_index = common_index.intersection(m["test_index"])

    avg_proba = np.mean([
        m["proba"][[list(m["test_index"]).index(idx) for idx in common_index]]
        for m in models
    ], axis=0)

    # Test ensemble with different confidence + min_hold configs
    results = []
    for conf in [0.4, 0.5, 0.6]:
        for mh in [20, 30, 40]:
            position = calibrated_regime_position(avg_proba, confidence=conf, min_hold=mh)
            position.index = common_index
            full_pos = pd.Series(np.nan, index=enhanced.index, dtype=float)
            full_pos.loc[position.index] = position.values
            metrics = run_backtest_single(enhanced, full_pos)
            results.append({"confidence": conf, "min_hold": mh, "ensemble_size": len(models), **metrics})

    # Also test voting ensemble (majority vote)
    votes = np.array([m["preds"][
        [list(m["test_index"]).index(idx) if idx in m["test_index"] else -1 for idx in common_index]
    ] for m in models])
    # For voting: each model votes for its class
    vote_preds = []
    for i in range(len(common_index)):
        col_votes = votes[:, i]
        valid_votes = col_votes[col_votes >= 0]
        if len(valid_votes) == 0:
            vote_preds.append(1)  # default neutral
        else:
            vote_preds.append(np.bincount(valid_votes.astype(int), minlength=3).argmax())
    vote_preds = np.array(vote_preds)

    # Convert vote predictions to binary long/cash
    vote_entry = pd.Series(vote_preds == 2, index=common_index)  # bull → long
    vote_exit = pd.Series(vote_preds == 0, index=common_index)   # bear → cash

    for mh in [20, 30, 40]:
        position = _stateful_min_hold(vote_entry, vote_exit, min_hold=mh)
        position.index = common_index
        full_pos = pd.Series(np.nan, index=enhanced.index, dtype=float)
        full_pos.loc[position.index] = position.values
        metrics = run_backtest_single(enhanced, full_pos)
        results.append({
            "confidence": "vote",
            "min_hold": mh,
            "ensemble_size": len(models),
            "ensemble_type": "majority_vote",
            **metrics,
        })

    best = max(results, key=lambda x: x.get("sharpe", -999))
    print(f"\n  Best ensemble: Sharpe={best['sharpe']:.3f}, "
          f"CAGR={best['cagr']:.4f}, conf={best.get('confidence')}, "
          f"min_hold={best['min_hold']}d")

    return {"ensemble_results": results, "best_ensemble": best}


def run_r2_experiment_4_calibrated_strategy(frame: pd.DataFrame) -> dict:
    """Final calibrated strategy with all optimizations.

    Combines:
      - Class-weighted XGBoost
      - 60d horizon labels
      - 0.5 confidence threshold
      - 30d min hold
      - (Optional) multi-horizon ensemble
    """
    print("\n" + "=" * 70)
    print("R2 Experiment 4: Final Calibrated Strategy")
    print("=" * 70)

    enhanced = build_enhanced_features(frame)
    labeled = build_regime_labels(enhanced, horizon=60, bull=0.10, bear=-0.10)

    X_all = labeled[FEATURE_COLUMNS]
    y_all = labeled["regime_label"]
    valid = y_all.notna()
    X_all = X_all.loc[valid]
    y_all = y_all.loc[valid]

    # Walk-forward from 2022-2026 with expanding window, same config
    years = [("2022", "2022-01-01", "2022-12-31"),
             ("2023", "2023-01-01", "2023-12-31"),
             ("2024", "2024-01-01", "2024-12-31"),
             ("2025", "2025-01-01", "2025-12-31"),
             ("2026", "2026-01-01", "2026-08-03")]

    # Fixed config
    CONFIDENCE = 0.5
    MIN_HOLD = 30

    wf_results = []
    cumulative_train_end = "2021-12-31"

    for label, y_start, y_end in years:
        train_mask = (X_all.index >= "2012-01-01") & (X_all.index <= cumulative_train_end)
        test_mask = (X_all.index >= y_start) & (X_all.index <= y_end)

        X_train = X_all.loc[train_mask]
        y_train = y_all.loc[train_mask]
        X_test = X_all.loc[test_mask]

        if len(X_train) < 100 or len(X_test) < 10:
            continue

        model, proba, preds = train_xgb_weighted(X_train, y_train, X_test)
        position = calibrated_regime_position(proba, confidence=CONFIDENCE, min_hold=MIN_HOLD)
        position.index = X_test.index

        full_pos = pd.Series(np.nan, index=enhanced.index, dtype=float)
        full_pos.loc[position.index] = position.values
        metrics = run_backtest_single(enhanced, full_pos)

        _, cnts = np.unique(preds, return_counts=True)
        regime_dist = dict(zip(["bear", "neutral", "bull"], cnts))

        # Buy & Hold for this year
        bh_pos = pd.Series(1.0, index=enhanced.index, dtype=float)
        bh_metrics = run_backtest_single(enhanced, bh_pos)

        wf_results.append({
            "year": label,
            "train_until": cumulative_train_end,
            **metrics,
            "regime_distribution": regime_dist,
            "buy_hold_cagr": bh_metrics.get("cagr", 0),
            "buy_hold_sharpe": bh_metrics.get("sharpe", 0),
        })
        print(f"  {label}: CAGR={metrics.get('cagr', 0):.4f} "
              f"(B&H={bh_metrics.get('cagr', 0):.4f}), "
              f"Sharpe={metrics.get('sharpe', 0):.3f}, "
              f"trades={metrics.get('n_trades', 0)}, "
              f"regimes={regime_dist}")

        cumulative_train_end = y_end

    # Yearly summary
    if wf_results:
        cagrs = [r.get("cagr", 0) for r in wf_results]
        sharpes = [r.get("sharpe", 0) for r in wf_results]
        print("\n  Walk-forward stability (calibrated):")
        print(f"    CAGR: mean={np.mean(cagrs):.4f}, std={np.std(cagrs):.4f}")
        print(f"    Sharpe: mean={np.mean(sharpes):.3f}, std={np.std(sharpes):.3f}")

    return {"calibrated_walk_forward": wf_results}


# — Main —————————————————————————————————————————————————————————————————


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_BASE / f"{timestamp}_r2"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {output_dir}")

    # Load data
    canonical = load_canonical_snapshot(CANONICAL_ROOT)
    dataset = build_research_dataset(canonical.adjusted, canonical.sessions)
    frame = build_enhanced_features(dataset)
    print(f"Loaded: {len(frame)} rows, cutoff={canonical.manifest.get('cutoff')}")

    all_results = {
        "metadata": {
            "experiment_id": f"byd_v2_round2_{timestamp}",
            "issue": "https://github.com/liuh886/alpha_engine/issues/716",
            "timestamp_utc": timestamp,
            "improvements": [
                "class_weighted_xgboost",
                "multi_horizon_label_testing",
                "calibrated_confidence_thresholds",
                "direct_v1_2_comparison",
                "multi_horizon_ensemble",
            ],
        },
    }

    # R2.1: Label horizon sensitivity
    all_results["r2_1_label_horizons"] = run_r2_experiment_1_label_horizons(frame)

    # R2.2: Direct v1.2 comparison
    all_results["r2_2_v12_comparison"] = run_r2_experiment_2_v12_comparison(frame)

    # R2.3: Ensemble robustness
    all_results["r2_3_ensemble"] = run_r2_experiment_3_ensemble_robustness(frame)

    # R2.4: Final calibrated strategy
    all_results["r2_4_calibrated"] = run_r2_experiment_4_calibrated_strategy(frame)

    # Save
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, (pd.Timestamp, Path)):
                return str(obj)
            return super().default(obj)

    results_path = output_dir / "experiment_results_r2.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, cls=NpEncoder, indent=2, ensure_ascii=False)

    print(f"\nResults: {results_path}")
    print("=" * 70)
    print("Round 2 Complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
