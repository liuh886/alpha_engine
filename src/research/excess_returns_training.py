"""Excess returns training pipeline.

This module trains models on excess returns (relative to benchmark),
pre-processing data by detrending against CSI300/QQQ.

Key design:
- Label: stock return - benchmark return (excess return)
- Features: same 73 vectorized features
- Evaluation: TOP N / BOTTOM N excess return backtest
"""

from __future__ import annotations

import pickle
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd


@dataclass
class ExcessTrainingResult:
    """Result from excess returns training."""

    market: str
    model_path: str
    n_features: int
    n_train_samples: int
    n_valid_samples: int
    valid_ic: float
    test_ic: float
    top15_excess: float
    bottom15_excess: float
    spread: float
    sharpe: float
    training_time: float
    feature_importance: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "model_path": self.model_path,
            "n_features": self.n_features,
            "n_train_samples": self.n_train_samples,
            "n_valid_samples": self.n_valid_samples,
            "valid_ic": round(self.valid_ic, 4),
            "test_ic": round(self.test_ic, 4),
            "top15_excess": round(self.top15_excess, 4),
            "bottom15_excess": round(self.bottom15_excess, 4),
            "spread": round(self.spread, 4),
            "sharpe": round(self.sharpe, 4),
            "training_time": round(self.training_time, 2),
            "top_features": dict(sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)[:20]),
        }


