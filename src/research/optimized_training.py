"""Optimized training pipeline for fast model iteration.

This module provides a streamlined training pipeline that:
1. Loads data once and caches it
2. Computes features using vectorized operations
3. Trains models with optimal hyperparameters
4. Evaluates using vectorized backtest

Usage:
    from src.research.optimized_training import train_and_evaluate
    result = train_and_evaluate(market='cn', topk=15, rebalance_days=10)
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
class TrainingResult:
    """Result from optimized training."""

    market: str
    model_path: str
    n_features: int
    n_train_samples: int
    n_valid_samples: int
    train_ic: float
    valid_ic: float
    backtest_result: dict[str, Any]
    training_time: float
    feature_importance: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "model_path": self.model_path,
            "n_features": self.n_features,
            "n_train_samples": self.n_train_samples,
            "n_valid_samples": self.n_valid_samples,
            "train_ic": round(self.train_ic, 4),
            "valid_ic": round(self.valid_ic, 4),
            "backtest_result": self.backtest_result,
            "training_time": round(self.training_time, 2),
            "top_features": dict(sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)[:20]),
        }


def load_market_data(market: str = "cn") -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Load market data for training.

    Returns
    -------
    tuple[pd.DataFrame, pd.Series, pd.DataFrame]
        (features_df, labels_series, benchmark_returns)
    """
    from qlib.data import D

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    safe_qlib_init(build_qlib_init_cfg({}, market=market))

    # Get symbols filtered by market
    instr_file = Path(f"data/watchlist/instruments/{market}.txt")
    if instr_file.exists():
        symbols = [line.split("\t")[0].strip() for line in instr_file.read_text().splitlines() if line.strip()]
    else:
        # Fallback: use all features
        data_dir = Path("data/watchlist/features")
        symbols = [d.name for d in data_dir.iterdir() if d.is_dir()]

    # Load OHLCV data
    print(f"Loading data for {len(symbols)} {market.upper()} symbols...")
    t0 = time.time()

    ohlcv = D.features(
        symbols,
        ["$open", "$high", "$low", "$close", "$volume"],
        start_time="2018-01-01",
        end_time="2026-06-18",
    )

    # Load labels (10-day forward excess returns)
    labels = D.features(
        symbols,
        ["(Ref($close, -10) / Ref($close, -1) - 1) - Mean(Ref($close, -10) / Ref($close, -1) - 1, 10)"],
        start_time="2018-01-01",
        end_time="2026-06-18",
    )

    # Load benchmark
    bench_symbol = "000300" if market == "cn" else "QQQ"
    benchmark = D.features(
        [bench_symbol],
        ["$close/Ref($close, 1) - 1"],
        start_time="2018-01-01",
        end_time="2026-06-18",
    )

    t1 = time.time()
    print(f"Data loading: {t1-t0:.2f}s")

    return ohlcv, labels, benchmark


