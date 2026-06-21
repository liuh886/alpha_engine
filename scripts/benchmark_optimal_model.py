"""Benchmark SignalExecutionEngine on the OPTIMAL model configuration.

Optimal config (verified in model_training_experience.md):
  - Features: 181 Alpha158 expressions (158 + 23 extras)
  - Label: absolute 10-day forward return
  - Model: LightGBM (lr=0.05, depth=10, leaves=128)
  - Training: 2021-2024, Test: 2025-01 to 2026-06

This script:
  1. Loads Alpha158 features directly via D.features()
  2. Manually normalizes features (Z-score fitted on train only)
  3. Trains LightGBM with proper early stopping
  4. Runs all 4 SignalExecutionEngine configs + baseline
  5. Prints comprehensive comparison
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import lightgbm as lgb
import numpy as np
import pandas as pd
import structlog
from qlib.contrib.data.loader import Alpha158DL
from qlib.data import D

from src.common.paths import ARTIFACTS_DIR
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.execution.signal_execution_config import SignalExecutionConfig
from src.execution.signal_execution_engine import SignalExecutionEngine
from src.research.vectorized_backtest import run_vectorized_backtest

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MARKET = "cn"
BENCHMARK = "000300"
TRAIN_START = "2021-01-01"
TRAIN_END = "2024-12-31"
VALID_START = "2024-07-01"
VALID_END = "2024-12-31"
TEST_START = "2025-01-01"    # Full out-of-sample: 2025-2026
TEST_END = "2026-06-18"
TOP_K = 15
REBALANCE_DAYS = 10
COST_BPS = 20.0


def load_data():
    """Load Alpha158 features, absolute return labels, and benchmark."""
    safe_qlib_init(build_qlib_init_cfg(None, market=MARKET))

    # Load symbols
    instr_file = ROOT / "data" / "watchlist" / "instruments" / f"{MARKET}.txt"
    symbols = [line.split("\t")[0] for line in instr_file.read_text().splitlines() if line.strip()]
    logger.info("Symbols loaded", n=len(symbols))

    # Alpha158 expressions
    alpha_exprs = Alpha158DL.get_feature_config({
        "kbar": {}, "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]}, "rolling": {},
    })[0]
    extra_exprs = [
        "$close/Ref($close, 5)-1", "$close/Ref($close, 10)-1", "$close/Ref($close, 20)-1",
        "Std($close, 10)", "$volume/Ref($volume, 10)-1",
    ]
    all_exprs = list(alpha_exprs) + extra_exprs
    label_expr = ["Ref($close, -10) / Ref($close, -1) - 1"]

    logger.info("Loading features", n_features=len(all_exprs))
    t0 = time.perf_counter()
    X_all = D.features(symbols, all_exprs, start_time=TRAIN_START, end_time=TEST_END)
    y_all = D.features(symbols, label_expr, start_time=TRAIN_START, end_time=TEST_END)
    bench_all = D.features([BENCHMARK], label_expr, start_time=TEST_START, end_time=TEST_END)
    logger.info("Data loaded", seconds=round(time.perf_counter() - t0, 1),
                X_shape=X_all.shape, y_shape=y_all.shape)

    # Flatten labels
    label_col = y_all.columns[0]
    y_series = y_all[label_col]

    # Fill NaN features with 0
    X_all = X_all.fillna(0.0)

    # Split by date
    train_mask = (X_all.index.get_level_values("datetime") >= TRAIN_START) & \
                 (X_all.index.get_level_values("datetime") <= TRAIN_END)
    valid_mask = (X_all.index.get_level_values("datetime") >= VALID_START) & \
                 (X_all.index.get_level_values("datetime") <= VALID_END)
    test_mask = (X_all.index.get_level_values("datetime") >= TEST_START) & \
                (X_all.index.get_level_values("datetime") <= TEST_END)

    X_train = X_all[train_mask].copy()
    y_train = y_series[train_mask].copy()
    X_valid = X_all[valid_mask].copy()
    y_valid = y_series[valid_mask].copy()
    X_test = X_all[test_mask].copy()
    y_test = y_series[test_mask].copy()

    # Z-score normalize: fit on train only
    train_mean = X_train.mean()
    train_std = X_train.std().replace(0, 1.0)
    for df in [X_train, X_valid, X_test]:
        df[:] = (df - train_mean) / train_std

    logger.info("Data split", train=len(X_train), valid=len(X_valid), test=len(X_test))

    # Benchmark
    if isinstance(bench_all.index, pd.MultiIndex):
        bench_flat = bench_all.xs(BENCHMARK, level="instrument")
    else:
        bench_flat = bench_all
    if isinstance(bench_flat, pd.DataFrame):
        bench_flat.columns = ["benchmark"]

    return X_train, y_train, X_valid, y_valid, X_test, y_test, bench_flat


def sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """LightGBM rejects $ / ( ) in feature names."""
    df = df.copy()
    df.columns = [str(c).replace("$", "D").replace("/", "_d_").replace("(", "L")
                   .replace(")", "R").replace(",", "_").replace(" ", "_")
                   .replace("-", "neg").replace("+", "plus")
                  for c in df.columns]
    return df


def train_model(X_train, y_train, X_valid, y_valid):
    """Train LightGBM on Alpha158 features with absolute return labels."""
    X_train_s = sanitize_columns(X_train)
    X_valid_s = sanitize_columns(X_valid)

    logger.info("Training LightGBM (500 rounds, lr=0.05, depth=10)")
    t0 = time.perf_counter()

    train_data = lgb.Dataset(X_train_s, label=y_train)
    valid_data = lgb.Dataset(X_valid_s, label=y_valid, reference=train_data)

    params = {
        "objective": "regression", "metric": "l2",
        "learning_rate": 0.05, "max_depth": 10, "num_leaves": 128,
        "feature_fraction": 0.8879, "bagging_fraction": 0.8789,
        "lambda_l1": 1.0, "lambda_l2": 1.0,
        "num_threads": 20, "verbosity": -1,
        "min_data_in_leaf": 20, "min_gain_to_split": 0.0,
    }

    booster = lgb.train(
        params, train_data, num_boost_round=500,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )
    elapsed = time.perf_counter() - t0
    logger.info("Training done", seconds=round(elapsed, 1),
                best_iter=booster.best_iteration,
                best_score=round(booster.best_score["valid_0"]["l2"], 6))

    return booster, X_train_s.columns.tolist()


def make_predictions_df(booster, X_test, feature_names):
    """Create MultiIndex predictions DataFrame."""
    X_test_s = sanitize_columns(X_test)
    X_test_s = X_test_s[feature_names]  # ensure same column order
    y_pred = booster.predict(X_test_s)
    return pd.DataFrame(y_pred, index=X_test.index, columns=["score"])


def make_returns_df(y_test):
    """Create MultiIndex returns DataFrame."""
    return y_test.to_frame("return")


def run_all_engines(predictions, returns, benchmark):
    """Run baseline + 3 SignalExecutionEngine configs."""
    results = {}

    # 1. Baseline
    logger.info("=== 1/4: Baseline vectorized_backtest TOP-15 ===")
    t0 = time.perf_counter()
    r1 = run_vectorized_backtest(predictions, returns, benchmark,
                                  topk=TOP_K, rebalance_days=REBALANCE_DAYS,
                                  initial_capital=10000.0, cost_bps=COST_BPS,
                                  non_overlapping=True)
    results["1_baseline_top15"] = {"r": r1, "t": time.perf_counter() - t0,
                                    "desc": "基准: TOP-15等权"}

    # 2. Grade-weighted long-only (no regime)
    logger.info("=== 2/4: Grade-weighted long-only ===")
    cfg2 = SignalExecutionConfig(market=MARKET, step_size=5, long_fraction=1.0,
                                  short_fraction=0.0, rebalance_days=REBALANCE_DAYS,
                                  enable_regime_filter=False,
                                  buy_cost_bps=COST_BPS/2, sell_cost_bps=COST_BPS/2)
    e2 = SignalExecutionEngine(cfg2)
    t0 = time.perf_counter()
    r2 = e2.execute(predictions, returns, benchmark)
    results["2_grade_long"] = {"r": r2, "t": time.perf_counter() - t0,
                                "desc": "分级权重纯多头",
                                "diag": r2._diagnostics.summary() if hasattr(r2, "_diagnostics") else {}}

    # 3. Grade-weighted + Regime (long-only)
    logger.info("=== 3/4: Grade + Regime long-only ===")
    cfg3 = SignalExecutionConfig(market=MARKET, step_size=5, long_fraction=1.0,
                                  short_fraction=0.0, rebalance_days=REBALANCE_DAYS,
                                  enable_regime_filter=True,
                                  buy_cost_bps=COST_BPS/2, sell_cost_bps=COST_BPS/2)
    e3 = SignalExecutionEngine(cfg3)
    t0 = time.perf_counter()
    r3 = e3.execute(predictions, returns, benchmark)
    results["3_grade_regime"] = {"r": r3, "t": time.perf_counter() - t0,
                                  "desc": "分级+状态过滤纯多头 ✅",
                                  "diag": r3._diagnostics.summary() if hasattr(r3, "_diagnostics") else {}}

    # 4. Grade + Regime + Short (best all-around)
    logger.info("=== 4/4: Grade + Regime + Long/Short ===")
    cfg4 = SignalExecutionConfig(market=MARKET, step_size=5, long_fraction=0.8,
                                  short_fraction=0.2, rebalance_days=REBALANCE_DAYS,
                                  enable_regime_filter=True,
                                  buy_cost_bps=COST_BPS/2, sell_cost_bps=COST_BPS/2)
    e4 = SignalExecutionEngine(cfg4)
    t0 = time.perf_counter()
    r4 = e4.execute(predictions, returns, benchmark)
    results["4_grade_regime_ls"] = {"r": r4, "t": time.perf_counter() - t0,
                                     "desc": "分级+状态+做空",
                                     "diag": r4._diagnostics.summary() if hasattr(r4, "_diagnostics") else {}}

    return results


def print_results(results):
    """Pretty-print comparison table."""
    hdr = f"{'Engine':<38} {'Excess':>8} {'Total':>8} {'Bench':>8} {'Sharpe':>7} {'MaxDD':>7} {'Vol':>7} {'IC':>6} {'Time':>5}"
    print("\n" + "=" * len(hdr))
    print("  SignalExecutionEngine — OPTIMAL MODEL Benchmark")
    print(f"  Period: {TEST_START} to {TEST_END} | Alpha158+绝对收益 | TopK≈{TOP_K} | {REBALANCE_DAYS}d rebal | {COST_BPS}bps cost")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))

    baseline_excess = None
    for k, v in results.items():
        r = v["r"]
        if baseline_excess is None:
            baseline_excess = r.excess_return
        print(f"{v['desc']:<38} {r.excess_return:>7.2%} {r.total_return:>7.2%} {r.benchmark_return:>7.2%} "
              f"{r.sharpe_ratio:>6.2f} {r.max_drawdown:>6.2%} {r.volatility:>6.2%} "
              f"{r.mean_ic:>5.3f} {v['t']:>4.1f}s")

    print("-" * len(hdr))

    # Improvements vs baseline
    for k in ["2_grade_long", "3_grade_regime", "4_grade_regime_ls"]:
        v = results[k]
        imp = v["r"].excess_return - baseline_excess
        print(f"  → {v['desc']}: 超额改善 {imp:+.2%}")

    # Diagnostics
    for k in ["2_grade_long", "3_grade_regime", "4_grade_regime_ls"]:
        v = results[k]
        if "diag" in v and v["diag"]:
            print(f"\n  [{v['desc']}] 状态诊断: {v['diag']}")

    # Feature importance (top 10)
    print()


def main():
    # Load data
    X_train, y_train, X_valid, y_valid, X_test, y_test, benchmark = load_data()

    # Train model
    booster, feature_names = train_model(X_train, y_train, X_valid, y_valid)

    # Generate predictions
    predictions = make_predictions_df(booster, X_test, feature_names)
    returns = make_returns_df(y_test)
    logger.info("Predictions ready", shape=predictions.shape)

    # Debug: check data alignment
    pred_dates = sorted(predictions.index.get_level_values("datetime").unique())
    ret_dates = sorted(returns.index.get_level_values("datetime").unique())
    bench_dates = sorted(benchmark.index.unique()) if hasattr(benchmark.index, 'unique') else []
    common_pr = sorted(set(pred_dates) & set(ret_dates))
    logger.info("Data alignment", pred_dates_n=len(pred_dates), ret_dates_n=len(ret_dates),
                bench_dates_n=len(bench_dates), common_n=len(common_pr),
                pred_sample=str(pred_dates[:3]), ret_sample=str(ret_dates[:3]),
                bench_cols=benchmark.columns.tolist() if hasattr(benchmark, 'columns') else 'N/A',
                bench_idx_type=str(type(benchmark.index)))

    # Run all engines
    results = run_all_engines(predictions, returns, benchmark)

    # Print results
    print_results(results)

    # Save
    output = {}
    for k, v in results.items():
        r = v["r"]
        entry = {"description": v["desc"], "wall_seconds": v["t"], **r.to_dict()}
        if "diag" in v:
            entry["diagnostics"] = v["diag"]
        output[k] = entry

    out_path = ARTIFACTS_DIR / "benchmark_optimal_model.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Results saved", path=str(out_path))


if __name__ == "__main__":
    main()
