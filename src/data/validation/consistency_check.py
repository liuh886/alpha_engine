from __future__ import annotations

import numpy as np
import pandas as pd


def compute_df_diff(df1: pd.DataFrame, df2: pd.DataFrame, columns: list[str] | None = None) -> dict[str, float]:
    """
    Compute the average absolute percentage difference between two DataFrames for specified columns.
    Assumes DataFrames are aligned by index (usually date).
    """
    if columns is None:
        columns = ["open", "high", "low", "close", "volume"]
    
    # Keep only overlapping indices
    common_idx = df1.index.intersection(df2.index)
    if common_idx.empty:
        return {col: np.nan for col in columns}
    
    d1 = df1.loc[common_idx, columns]
    d2 = df2.loc[common_idx, columns]
    
    # Compute relative difference: |d1 - d2| / d1
    # Avoid division by zero
    diff = (d1 - d2).abs() / d1.replace(0, np.nan)
    
    # Mean of non-NaN values
    results = diff.mean().to_dict()
    return results

class ConsistencyChecker:
    def __init__(self, threshold: float = 0.02):
        self.threshold = threshold

    def check(self, df_primary: pd.DataFrame, df_fallback: pd.DataFrame, symbol: str) -> dict:
        """
        Check consistency and return a report.
        """
        diffs = compute_df_diff(df_primary, df_fallback)
        
        warnings = []
        for col, val in diffs.items():
            if val > self.threshold:
                warnings.append(f"{col} difference too high: {val:.2%}")
        
        return {
            "symbol": symbol,
            "ok": len(warnings) == 0,
            "diffs": diffs,
            "warnings": warnings
        }