def compute_features_vectorized(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Compute features using vectorized operations.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        OHLCV data with MultiIndex (datetime, instrument)

    Returns
    -------
    pd.DataFrame
        Feature matrix with MultiIndex (datetime, instrument)
    """
    from src.research.vectorized_features import compute_all_features

    print("Computing features...")
    t0 = time.time()

    # Group by instrument and compute features
    all_features = []
    instruments = ohlcv.index.get_level_values("instrument").unique()

    for inst in instruments:
        try:
            inst_data = ohlcv.loc[inst]
            if len(inst_data) < 60:  # Need at least 60 days
                continue

            # Rename columns to match expected format
            col_map = {c: c.lstrip("$") for c in inst_data.columns if c.startswith("$")}
            inst_data = inst_data.rename(columns=col_map)

            features = compute_all_features(inst_data)
            # Add instrument level to index
            features["instrument"] = inst
            features = features.reset_index()
            features = features.rename(columns={"index": "datetime"})
            all_features.append(features)
        except Exception:
            continue

    if not all_features:
        return pd.DataFrame()

    # Concatenate all features
    features_df = pd.concat(all_features, axis=0)

    # Create MultiIndex
    features_df = features_df.set_index(["datetime", "instrument"])

    t1 = time.time()
    print(f"Feature computation: {t1-t0:.2f}s, {len(features_df.columns)} features")

    return features_df


def train_model_optimized(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_valid: pd.DataFrame,
    y_valid: pd.Series,
    market: str = "cn",
) -> tuple[lgb.Booster, dict[str, float]]:
    """Train LightGBM model with optimized hyperparameters.

    Parameters
    ----------
    X_train, y_train : training data
    X_valid, y_valid : validation data
    market : str
        Market identifier

    Returns
    -------
    tuple[lgb.Booster, dict[str, float]]
        Trained model and feature importance
    """
    print(f"Training model: {len(X_train)} train, {len(X_valid)} valid samples...")
    t0 = time.time()

    # Create datasets
    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    # Optimized hyperparameters
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

    # Train
    callbacks = [lgb.early_stopping(50), lgb.log_evaluation(100)]
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[valid_data],
        callbacks=callbacks,
    )

    t1 = time.time()
    print(f"Training: {t1-t0:.2f}s, best_iteration={model.best_iteration}")

    # Feature importance
    importance = model.feature_importance(importance_type="gain")
    feature_names = model.feature_name()
    feature_importance = dict(zip(feature_names, importance.tolist()))

    return model, feature_importance


def evaluate_predictions(
    model: lgb.Booster,
    X: pd.DataFrame,
    y: pd.Series,
) -> tuple[float, float, float]:
    """Evaluate model predictions.

    Returns
    -------
    tuple[float, float, float]
        (mean_ic, ic_ir, positive_ic_ratio)
    """
    predictions = model.predict(X)

    # Compute IC per date
    dates = X.index.get_level_values("datetime").unique()
    ics = []

    for date in dates:
        try:
            mask = X.index.get_level_values("datetime") == date
            pred_day = predictions[mask]
            actual_day = y[mask].values

            # Remove NaN
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


def train_and_evaluate(
    market: str = "cn",
    topk: int = 15,
    rebalance_days: int = 10,
    train_start: str = "2018-01-01",
    train_end: str = "2024-12-31",
    valid_start: str = "2025-01-01",
    valid_end: str = "2025-06-30",
    test_start: str = "2025-07-01",
    test_end: str = "2026-06-18",
) -> TrainingResult:
    """Train and evaluate a model using the optimized pipeline.

    Parameters
    ----------
    market : str
        Market identifier (cn or us)
    topk : int
        Number of top stocks to hold
    rebalance_days : int
        Rebalance frequency in days
    train_start, train_end : str
        Training period
    valid_start, valid_end : str
        Validation period
    test_start, test_end : str
        Test period

    Returns
    -------
    TrainingResult
        Training and evaluation results
    """
    t0 = time.time()

    # Load data
    ohlcv, labels_df, benchmark_df = load_market_data(market)

    # Compute features
    features_df = compute_features_vectorized(ohlcv)

    # Prepare labels - reorder index to match features
    labels = labels_df.iloc[:, 0]
    labels = labels.reorder_levels(["datetime", "instrument"])

    # Prepare training data
    from src.research.vectorized_features import prepare_training_data

    X_train, y_train, X_valid, y_valid = prepare_training_data(
        features_df, labels, train_start, train_end, valid_start, valid_end
    )

    # Train model
    model, feature_importance = train_model_optimized(X_train, y_train, X_valid, y_valid, market)

    # Evaluate on validation set
    valid_ic, valid_ir, valid_pos = evaluate_predictions(model, X_valid, y_valid)
    print(f"Validation: IC={valid_ic:.4f}, IR={valid_ir:.4f}, Pos={valid_pos:.2%}")

    # Evaluate on test set - sort index first for slicing
    features_df = features_df.sort_index()
    labels = labels.sort_index()

    # Get test period data
    dates = features_df.index.get_level_values("datetime")
    test_mask = (dates >= test_start) & (dates <= test_end)
    X_test = features_df[test_mask]
    y_test = labels[test_mask]

    # Align
    common_idx = X_test.index.intersection(y_test.index)
    X_test = X_test.loc[common_idx]
    y_test = y_test.loc[common_idx]

    # Drop NaN
    test_nan_mask = X_test.isna().any(axis=1) | y_test.isna()
    X_test = X_test[~test_nan_mask]
    y_test = y_test[~test_nan_mask]

    test_ic, test_ir, test_pos = evaluate_predictions(model, X_test, y_test)
    print(f"Test: IC={test_ic:.4f}, IR={test_ir:.4f}, Pos={test_pos:.2%}")

    # Run vectorized backtest
    from src.research.vectorized_backtest import run_vectorized_backtest

    # Create predictions DataFrame
    predictions = pd.DataFrame(
        {"score": model.predict(X_test)},
        index=X_test.index,
    )

    # Load ABSOLUTE returns for backtest (not excess returns)
    from qlib.data import D as _D
    symbols = list(set(features_df.index.get_level_values("instrument")))
    abs_returns = _D.features(
        symbols,
        ["Ref($close, -10) / Ref($close, -1) - 1"],
        start_time=test_start,
        end_time=test_end,
    )
    # The result has MultiIndex (instrument, datetime)
    # Reorder to match predictions: (datetime, instrument)
    abs_returns = abs_returns.reorder_levels(["datetime", "instrument"])
    abs_returns = abs_returns.sort_index()
    abs_returns.columns = ["return"]
    returns_df = abs_returns

    # Load benchmark for test period - flatten to single instrument
    bench_dates = benchmark_df.index.get_level_values("datetime")
    bench_mask = (bench_dates >= test_start) & (bench_dates <= test_end)
    benchmark = benchmark_df[bench_mask]
    # Flatten MultiIndex to just datetime (take first instrument)
    instruments = benchmark.index.get_level_values("instrument").unique()
    if len(instruments) > 0:
        benchmark = benchmark.loc[instruments[0]]
    # Ensure datetime index
    benchmark = benchmark.sort_index()

    backtest_result = run_vectorized_backtest(
        predictions=predictions,
        returns=returns_df,
        benchmark_returns=benchmark,
        topk=topk,
        rebalance_days=rebalance_days,
        cost_bps=20,
        non_overlapping=True,
    )

    # Save model
    model_dir = Path("artifacts/models")
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{market}_optimized_{int(time.time())}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    t1 = time.time()

    return TrainingResult(
        market=market,
        model_path=str(model_path),
        n_features=len(X_train.columns),
        n_train_samples=len(X_train),
        n_valid_samples=len(X_valid),
        train_ic=test_ic,  # Using test IC as primary metric
        valid_ic=valid_ic,
        backtest_result=backtest_result.to_dict(),
        training_time=t1 - t0,
        feature_importance=feature_importance,
    )
