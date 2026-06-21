"""Grade-differentiated position weight assignment.

Maps cross-sectional model scores to portfolio weights using the
AAA / AA / A / V / VV / VVV signal grade system.  Higher-confidence
signals receive proportionally larger position weights, replacing
the equal-weight TOP-N approach.

Core insight:
    An AAA-ranked stock deserves 3× the weight of an A-ranked stock.
    A VVV-ranked stock deserves 3× the short weight of a V-ranked stock.

This module is designed for use by ``SignalExecutionEngine`` but can
also be used standalone for position sizing given a cross-section of
model scores.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.execution.signal_execution_config import SignalExecutionConfig
from src.strategies.signal_grade_engine import GRADES, SignalGradeEngine

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradeAllocation:
    """Portfolio allocation for a single rebalance date.

    Attributes
    ----------
    date : str
        ISO date string for tracing.
    long_positions : dict[str, float]
        {instrument: portfolio_weight} for the long basket.
    short_positions : dict[str, float]
        {instrument: portfolio_weight} for the short basket.
        Weights are positive (the engine handles the short-side P&L sign).
    long_count : int
        Number of stocks that received a buy-grade (AAA, AA, A).
    short_count : int
        Number of stocks that received a sell-grade (V, VV, VVV).
    ungraded_count : int
        Number of stocks in the middle zone (no grade).
    has_sufficient_stocks : bool
        True when the long basket meets ``min_stocks_per_side``.
    """

    date: str
    long_positions: dict[str, float]
    short_positions: dict[str, float]
    long_count: int
    short_count: int
    ungraded_count: int
    has_sufficient_stocks: bool


# ---------------------------------------------------------------------------
# Assigner
# ---------------------------------------------------------------------------


class GradeWeightAssigner:
    """Maps signal grades to differentiated portfolio weights.

    Weight computation (per rebalance date):

    1. All stocks are graded AAA–VVV by cross-sectional rank.
    2. Raw weights come from ``grade_weights`` config (AAA=3.0, …, VVV=-3.0).
    3. Long basket: stocks with positive grade weights, normalized to
       sum to ``long_fraction × regime_factor``.
    4. Short basket: stocks with negative grade weights, normalized to
       sum to ``short_fraction × regime_factor``.
    5. Each position is capped at ``max_single_position_weight``.

    If a basket has fewer than ``min_stocks_per_side``, it is skipped.
    """

    def __init__(self, config: SignalExecutionConfig):
        self._cfg = config
        self._grade_engine = SignalGradeEngine(step_size=config.step_size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_allocation(
        self,
        scores: pd.Series,
        current_date: str,
        regime_factor: float = 1.0,
    ) -> GradeAllocation:
        """Compute grade-weighted allocation for one cross-section.

        Parameters
        ----------
        scores : pd.Series
            Cross-sectional model scores indexed by instrument.
            Typically comes from ``score_matrix.loc[date]``.
        current_date : str
            ISO date string for the allocation (tracing only).
        regime_factor : float
            Exposure multiplier from ``RegimeFilter``, in [0.0, 1.0].
            1.0 = full exposure, 0.0 = 100% cash.

        Returns
        -------
        GradeAllocation
        """
        # Drop NaN and sort descending for grade assignment
        sorted_scores = scores.dropna().sort_values(ascending=False)
        total_stocks = len(sorted_scores)

        if total_stocks == 0:
            return GradeAllocation(
                date=current_date,
                long_positions={},
                short_positions={},
                long_count=0,
                short_count=0,
                ungraded_count=0,
                has_sufficient_stocks=False,
            )

        # Assign grades to all stocks
        grades: dict[str, str] = {}
        for idx, instrument in enumerate(sorted_scores.index):
            grade = self._grade_engine._rank_to_grade(idx, total_stocks)
            grades[instrument] = grade

        # Separate into long and short baskets by grade weight sign
        long_raw: dict[str, float] = {}
        short_raw: dict[str, float] = {}
        for instrument, grade in grades.items():
            weight = self._cfg.grade_weights.get(grade, 0.0)
            if weight > 0:
                long_raw[instrument] = weight
            elif weight < 0:
                short_raw[instrument] = abs(weight)
            # weight == 0 → middle zone, skip

        # Apply regime_factor to target allocations
        long_target = self._cfg.long_fraction * regime_factor
        short_target = self._cfg.short_fraction * regime_factor

        # Normalize each basket
        long_positions = self._normalize_basket(
            raw_weights=long_raw,
            target_total=long_target,
            max_single=self._cfg.max_single_position_weight,
            min_stocks=self._cfg.min_stocks_per_side,
        )
        short_positions = self._normalize_basket(
            raw_weights=short_raw,
            target_total=short_target,
            max_single=self._cfg.max_single_position_weight,
            min_stocks=self._cfg.min_stocks_per_side,
        )

        has_sufficient = len(long_positions) >= self._cfg.min_stocks_per_side
        ungraded = total_stocks - len(long_raw) - len(short_raw)

        return GradeAllocation(
            date=current_date,
            long_positions=long_positions,
            short_positions=short_positions,
            long_count=len(long_raw),
            short_count=len(short_raw),
            ungraded_count=ungraded,
            has_sufficient_stocks=has_sufficient,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_basket(
        raw_weights: dict[str, float],
        target_total: float,
        max_single: float,
        min_stocks: int,
    ) -> dict[str, float]:
        """Normalize raw grade weights into portfolio weights.

        Parameters
        ----------
        raw_weights : dict[str, float]
            {instrument: raw_grade_weight} where all values are positive.
        target_total : float
            Desired sum of all output weights (e.g., 0.8 for long side).
        max_single : float
            Hard cap on any single position weight.
        min_stocks : int
            If ``len(raw_weights) < min_stocks``, return an empty dict.

        Returns
        -------
        dict[str, float]
            Normalized weights summing approximately to ``target_total``.
        """
        if len(raw_weights) < min_stocks or target_total <= 0:
            return {}

        total_raw = sum(raw_weights.values())
        if total_raw <= 0:
            return {}

        # First pass: proportional normalization
        normalized: dict[str, float] = {}
        for instrument, raw_w in raw_weights.items():
            normalized[instrument] = (raw_w / total_raw) * target_total

        # Second pass: cap positions and redistribute excess
        capped: dict[str, float] = {}
        uncapped: dict[str, float] = {}
        excess = 0.0

        for instrument, weight in normalized.items():
            if weight > max_single:
                excess += weight - max_single
                capped[instrument] = max_single
            else:
                uncapped[instrument] = weight

        if excess > 1e-10 and uncapped:
            uncapped_total = sum(uncapped.values())
            for instrument in uncapped:
                uncapped[instrument] += excess * (uncapped[instrument] / uncapped_total)

        capped.update(uncapped)
        return capped
