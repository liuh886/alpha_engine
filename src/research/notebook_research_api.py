"""Notebook-callable research helpers."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def daily_correlation_table(
    values: pd.DataFrame,
    target: pd.DataFrame,
    *,
    min_items_per_day: int = 5,
) -> pd.DataFrame:
    target_series = target.iloc[:, 0]
    rows: list[dict[str, Any]] = []
    for name in values.columns:
        common = values[name].index.intersection(target_series.index)
        frame = pd.DataFrame({"x": values.loc[common, name], "y": target_series.loc[common]}).dropna()
        daily: list[float] = []
        for _, group in frame.groupby(level="datetime"):
            if len(group) < min_items_per_day:
                continue
            corr = group["x"].corr(group["y"])
            if np.isfinite(corr):
                daily.append(float(corr))
        mean_corr = float(np.mean(daily)) if daily else 0.0
        std_corr = float(np.std(daily, ddof=1)) if len(daily) > 1 else 0.0
        rows.append({"name": str(name), "mean": mean_corr, "ir": mean_corr / std_corr if std_corr > 1e-12 else 0.0, "n_days": len(daily)})
    return pd.DataFrame(rows).sort_values("ir", ascending=False).reset_index(drop=True)
