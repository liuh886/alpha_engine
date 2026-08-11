"""Optimization data cache — load once, reuse across all candidates.

Eliminates redundant feature/return loading across candidates and windows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.research.qlib_execution_common import normalize_qlib_frame_index


@dataclass
class OptimizationDataCache:
    """Pre-loaded data shared across all candidates in an experiment.

    Key design: features and returns are loaded ONCE per window and
    shared across all candidates. Each candidate selects its own
    factor columns via expression index mapping.
    """

    market: str
    symbols: list[str]
    benchmark: str
    return_expression: str = "Ref($close, -10) / $close - 1"

    # Window-level caches
    _features: dict[str, pd.DataFrame] = field(default_factory=dict)
    _returns: dict[str, pd.DataFrame] = field(default_factory=dict)
    _benchmarks: dict[str, pd.DataFrame] = field(default_factory=dict)
    _eval_dates: dict[str, pd.DatetimeIndex] = field(default_factory=dict)
    _train_masks: dict[str, pd.Series] = field(default_factory=dict)
    _test_masks: dict[str, pd.Series] = field(default_factory=dict)

    def has_window(self, window_label: str) -> bool:
        return window_label in self._features

    def store_window(
        self,
        window_label: str,
        features: pd.DataFrame,
        returns: pd.DataFrame,
        benchmark: pd.DataFrame,
        eval_dates: pd.DatetimeIndex,
        train_mask: pd.Series,
        test_mask: pd.Series,
    ) -> None:
        self._features[window_label] = features
        self._returns[window_label] = returns
        self._benchmarks[window_label] = benchmark
        self._eval_dates[window_label] = eval_dates
        self._train_masks[window_label] = train_mask
        self._test_masks[window_label] = test_mask

    def get_window(self, window_label: str) -> dict[str, Any]:
        """Return all cached data for a window."""
        return {
            "features": self._features.get(window_label),
            "returns": self._returns.get(window_label),
            "benchmark": self._benchmarks.get(window_label),
            "eval_dates": self._eval_dates.get(window_label),
            "train_mask": self._train_masks.get(window_label),
            "test_mask": self._test_masks.get(window_label),
        }

    @property
    def cached_windows(self) -> list[str]:
        return sorted(self._features.keys())
