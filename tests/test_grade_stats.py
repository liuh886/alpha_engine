"""Tests for grade stats table, screener counts, and evidence fields (reqs 39-41).

Tests that:
1. SignalPerformance.to_dict() includes all required evidence fields.
2. Direction-adjusted hit rate is computed correctly for buy and sell grades.
3. Confidence interval is computed correctly.
4. Qualification status is determined correctly.
5. Screener counts are computed correctly in API response structure.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.strategies.signal_grade_engine import (
    GRADES,
    MIN_OCCURRENCES_FOR_QUALIFICATION,
    SignalGradeEngine,
    SignalPerformance,
    compute_confidence_interval_95,
    compute_direction_adjusted_hit_rate,
    determine_qualification,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_perf(
    grade: str = "AAA",
    n: int = 20,
    mean_ret: float = 0.02,
    **kwargs,
) -> SignalPerformance:
    """Create a SignalPerformance with sensible defaults for testing."""
    rng = np.random.RandomState(42)
    returns = rng.normal(mean_ret, 0.01, n) if n > 0 else np.array([])
    arr = returns
    positive = int(np.sum(arr > 0)) if n > 0 else 0
    negative = int(np.sum(arr < 0)) if n > 0 else 0
    defaults = dict(
        grade=grade,
        total_occurrences=n,
        positive_count=positive,
        negative_count=negative,
        win_rate=positive / n if n > 0 else 0.0,
        mean_return=float(np.mean(arr)) if n > 0 else 0.0,
        cumulative_return=float(np.sum(arr)) / 10 if n > 0 else 0.0,
        median_return=float(np.median(arr)) if n > 0 else 0.0,
        max_return=float(np.max(arr)) if n > 0 else 0.0,
        min_return=float(np.min(arr)) if n > 0 else 0.0,
        avg_score=0.5,
    )
    defaults.update(kwargs)
    return SignalPerformance(**defaults)


def _make_pred_df(
    dates: list[str],
    instruments: list[str],
    seed: int = 42,
) -> pd.DataFrame:
    """Create a synthetic prediction DataFrame with MultiIndex (datetime, instrument)."""
    rng = np.random.RandomState(seed)
    dt_index = pd.to_datetime(dates)
    idx = pd.MultiIndex.from_product([dt_index, instruments], names=["datetime", "instrument"])
    scores = rng.randn(len(idx))
    return pd.DataFrame({"score": scores}, index=idx)


def _make_price_df(
    instruments: list[str],
    start: str = "2025-12-01",
    periods: int = 60,
    daily_return: float = 0.002,
) -> pd.DataFrame:
    """Create synthetic price data with deterministic drift."""
    dates = pd.date_range(start, periods=periods, freq="B")
    data = {}
    for inst in instruments:
        prices = [100.0 * (1 + daily_return) ** i for i in range(periods)]
        data[inst] = prices
    return pd.DataFrame(data, index=dates)


# ===========================================================================
# 1. SignalPerformance.to_dict() includes all required fields
# ===========================================================================


class TestSignalPerformanceToDict:
    """Verify that to_dict() returns all evidence fields."""

    REQUIRED_FIELDS = [
        "grade",
        "grade_name",
        "total_occurrences",
        "positive_count",
        "negative_count",
        "win_rate",
        "mean_return",
        "cumulative_return",
        "median_return",
        "max_return",
        "min_return",
        "avg_score",
        "model_version_id",
        "policy_version",
        "direction_adjusted_hit_rate",
        "benchmark_excess_return",
        "cost_adjusted_return",
        "confidence_interval_95",
        "qualification_status",
        "failure_reasons",
    ]

    def test_to_dict_has_all_required_fields(self):
        """to_dict() must include every field listed in requirements 39-41."""
        perf = _make_perf()
        d = perf.to_dict()
        for field_name in self.REQUIRED_FIELDS:
            assert field_name in d, f"Missing field: {field_name}"

    def test_to_dict_is_json_serializable(self):
        """to_dict() output must be JSON-serializable."""
        perf = _make_perf()
        serialized = json.dumps(perf.to_dict())
        deserialized = json.loads(serialized)
        assert deserialized["grade"] == "AAA"

    def test_to_dict_confidence_interval_is_list(self):
        """confidence_interval_95 must be a 2-element list."""
        perf = _make_perf()
        d = perf.to_dict()
        ci = d["confidence_interval_95"]
        assert isinstance(ci, list)
        assert len(ci) == 2
        assert ci[0] <= ci[1]

    def test_to_dict_failure_reasons_is_list(self):
        """failure_reasons must be a list."""
        perf = _make_perf()
        d = perf.to_dict()
        assert isinstance(d["failure_reasons"], list)

    def test_to_dict_model_version_id_roundtrip(self):
        """model_version_id must survive serialization roundtrip."""
        perf = _make_perf(model_version_id="v2.1.0", policy_version="step10")
        d = perf.to_dict()
        assert d["model_version_id"] == "v2.1.0"
        assert d["policy_version"] == "step10"


# ===========================================================================
# 2. Direction-adjusted hit rate computation
# ===========================================================================


class TestDirectionAdjustedHitRate:
    """Verify direction-adjusted hit rate for buy and sell grades."""

    def test_buy_grade_positive_returns(self):
        """All positive returns for AAA → hit rate = 1.0."""
        returns = np.array([0.01, 0.02, 0.03, 0.04])
        rate = compute_direction_adjusted_hit_rate(returns, "AAA")
        assert rate == pytest.approx(1.0)

    def test_buy_grade_negative_returns(self):
        """All negative returns for AAA → hit rate = 0.0."""
        returns = np.array([-0.01, -0.02, -0.03])
        rate = compute_direction_adjusted_hit_rate(returns, "AAA")
        assert rate == pytest.approx(0.0)

    def test_sell_grade_negative_returns_are_hits(self):
        """All negative returns for VVV → hit rate = 1.0 (correctly predicted decline)."""
        returns = np.array([-0.01, -0.02, -0.03, -0.04])
        rate = compute_direction_adjusted_hit_rate(returns, "VVV")
        assert rate == pytest.approx(1.0)

    def test_sell_grade_positive_returns_are_misses(self):
        """All positive returns for VVV → hit rate = 0.0 (wrong direction)."""
        returns = np.array([0.01, 0.02, 0.03])
        rate = compute_direction_adjusted_hit_rate(returns, "VVV")
        assert rate == pytest.approx(0.0)

    def test_mixed_returns_buy_grade(self):
        """Mixed returns for AA: 3 positive out of 5 → 0.6."""
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
        rate = compute_direction_adjusted_hit_rate(returns, "AA")
        assert rate == pytest.approx(0.6)

    def test_empty_returns(self):
        """Empty returns array → hit rate = 0.0."""
        rate = compute_direction_adjusted_hit_rate(np.array([]), "AAA")
        assert rate == pytest.approx(0.0)

    def test_middle_zone_grade_returns_zero(self):
        """Grade not in AAA-AA-A-V-VV-VVV → hit rate = 0.0."""
        returns = np.array([0.01, 0.02])
        rate = compute_direction_adjusted_hit_rate(returns, "")
        assert rate == pytest.approx(0.0)


# ===========================================================================
# 3. Confidence interval computation
# ===========================================================================


class TestConfidenceInterval:
    """Verify confidence interval computation."""

    def test_ci_contains_mean(self):
        """95% CI must contain the sample mean."""
        rng = np.random.RandomState(42)
        returns = rng.normal(0.02, 0.01, 50)
        ci = compute_confidence_interval_95(returns)
        mean = float(np.mean(returns))
        assert ci[0] <= mean <= ci[1]

    def test_ci_width_decreases_with_sample_size(self):
        """Larger samples should produce narrower CI."""
        rng = np.random.RandomState(42)
        small = rng.normal(0.02, 0.01, 10)
        large = rng.normal(0.02, 0.01, 100)
        ci_small = compute_confidence_interval_95(small)
        ci_large = compute_confidence_interval_95(large)
        width_small = ci_small[1] - ci_small[0]
        width_large = ci_large[1] - ci_large[0]
        assert width_large < width_small

    def test_ci_single_observation(self):
        """Single observation → CI is [value, value]."""
        ci = compute_confidence_interval_95(np.array([0.05]))
        assert ci[0] == pytest.approx(0.05)
        assert ci[1] == pytest.approx(0.05)

    def test_ci_empty_returns(self):
        """Empty returns → CI is [0, 0]."""
        ci = compute_confidence_interval_95(np.array([]))
        assert ci == [0.0, 0.0]

    def test_ci_symmetric_for_normal_data(self):
        """For symmetric normal data, CI should be roughly symmetric around mean."""
        rng = np.random.RandomState(123)
        returns = rng.normal(0.0, 0.01, 100)
        ci = compute_confidence_interval_95(returns)
        mean = float(np.mean(returns))
        lower_dist = mean - ci[0]
        upper_dist = ci[1] - mean
        assert lower_dist == pytest.approx(upper_dist, rel=0.01)


# ===========================================================================
# 4. Qualification status determination
# ===========================================================================


class TestQualificationStatus:
    """Verify qualification status logic."""

    def test_zero_occurrences_is_excluded(self):
        """No occurrences → status = 'excluded'."""
        status, reasons = determine_qualification(0)
        assert status == "excluded"
        assert "no_signal_occurrences" in reasons

    def test_below_minimum_is_unqualified(self):
        """Fewer than MIN_OCCURRENCES → status = 'unqualified'."""
        status, reasons = determine_qualification(MIN_OCCURRENCES_FOR_QUALIFICATION - 1)
        assert status == "unqualified"
        assert any("insufficient" in r for r in reasons)

    def test_at_minimum_is_qualified(self):
        """Exactly MIN_OCCURRENCES → status = 'qualified'."""
        status, reasons = determine_qualification(MIN_OCCURRENCES_FOR_QUALIFICATION)
        assert status == "qualified"
        assert reasons == []

    def test_above_minimum_is_qualified(self):
        """More than MIN_OCCURRENCES → status = 'qualified'."""
        status, reasons = determine_qualification(50)
        assert status == "qualified"
        assert reasons == []

    def test_high_nan_ratio_is_failed(self):
        """Returns with >50% NaN → status = 'failed'."""
        returns = np.array([0.01, float("nan"), float("nan"), float("nan"), 0.02, float("nan"),
                            float("nan"), float("nan"), float("nan"), float("nan")])
        status, reasons = determine_qualification(10, returns)
        assert status == "failed"
        assert any("nan" in r.lower() for r in reasons)


# ===========================================================================
# 5. Screener counts computation
# ===========================================================================


class TestScreenerCounts:
    """Verify screener count logic used in API responses."""

    def test_grade_counts_structure(self):
        """Performance dict should have entries for all GRADES."""
        engine = SignalGradeEngine(step_size=2)
        dates = pd.date_range("2026-01-02", periods=30, freq="B").strftime("%Y-%m-%d").tolist()
        instruments = [f"STK_{i}" for i in range(6)]
        pred_df = _make_pred_df(dates, instruments, seed=123)

        perf = engine.compute_performance(
            symbol="STK_0",
            pred_df=pred_df,
            price_df=_make_price_df(instruments),
            forward_days=5,
        )
        # Should have all grades as keys
        assert set(perf.keys()) == set(GRADES)

    def test_all_grades_have_evidence_fields(self):
        """Every grade in performance dict must have evidence fields populated."""
        engine = SignalGradeEngine(step_size=2)
        dates = pd.date_range("2026-01-02", periods=30, freq="B").strftime("%Y-%m-%d").tolist()
        instruments = [f"STK_{i}" for i in range(6)]
        pred_df = _make_pred_df(dates, instruments, seed=123)

        perf = engine.compute_performance(
            symbol="STK_0",
            pred_df=pred_df,
            price_df=_make_price_df(instruments),
            forward_days=5,
        )
        for grade, p in perf.items():
            d = p.to_dict()
            assert "qualification_status" in d, f"Missing qualification_status for {grade}"
            assert "failure_reasons" in d, f"Missing failure_reasons for {grade}"
            assert "confidence_interval_95" in d
            assert "direction_adjusted_hit_rate" in d
            assert "benchmark_excess_return" in d
            assert "cost_adjusted_return" in d

    def test_screener_count_logic(self):
        """Simulate screener count logic used in API."""
        # Create performance with known qualification statuses
        perfs = {}
        perfs["AAA"] = _make_perf(grade="AAA", n=20)  # qualified
        perfs["AA"] = _make_perf(grade="AA", n=3)     # unqualified (< MIN)
        perfs["A"] = _make_perf(grade="A", n=0)       # excluded (0 occ)
        perfs["V"] = _make_perf(grade="V", n=10)      # qualified
        perfs["VV"] = _make_perf(grade="VV", n=0)     # excluded
        perfs["VVV"] = _make_perf(grade="VVV", n=15)  # qualified

        # Simulate the screener count logic from the API
        total = 0
        eligible = 0
        graded = 0
        unqualified = 0
        excluded = 0

        for g in GRADES:
            p = perfs.get(g)
            if p is None:
                continue
            total += p.total_occurrences
            if p.total_occurrences > 0:
                eligible += 1
            if p.total_occurrences >= MIN_OCCURRENCES_FOR_QUALIFICATION:
                graded += p.total_occurrences
            elif 0 < p.total_occurrences < MIN_OCCURRENCES_FOR_QUALIFICATION:
                unqualified += p.total_occurrences
            elif p.total_occurrences == 0:
                excluded += 1

        assert total == 20 + 3 + 0 + 10 + 0 + 15  # 48
        assert eligible == 4  # AAA, AA, V, VVV have >0 occurrences
        assert graded == 20 + 10 + 15  # 45 (AAA, V, VVV are qualified)
        assert unqualified == 3  # AA has 3 (< MIN)

    def test_compute_performance_with_model_version(self):
        """compute_performance populates model_version_id and policy_version."""
        engine = SignalGradeEngine(step_size=2)
        dates = pd.date_range("2026-01-02", periods=30, freq="B").strftime("%Y-%m-%d").tolist()
        instruments = [f"STK_{i}" for i in range(6)]
        pred_df = _make_pred_df(dates, instruments, seed=123)

        perf = engine.compute_performance(
            symbol="STK_0",
            pred_df=pred_df,
            price_df=_make_price_df(instruments),
            forward_days=5,
            model_version_id="lgbm_v1",
            policy_version="step2",
        )
        for grade, p in perf.items():
            assert p.model_version_id == "lgbm_v1"
            assert p.policy_version == "step2"

    def test_compute_performance_with_benchmark_excess(self):
        """compute_performance computes benchmark_excess_return."""
        engine = SignalGradeEngine(step_size=2)
        dates = pd.date_range("2026-01-02", periods=30, freq="B").strftime("%Y-%m-%d").tolist()
        instruments = [f"STK_{i}" for i in range(6)]
        pred_df = _make_pred_df(dates, instruments, seed=123)

        perf = engine.compute_performance(
            symbol="STK_0",
            pred_df=pred_df,
            price_df=_make_price_df(instruments),
            forward_days=5,
            benchmark_return=0.10,  # 10% annualized
        )
        for grade, p in perf.items():
            # benchmark_excess should be mean_return - per_period_benchmark
            per_period_bm = 0.10 * (5 / 252.0)
            expected = p.mean_return - per_period_bm
            assert p.benchmark_excess_return == pytest.approx(expected, abs=1e-8)

    def test_compute_performance_with_cost_adjustment(self):
        """compute_performance computes cost_adjusted_return."""
        engine = SignalGradeEngine(step_size=2)
        dates = pd.date_range("2026-01-02", periods=30, freq="B").strftime("%Y-%m-%d").tolist()
        instruments = [f"STK_{i}" for i in range(6)]
        pred_df = _make_pred_df(dates, instruments, seed=123)

        perf = engine.compute_performance(
            symbol="STK_0",
            pred_df=pred_df,
            price_df=_make_price_df(instruments),
            forward_days=5,
            cost_bps=20,  # 20 bps round-trip
        )
        cost_decimal = 20 / 10000.0
        for grade, p in perf.items():
            expected = p.mean_return - cost_decimal
            assert p.cost_adjusted_return == pytest.approx(expected, abs=1e-8)
