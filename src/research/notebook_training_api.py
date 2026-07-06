"""Notebook-callable training helpers for fixed-10D research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def prepare_training_frame(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    label_type: str = "raw_10d_return",
) -> tuple[pd.DataFrame, pd.Series]:
    """Align feature matrix and target series for notebook training."""

    target = labels.iloc[:, 0]
    common = features.index.intersection(target.index)
    x = features.loc[common].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = target.loc[common].astype(float).fillna(0.0)
    if label_type == "excess":
        y = y - y.groupby(level="datetime").transform("mean").fillna(0.0)
    elif label_type == "rank":
        y = y.groupby(level="datetime").rank(pct=True).fillna(0.0)
    elif label_type not in {"raw_10d_return", "absret"}:
        raise ValueError(f"unsupported label_type: {label_type}")
    return x, y
