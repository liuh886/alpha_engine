"""Vectorized feature engineering for fast model training.

This module provides high-performance feature computation using NumPy/Pandas
vectorized operations instead of Qlib's per-expression evaluation.

Key optimizations:
- All features computed in a single pass over the data
- Matrix operations instead of row-by-row computation
- Pre-computed rolling windows for reuse
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_kbar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute K-bar features from OHLCV data.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: open, high, low, close, volume

    Returns
    -------
    pd.DataFrame
        K-bar features
    """
    o = df["open"]
    h = df["high"]
    lo = df["low"]
    c = df["close"]
    df["volume"]

    features = pd.DataFrame(index=df.index)

    # Price-based
    features["kmid"] = (c - o) / o
    features["klen"] = (h - lo) / o
    features["kmid2"] = (c - o) / (h - lo + 1e-12)
    features["kup"] = (h - np.maximum(o, c)) / o
    features["kup2"] = (h - np.maximum(o, c)) / (h - lo + 1e-12)
    features["klow"] = (np.minimum(o, c) - lo) / o
    features["klow2"] = (np.minimum(o, c) - lo) / (h - lo + 1e-12)
    features["ksft"] = (2 * c - h - lo) / o
    features["ksft2"] = (2 * c - h - lo) / (h - lo + 1e-12)

    # Price ratios
    features["open_ratio"] = o / c
    features["high_ratio"] = h / c
    features["low_ratio"] = lo / c

    return features


def compute_rolling_features(
    df: pd.DataFrame, windows: list[int] = [5, 10, 20, 30, 60]
) -> pd.DataFrame:
    """Compute rolling window features.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: open, high, low, close, volume
    windows : list[int]
        Rolling window sizes

    Returns
    -------
    pd.DataFrame
        Rolling features
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]
    v = df["volume"]
    returns = c.pct_change()

    features = pd.DataFrame(index=df.index)

    for w in windows:
        # Momentum
        features[f"roc_{w}"] = c / c.shift(w) - 1

        # Moving averages
        features[f"ma_{w}"] = c.rolling(w).mean() / c

        # Volatility
        features[f"std_{w}"] = returns.rolling(w).std()

        # High/Low range
        features[f"max_high_{w}"] = h.rolling(w).max() / c
        features[f"min_low_{w}"] = lo.rolling(w).min() / c

        # Volume features
        features[f"vol_ma_{w}"] = v.rolling(w).mean() / (v + 1e-12)
        features[f"vol_std_{w}"] = v.rolling(w).std() / (v + 1e-12)

        # Price position in range
        features[f"price_pos_{w}"] = (c - lo.rolling(w).min()) / (
            h.rolling(w).max() - lo.rolling(w).min() + 1e-12
        )

    return features


def compute_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute momentum features.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: open, high, low, close, volume

    Returns
    -------
    pd.DataFrame
        Momentum features
    """
    c = df["close"]
    returns = c.pct_change()

    features = pd.DataFrame(index=df.index)

    # Multi-period momentum
    for d in [5, 10, 20, 60]:
        features[f"mom_{d}"] = c / c.shift(d) - 1

    # Momentum acceleration
    features["mom_accel"] = features["mom_10"] - features["mom_20"]

    # Momentum reversal
    features["mom_reversal"] = -features["mom_5"]

    # Volatility-adjusted momentum
    vol_20 = returns.rolling(20).std()
    features["mom_vol_adj"] = features["mom_10"] / (vol_20 + 1e-12)

    return features