def load_and_detrend_data(
    market: str = "cn",
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Load market data and compute excess returns by detrending against benchmark.

    Returns
    -------
    tuple[pd.DataFrame, pd.Series, pd.DataFrame]
        (ohlcv_df, excess_labels, benchmark_returns)
    """
    from qlib.data import D

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    safe_qlib_init(build_qlib_init_cfg({}, market=market))

    # Get symbols
    instr_file = Path(f"data/watchlist/instruments/{market}.txt")
    symbols = [line.split("\t")[0].strip() for line in instr_file.read_text().splitlines() if line.strip()]

    # Load OHLCV
    print(f"Loading {len(symbols)} {market.upper()} symbols...")
    ohlcv = D.features(
        symbols,
        ["$open", "$high", "$low", "$close", "$volume"],
        start_time="2018-01-01",
        end_time="2026-06-18",
    )

    # Load stock returns (10-day forward)
    stock_returns = D.features(
        symbols,
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time="2018-01-01",
        end_time="2026-06-18",
    )

    # Load benchmark returns (10-day forward)
    bench_symbol = "000300" if market == "cn" else "QQQ"
    bench_returns = D.features(
        [bench_symbol],
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time="2018-01-01",
        end_time="2026-06-18",
    )

    # Compute excess returns: stock return - benchmark return
    # Flatten benchmark to Series
    bench_flat = bench_returns.xs(bench_symbol, level="instrument")
    bench_col = bench_flat.columns[0]

    # For each stock, compute excess return
    stock_returns_flat = stock_returns.iloc[:, 0]
    excess_labels = pd.Series(index=stock_returns_flat.index, dtype=float)

    for date in bench_flat.index:
        if date in stock_returns_flat.index.get_level_values("datetime"):
            bench_ret = float(bench_flat.loc[date, bench_col])
            mask = stock_returns_flat.index.get_level_values("datetime") == date
            excess_labels[mask] = stock_returns_flat[mask] - bench_ret

    return ohlcv, excess_labels, bench_returns


def compute_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Compute vectorized features from OHLCV data."""
    from src.research.vectorized_features import compute_all_features

    print("Computing features...")
    t0 = time.time()

    all_features = []
    instruments = ohlcv.index.get_level_values("instrument").unique()

    for inst in instruments:
        try:
            inst_data = ohlcv.loc[inst]
            if len(inst_data) < 60:
                continue

            # Rename columns
            col_map = {c: c.lstrip("$") for c in inst_data.columns if c.startswith("$")}
            inst_data = inst_data.rename(columns=col_map)

            features = compute_all_features(inst_data)
            features["instrument"] = inst
            features = features.reset_index()
            features = features.rename(columns={"index": "datetime"})
            all_features.append(features)
        except Exception:
            continue

    if not all_features:
        return pd.DataFrame()

    features_df = pd.concat(all_features, axis=0)
    features_df = features_df.set_index(["datetime", "instrument"])

    t1 = time.time()
    print(f"Feature computation: {t1-t0:.2f}s, {len(features_df.columns)} features")

    return features_df


def prepare_data(
    features: pd.DataFrame,
    labels: pd.Series,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Prepare training and validation data."""
    # Align
    common_idx = features.index.intersection(labels.index)
    features = features.loc[common_idx]
    labels = labels.loc[common_idx]

    # Split by date
    dates = features.index.get_level_values("datetime")
    train_mask = (dates >= train_start) & (dates <= train_end)
    valid_mask = (dates >= valid_start) & (dates <= valid_end)

    X_train = features[train_mask].fillna(0)
    y_train = labels[train_mask].fillna(0)
    X_valid = features[valid_mask].fillna(0)
    y_valid = labels[valid_mask].fillna(0)

    return X_train, y_train, X_valid, y_valid


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_valid: pd.DataFrame,
    y_valid: pd.Series,
) -> tuple[lgb.Booster, dict[str, float]]:
    """Train LightGBM model."""
    print(f"Training: {len(X_train)} train, {len(X_valid)} valid...")

    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    params = {
        "objective": "regression",
        "metric": "mse",
        "boosting_type": "gbdt",
        "learning_rate": 0.05,
        "num_leaves": 128,
        "max_depth": 10,
        "min_child_samples": 20,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l1": 1.0,
        "lambda_l2": 1.0,
        "verbose": -1,
        "n_jobs": -1,
    }

    callbacks = [lgb.early_stopping(50), lgb.log_evaluation(100)]
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[valid_data],
        callbacks=callbacks,
    )

    importance = model.feature_importance(importance_type="gain")
    feature_names = model.feature_name()
    feature_importance = dict(zip(feature_names, importance.tolist()))

    return model, feature_importance


def evaluate_ic(model: lgb.Booster, X: pd.DataFrame, y: pd.Series) -> tuple[float, float, float]:
    """Evaluate model IC."""
    predictions = model.predict(X)
    dates = X.index.get_level_values("datetime").unique()

    ics = []
    for date in dates:
        try:
            mask = X.index.get_level_values("datetime") == date
            pred_day = predictions[mask]
            actual_day = y[mask].values
            valid = ~(np.isnan(pred_day) | np.isnan(actual_day))
            if valid.sum() < 10:
                continue
            ic = np.corrcoef(pred_day[valid], actual_day[valid])[0, 1]
            if not np.isnan(ic):
                ics.append(ic)
        except Exception:
            continue

    if not ics:
        return 0.0, 0.0, 0.0

    mean_ic = float(np.mean(ics))
    ic_std = float(np.std(ics))
    ic_ir = mean_ic / ic_std if ic_std > 1e-10 else 0.0
    pos_ratio = sum(1 for ic in ics if ic > 0) / len(ics)

    return mean_ic, ic_ir, pos_ratio


def run_excess_backtest(
    model: lgb.Booster,
    X_test: pd.DataFrame,
    stock_returns: pd.Series,
    benchmark_returns: pd.Series,
    topk: int = 15,
    rebalance_days: int = 10,
) -> dict[str, float]:
    """Run TOP/BOTTOM N excess return backtest."""
    from src.research.vectorized_backtest import run_vectorized_backtest

    # Generate predictions
    predictions = pd.DataFrame(
        {"score": model.predict(X_test)},
        index=X_test.index,
    )

    # Prepare returns DataFrame
    returns_df = stock_returns.to_frame(name="return")

    # Flatten benchmark to datetime index
    bench_flat = benchmark_returns.iloc[:, 0] if isinstance(benchmark_returns, pd.DataFrame) else benchmark_returns
    if hasattr(bench_flat, 'index') and 'instrument' in str(bench_flat.index.names):
        bench_symbol = bench_flat.index.get_level_values("instrument").unique()[0]
        bench_flat = bench_flat.xs(bench_symbol, level="instrument")

    # TOP N backtest
    result_top = run_vectorized_backtest(
        predictions=predictions,
        returns=returns_df,
        benchmark_returns=bench_flat.to_frame(name="return") if isinstance(bench_flat, pd.Series) else bench_flat,
        topk=topk,
        rebalance_days=rebalance_days,
        cost_bps=20,
        non_overlapping=True,
    )

    # BOTTOM N backtest
    pred_inv = predictions.copy()
    pred_inv["score"] = -pred_inv["score"]
    result_bottom = run_vectorized_backtest(
        predictions=pred_inv,
        returns=returns_df,
        benchmark_returns=bench_flat.to_frame(name="return") if isinstance(bench_flat, pd.Series) else bench_flat,
        topk=topk,
        rebalance_days=rebalance_days,
        cost_bps=20,
        non_overlapping=True,
    )

    return {
        "top_excess": result_top.excess_return,
        "bottom_excess": result_bottom.excess_return,
        "spread": result_top.excess_return - result_bottom.excess_return,
        "top_sharpe": result_top.sharpe_ratio,
        "top_total": result_top.total_return,
        "benchmark_return": result_top.benchmark_return,
        "ic": result_top.mean_ic,
        "ic_ir": result_top.ic_ir,
    }


def train_and_evaluate_excess(
    market: str = "cn",
    topk: int = 15,
    rebalance_days: int = 10,
) -> ExcessTrainingResult:
    """Full pipeline: load data, detrend, train, evaluate."""
    t0 = time.time()

    # Load and detrend data
    ohlcv, excess_labels, bench_returns = load_and_detrend_data(market)

    # Compute features
    features = compute_features(ohlcv)

    # Sort for slicing and align index order
    features = features.sort_index()
    excess_labels = excess_labels.reorder_levels(["datetime", "instrument"]).sort_index()

    # Prepare data
    X_train, y_train, X_valid, y_valid = prepare_data(
        features, excess_labels,
        "2018-01-01", "2024-12-31",
        "2025-01-01", "2025-06-30",
    )

    # Train
    model, feature_importance = train_model(X_train, y_train, X_valid, y_valid)

    # Evaluate IC
    valid_ic, valid_ir, valid_pos = evaluate_ic(model, X_valid, y_valid)
    print(f"Valid: IC={valid_ic:.4f}, IR={valid_ir:.4f}, Pos={valid_pos:.2%}")

    # Prepare test data
    dates = features.index.get_level_values("datetime")
    test_mask = (dates >= "2025-07-01") & (dates <= "2026-06-18")
    X_test = features[test_mask]

    # Get stock returns for test period
    stock_returns_flat = excess_labels[test_mask]

    # Get benchmark returns for test period
    bench_dates = bench_returns.index.get_level_values("datetime")
    bench_mask = (bench_dates >= "2025-07-01") & (bench_dates <= "2026-06-18")
    bench_test = bench_returns[bench_mask]

    # Evaluate IC on test set
    y_test = excess_labels[test_mask]
    test_ic, test_ir, test_pos = evaluate_ic(model, X_test, y_test)
    print(f"Test: IC={test_ic:.4f}, IR={test_ir:.4f}, Pos={test_pos:.2%}")

    # Run backtest
    backtest = run_excess_backtest(
        model, X_test, stock_returns_flat, bench_test,
        topk=topk, rebalance_days=rebalance_days,
    )

    print(f"TOP {topk} excess: {backtest['top_excess']:.2%}")
    print(f"BOTTOM {topk} excess: {backtest['bottom_excess']:.2%}")
    print(f"Spread: {backtest['spread']:.2%}")
    print(f"Sharpe: {backtest['top_sharpe']:.2f}")

    # Save model
    model_dir = Path("artifacts/models")
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{market}_excess_{int(time.time())}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    t1 = time.time()

    return ExcessTrainingResult(
        market=market,
        model_path=str(model_path),
        n_features=len(X_train.columns),
        n_train_samples=len(X_train),
        n_valid_samples=len(X_valid),
        valid_ic=valid_ic,
        test_ic=test_ic,
        top15_excess=backtest["top_excess"],
        bottom15_excess=backtest["bottom_excess"],
        spread=backtest["spread"],
        sharpe=backtest["top_sharpe"],
        training_time=t1 - t0,
        feature_importance=feature_importance,
    )
