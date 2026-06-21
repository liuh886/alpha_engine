"""Vectorized signal pre-computer for batch signal materialization.

Replaces per-bar D.features() calls with a single batch fetch,
then computes MA, rankings, and signals using NumPy/Pandas vectorization.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import structlog

logger = structlog.get_logger()

__all__ = ["PrecomputedSignals", "VectorizedSignalPrecomputer"]


@dataclass
class PrecomputedSignals:
    """Container for all pre-computed signal data."""

    # Raw close prices: DataFrame (datetime × instrument)
    close_matrix: pd.DataFrame

    # Moving averages: DataFrame (datetime × instrument)
    ma_matrix: pd.DataFrame

    # Cross-sectional ranks per date: DataFrame (datetime × instrument)
    rank_matrix: pd.DataFrame

    # Model prediction scores: DataFrame (datetime × instrument)
    score_matrix: pd.DataFrame

    # Date index (sorted)
    dates: pd.DatetimeIndex

    # Instrument list
    instruments: list[str]

    # Metadata
    ma_window: int = 60
    total_stocks: int = 0

    def get_scores_on_date(self, dt: pd.Timestamp) -> pd.Series:
        """Get cross-sectional scores for a specific date, sorted descending."""
        if dt not in self.score_matrix.index:
            return pd.Series(dtype=float)
        scores = self.score_matrix.loc[dt].dropna()
        return scores.sort_values(ascending=False)

    def get_ranks_on_date(self, dt: pd.Timestamp) -> pd.Series:
        """Get cross-sectional ranks for a specific date (0 = best)."""
        if dt not in self.rank_matrix.index:
            return pd.Series(dtype=float)
        return self.rank_matrix.loc[dt]

    def get_ma_on_date(self, dt: pd.Timestamp) -> pd.Series:
        """Get MA values for a specific date."""
        if dt not in self.ma_matrix.index:
            return pd.Series(dtype=float)
        return self.ma_matrix.loc[dt]

    def get_close_on_date(self, dt: pd.Timestamp) -> pd.Series:
        """Get close prices for a specific date."""
        if dt not in self.close_matrix.index:
            return pd.Series(dtype=float)
        return self.close_matrix.loc[dt]

    def is_ma_cross_under(self, dt: pd.Timestamp) -> pd.Series:
        """Check if close < MA for each stock on a date (vectorized)."""
        close = self.get_close_on_date(dt)
        ma = self.get_ma_on_date(dt)
        common = close.index.intersection(ma.index)
        return close[common] < ma[common]


class VectorizedSignalPrecomputer:
    """Pre-compute all signals for all stocks across all dates upfront.

    Usage::

        precomputer = VectorizedSignalPrecomputer(ma_window=60)
        signals = precomputer.precompute(
            instruments=['AAPL', 'NVDA', ...],
            start_time='2025-01-01',
            end_time='2026-06-17',
            market='us',
        )
        # Then use signals.get_scores_on_date(dt) in strategy
    """

    def __init__(self, ma_window: int = 60):
        self.ma_window = ma_window

    def precompute(
        self,
        instruments: list[str],
        start_time: str,
        end_time: str,
        market: str = "us",
        pred_df: pd.DataFrame | None = None,
    ) -> PrecomputedSignals:
        """Pre-compute all signals in a single batch operation.

        Parameters
        ----------
        instruments : list[str]
            Stock symbols to include.
        start_time : str
            Start date (ISO format).
        end_time : str
            End date (ISO format).
        market : str
            Market identifier for Qlib init.
        pred_df : pd.DataFrame, optional
            Pre-loaded predictions. If None, will try to load from artifacts.

        Returns
        -------
        PrecomputedSignals
            All pre-computed signal data.
        """
        from qlib.data import D

        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

        safe_qlib_init(build_qlib_init_cfg({}, market=market))

        logger.info(
            "precompute_start",
            n_instruments=len(instruments),
            start=start_time,
            end=end_time,
        )

        # Step 1: Batch fetch close prices (single D.features() call)
        fields = ["$close"]
        close_df = D.features(
            instruments,
            fields,
            start_time=start_time,
            end_time=end_time,
        )

        return self.precompute_from_frame(close_df, pred_df=pred_df)

    def precompute_from_frame(
        self,
        close_df: pd.DataFrame,
        *,
        pred_df: pd.DataFrame | None = None,
    ) -> PrecomputedSignals:
        """Precompute signals from a Qlib-shaped feature frame without I/O."""
        if close_df.empty:
            logger.warning("precompute_empty_close")
            return PrecomputedSignals(
                close_matrix=pd.DataFrame(),
                ma_matrix=pd.DataFrame(),
                rank_matrix=pd.DataFrame(),
                score_matrix=pd.DataFrame(),
                dates=pd.DatetimeIndex([]),
                instruments=[],
                ma_window=self.ma_window,
            )

        # Pivot to matrix (datetime × instrument)
        close_matrix = close_df.iloc[:, 0].unstack(level="instrument")

        # Step 2: Vectorized MA computation (no D.features() call needed)
        ma_matrix = close_matrix.rolling(window=self.ma_window, min_periods=self.ma_window).mean()

        # Step 3: Load predictions and build score matrix
        instruments = list(close_matrix.columns)
        score_matrix = self._build_score_matrix(pred_df, close_matrix.index, instruments)

        # Step 4: Vectorized ranking per date (descending score = rank 0 is best)
        rank_matrix = score_matrix.rank(axis=1, ascending=False, method="min") - 1

        logger.info(
            "precompute_done",
            n_dates=len(close_matrix.index),
            n_instruments=len(close_matrix.columns),
            memory_mb=round(close_matrix.memory_usage(deep=True).sum() / 1024 / 1024, 2),
        )

        return PrecomputedSignals(
            close_matrix=close_matrix,
            ma_matrix=ma_matrix,
            rank_matrix=rank_matrix,
            score_matrix=score_matrix,
            dates=close_matrix.index,
            instruments=list(close_matrix.columns),
            ma_window=self.ma_window,
            total_stocks=len(close_matrix.columns),
        )

    def _build_score_matrix(
        self,
        pred_df: pd.DataFrame | None,
        dates: pd.DatetimeIndex,
        instruments: list[str],
    ) -> pd.DataFrame:
        """Build a score matrix (datetime × instrument) from predictions.

        Missing predictions remain NaN so they cannot become ranked candidates.
        """
        if pred_df is None or pred_df.empty:
            return pd.DataFrame(index=dates, columns=instruments, dtype=float)

        try:
            # Ensure predictions have the right index
            if isinstance(pred_df.index, pd.MultiIndex):
                if "datetime" in pred_df.index.names and "instrument" in pred_df.index.names:
                    # Pivot to matrix
                    score_matrix = pred_df.iloc[:, 0].unstack(level="instrument")
                    # Align with close_matrix dates and instruments
                    score_matrix = score_matrix.reindex(index=dates, columns=instruments)
                    return score_matrix

            # If predictions are already a matrix
            if isinstance(pred_df, pd.DataFrame):
                return pred_df.reindex(index=dates, columns=instruments)

        except Exception as exc:
            logger.warning("score_matrix_build_failed", error=str(exc))

        return pd.DataFrame(index=dates, columns=instruments, dtype=float)


class FeatureCache:
    """Cache D.features() results to avoid repeated calls.

    Usage::

        cache = FeatureCache()
        df1 = cache.get(instruments, fields, start, end)  # fetches from Qlib
        df2 = cache.get(instruments, fields, start, end)  # returns cached
    """

    def __init__(self, max_size: int = 100):
        self._cache: dict[str, pd.DataFrame] = {}
        self._max_size = max_size

    def _make_key(self, instruments: list[str], fields: list[str], start: str, end: str) -> str:
        """Create a cache key from parameters."""
        return f"{tuple(sorted(instruments))}|{tuple(fields)}|{start}|{end}"

    def get(
        self,
        instruments: list[str],
        fields: list[str],
        start_time: str,
        end_time: str,
    ) -> pd.DataFrame:
        """Get features from cache or fetch from Qlib."""
        key = self._make_key(instruments, fields, start_time, end_time)

        if key in self._cache:
            return self._cache[key].copy()

        from qlib.data import D

        df = D.features(instruments, fields, start_time=start_time, end_time=end_time)

        # Evict oldest if cache is full
        if len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = df.copy()
        return df

    def clear(self):
        """Clear the cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)