def compute_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute volume-based features.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: open, high, low, close, volume

    Returns
    -------
    pd.DataFrame
        Volume features
    """
    c = df["close"]
    v = df["volume"]
    returns = c.pct_change()

    features = pd.DataFrame(index=df.index)

    # Volume ratios
    features["vol_ratio_5"] = v / (v.rolling(5).mean() + 1e-12)
    features["vol_ratio_20"] = v / (v.rolling(20).mean() + 1e-12)

    # Volume trend
    features["vol_trend"] = v.rolling(5).mean() / (v.rolling(20).mean() + 1e-12)

    # Price-volume correlation
    features["pv_corr_5"] = returns.rolling(5).corr(v.pct_change())
    features["pv_corr_20"] = returns.rolling(20).corr(v.pct_change())

    # Volume-weighted price
    features["vwap_ratio"] = (c * v).rolling(5).sum() / (v.rolling(5).sum() + 1e-12) / c

    return features


def compute_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical indicator features.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: open, high, low, close, volume

    Returns
    -------
    pd.DataFrame
        Technical features
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]
    returns = c.pct_change()

    features = pd.DataFrame(index=df.index)

    # RSI-like features
    for w in [5, 10, 20]:
        gain = returns.where(returns > 0, 0).rolling(w).mean()
        loss = (-returns.where(returns < 0, 0)).rolling(w).mean()
        features[f"rsi_{w}"] = gain / (gain + loss + 1e-12)

    # Bollinger Band position
    ma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std()
    features["bb_pos"] = (c - ma_20) / (2 * std_20 + 1e-12)

    # ATR-like volatility
    tr = pd.concat([h - lo, (h - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1).max(axis=1)
    features["atr_14"] = tr.rolling(14).mean() / c

    # Price acceleration
    features["price_accel"] = returns.diff()

    # Consecutive up/down days
    up = (returns > 0).astype(int)
    features["consec_up"] = up.rolling(5).sum()
    features["consec_down"] = (1 - up).rolling(5).sum()

    return features


def compute_all_features(
    df: pd.DataFrame,
    include_kbar: bool = True,
    include_rolling: bool = True,
    include_momentum: bool = True,
    include_volume: bool = True,
    include_technical: bool = True,
) -> pd.DataFrame:
    """Compute all features in a single pass.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with columns: open, high, low, close, volume
    include_kbar : bool
        Include K-bar features
    include_rolling : bool
        Include rolling window features
    include_momentum : bool
        Include momentum features
    include_volume : bool
        Include volume features
    include_technical : bool
        Include technical indicator features

    Returns
    -------
    pd.DataFrame
        All computed features
    """
    features = pd.DataFrame(index=df.index)

    if include_kbar:
        features = pd.concat([features, compute_kbar_features(df)], axis=1)

    if include_rolling:
        features = pd.concat([features, compute_rolling_features(df)], axis=1)

    if include_momentum:
        features = pd.concat([features, compute_momentum_features(df)], axis=1)

    if include_volume:
        features = pd.concat([features, compute_volume_features(df)], axis=1)

    if include_technical:
        features = pd.concat([features, compute_technical_features(df)], axis=1)

    return features


def prepare_training_data(
    features: pd.DataFrame,
    labels: pd.Series,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
    fill_nan: bool = True,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Prepare training and validation data.

    Parameters
    ----------
    features : pd.DataFrame
        Feature matrix with MultiIndex (datetime, instrument)
    labels : pd.Series
        Label series with MultiIndex (datetime, instrument)
    train_start, train_end : str
        Training period
    valid_start, valid_end : str
        Validation period
    fill_nan : bool
        If True, fill NaN with 0 (safe for z-scored features)

    Returns
    -------
    tuple
        (X_train, y_train, X_valid, y_valid)
    """
    # Align features and labels
    common_idx = features.index.intersection(labels.index)
    features = features.loc[common_idx]
    labels = labels.loc[common_idx]

    # Extract datetime from MultiIndex
    dates = features.index.get_level_values("datetime")

    # Split by date
    train_mask = (dates >= train_start) & (dates <= train_end)
    valid_mask = (dates >= valid_start) & (dates <= valid_end)

    X_train = features[train_mask]
    y_train = labels[train_mask]
    X_valid = features[valid_mask]
    y_valid = labels[valid_mask]

    # Fill NaN (safe for z-scored features where NaN = neutral)
    if fill_nan:
        X_train = X_train.fillna(0)
        X_valid = X_valid.fillna(0)
        y_train = y_train.fillna(0)
        y_valid = y_valid.fillna(0)
    else:
        # Drop rows with NaN in labels only (features can have NaN)
        train_nan_mask = y_train.isna()
        X_train = X_train[~train_nan_mask]
        y_train = y_train[~train_nan_mask]

        valid_nan_mask = y_valid.isna()
        X_valid = X_valid[~valid_nan_mask]
        y_valid = y_valid[~valid_nan_mask]

    return X_train, y_train, X_valid, y_valid
