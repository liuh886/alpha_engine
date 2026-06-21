"""Tests for GradeWeightAssigner — grade → differentiated position weights."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.execution.grade_weight_assigner import GradeAllocation, GradeWeightAssigner
from src.execution.signal_execution_config import SignalExecutionConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> SignalExecutionConfig:
    return SignalExecutionConfig(
        step_size=10,
        long_fraction=0.8,
        short_fraction=0.2,
        max_single_position_weight=0.15,
        min_stocks_per_side=3,
        grade_weights={
            "AAA": 3.0, "AA": 2.0, "A": 1.0,
            "V": -1.0, "VV": -2.0, "VVV": -3.0,
        },
    )


@pytest.fixture
def assigner(default_config: SignalExecutionConfig) -> GradeWeightAssigner:
    return GradeWeightAssigner(default_config)


def _make_scores(n_stocks: int = 100, seed: int = 42) -> pd.Series:
    """Synthetic cross-sectional scores indexed by instrument."""
    rng = np.random.default_rng(seed)
    scores = rng.normal(0.0, 0.1, size=n_stocks)
    return pd.Series(
        scores,
        index=[f"STOCK_{i:03d}" for i in range(n_stocks)],
    )


# ---------------------------------------------------------------------------
# Grade assignment tests
# ---------------------------------------------------------------------------


class TestGradeAssignment:
    def test_all_grades_assigned(self, assigner: GradeWeightAssigner) -> None:
        """Large universe → all 6 grades represented."""
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15"
        )
        # With 200 stocks and step_size=10:
        # AAA=10, AA=20, A=30 = 60 long → all should have some
        # V=30, VV=20, VVV=10 = 60 short
        assert allocation.long_count >= 10
        assert allocation.short_count >= 10
        assert allocation.ungraded_count > 0  # middle zone

    def test_small_universe_scales_tiers(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """Small universe → tiers scaled proportionally by SignalGradeEngine."""
        scores = _make_scores(n_stocks=20, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15"
        )
        # 20 stocks, step_size adjusted to max(1, 20//6) = 3
        # AAA=3, AA=6, A=9 = should have some longs
        assert allocation.long_count > 0
        assert allocation.short_count > 0

    def test_empty_scores_returns_empty_allocation(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """Empty scores → empty allocation."""
        scores = pd.Series(dtype=float)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15"
        )
        assert allocation.long_count == 0
        assert allocation.short_count == 0
        assert not allocation.has_sufficient_stocks

    def test_all_nan_scores_returns_empty_allocation(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """All-NaN scores → empty allocation."""
        scores = pd.Series(
            [float("nan")] * 50,
            index=[f"STOCK_{i:03d}" for i in range(50)],
        )
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15"
        )
        assert allocation.long_count == 0
        assert allocation.short_count == 0


# ---------------------------------------------------------------------------
# Weight normalization tests
# ---------------------------------------------------------------------------


class TestWeightNormalization:
    def test_long_weights_sum_to_long_fraction(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """Long basket weights sum to long_fraction."""
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15", regime_factor=1.0,
        )
        long_sum = sum(allocation.long_positions.values())
        assert long_sum == pytest.approx(0.8, abs=0.01)
        assert len(allocation.long_positions) > 0

    def test_short_weights_sum_to_short_fraction(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """Short basket weights sum to short_fraction."""
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15", regime_factor=1.0,
        )
        short_sum = sum(allocation.short_positions.values())
        assert short_sum == pytest.approx(0.2, abs=0.01)
        assert len(allocation.short_positions) > 0

    def test_regime_factor_scales_allocation(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """regime_factor=0.5 → both baskets' total weights halved."""
        scores = _make_scores(n_stocks=200, seed=42)
        alloc_full = assigner.compute_allocation(
            scores, current_date="2024-06-15", regime_factor=1.0,
        )
        alloc_half = assigner.compute_allocation(
            scores, current_date="2024-06-15", regime_factor=0.5,
        )
        full_long_sum = sum(alloc_full.long_positions.values())
        half_long_sum = sum(alloc_half.long_positions.values())
        assert half_long_sum == pytest.approx(full_long_sum * 0.5, abs=0.01)

    def test_regime_factor_zero_means_all_cash(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """regime_factor=0.0 → both baskets empty."""
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15", regime_factor=0.0,
        )
        assert len(allocation.long_positions) == 0
        assert len(allocation.short_positions) == 0

    def test_long_only_mode_short_fraction_zero(self) -> None:
        """short_fraction=0.0 → no short positions."""
        config = SignalExecutionConfig(short_fraction=0.0)
        assigner = GradeWeightAssigner(config)
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15",
        )
        assert len(allocation.short_positions) == 0
        assert len(allocation.long_positions) > 0
        long_sum = sum(allocation.long_positions.values())
        assert long_sum == pytest.approx(0.8, abs=0.01)


# ---------------------------------------------------------------------------
# Position cap tests
# ---------------------------------------------------------------------------


class TestPositionCap:
    def test_no_position_exceeds_max_single(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """All positions ≤ max_single_position_weight."""
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15",
        )
        max_weight = max(
            list(allocation.long_positions.values())
            + list(allocation.short_positions.values()),
            default=0.0,
        )
        assert max_weight <= 0.15 + 1e-6  # tiny epsilon for float

    def test_tight_cap_applied_with_small_step_size(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """With step_size=1 (very concentrated baskets), cap dominates."""
        config = SignalExecutionConfig(
            step_size=1,
            long_fraction=0.8,
            max_single_position_weight=0.10,
            min_stocks_per_side=2,
        )
        assigner = GradeWeightAssigner(config)
        scores = _make_scores(n_stocks=100, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15",
        )
        # AAA=1 stock (step_size=1) → very concentrated
        max_w = max(allocation.long_positions.values(), default=0.0)
        assert max_w <= 0.10 + 1e-6


# ---------------------------------------------------------------------------
# Minimum stocks enforcement
# ---------------------------------------------------------------------------


class TestMinStocks:
    def test_insufficient_stocks_skips_side(self) -> None:
        """If < min_stocks_per_side, that side is empty."""
        config = SignalExecutionConfig(
            min_stocks_per_side=50,  # Very high threshold
        )
        assigner = GradeWeightAssigner(config)
        scores = _make_scores(n_stocks=30, seed=42)  # Only 30 stocks
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15",
        )
        assert len(allocation.long_positions) == 0
        assert len(allocation.short_positions) == 0
        assert not allocation.has_sufficient_stocks

    def test_sufficient_stocks_enables_allocation(
        self, assigner: GradeWeightAssigner
    ) -> None:
        """With enough stocks, both sides are active."""
        scores = _make_scores(n_stocks=200, seed=42)
        allocation = assigner.compute_allocation(
            scores, current_date="2024-06-15",
        )
        assert allocation.has_sufficient_stocks
        assert len(allocation.long_positions) > 0


# ---------------------------------------------------------------------------
# Frozen / immutability
# ---------------------------------------------------------------------------


class TestGradeAllocationImmutability:
    def test_grade_allocation_is_frozen(self) -> None:
        """GradeAllocation should be frozen."""
        alloc = GradeAllocation(
            date="2024-06-15",
            long_positions={}, short_positions={},
            long_count=0, short_count=0, ungraded_count=0,
            has_sufficient_stocks=False,
        )
        # Frozen dataclass prevents attribute reassignment
        with pytest.raises(Exception):
            alloc.long_positions = {"TEST": 0.1}  # type: ignore[misc]
