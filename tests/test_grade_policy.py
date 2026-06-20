"""Tests for src/strategies/grade_policy.py — grade policy types and functions."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.strategies.grade_policy import (
    DEFAULT_POLICY,
    GradeObservation,
    GradePolicy,
    assign_grade,
    check_ordering,
    qualify_grade,
    validate_observation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obs(
    *,
    grade: str = "AAA",
    score: float = 0.05,
    percentile: float = 95.0,
    total_eligible: int = 200,
    asof_date: str = "2026-01-01",
    model_version_id: str = "m1",
    **overrides,
) -> GradeObservation:
    defaults = dict(
        model_version_id=model_version_id,
        run_id="run1",
        prediction_checksum=hashlib.sha256(asof_date.encode()).hexdigest(),
        snapshot_id="snap1",
        policy_version="v1",
        market="cn",
        universe_id="csi300",
        asof_date=asof_date,
        forecast_horizon_days=10,
        symbol="STOCK001",
        score=score,
        rank=1,
        percentile=percentile,
        grade=grade,
        total_eligible=total_eligible,
    )
    defaults.update(overrides)
    return GradeObservation(**defaults)


# ---------------------------------------------------------------------------
# 1. Grade assignment with default policy
# ---------------------------------------------------------------------------


class TestAssignGrade:
    def test_aaa_top_band(self):
        assert assign_grade(95.0) == "AAA"
        assert assign_grade(90.0) == "AAA"
        assert assign_grade(100.0) == "AAA"

    def test_aa_band(self):
        assert assign_grade(85.0) == "AA"
        assert assign_grade(80.0) == "AA"

    def test_a_band(self):
        assert assign_grade(75.0) == "A"
        assert assign_grade(70.0) == "A"

    def test_neutral_zone(self):
        assert assign_grade(50.0) == "neutral"
        assert assign_grade(40.0) == "neutral"
        assert assign_grade(60.0) == "neutral"

    def test_gap_regions_are_neutral(self):
        # Gap between A (70) and neutral (60)
        assert assign_grade(65.0) == "neutral"
        # Gap between neutral (40) and V (30)
        assert assign_grade(35.0) == "neutral"

    def test_v_band(self):
        # V band covers (0, 30), but VV (0,20) and VVV (0,10) are checked first.
        # Effective V range: 20-30.
        assert assign_grade(25.0) == "V"

    def test_vv_band(self):
        # VV band covers (0, 20), but VVV (0,10) is checked first.
        # Effective VV range: 10-20.
        assert assign_grade(15.0) == "VV"

    def test_vvv_band(self):
        assert assign_grade(0.0) == "VVV"
        assert assign_grade(1.0) == "VVV"

    def test_boundary_90_is_aaa(self):
        # 90 is in both AAA (90-100) and AA (80-90).  AAA should win because
        # we check buy-side from strongest first.
        assert assign_grade(90.0) == "AAA"

    def test_boundary_30_is_v(self):
        # 30 is in V (0-30) and neutral starts at 40, so 30 should be V.
        assert assign_grade(30.0) == "V"


# ---------------------------------------------------------------------------
# 2. Insufficient universe returns insufficient_universe
# ---------------------------------------------------------------------------


class TestInsufficientUniverse:
    def test_grade_insufficient_universe_is_not_valid(self):
        obs = _obs(grade="insufficient_universe", total_eligible=50)
        assert not validate_observation(obs)

    def test_small_universe_is_not_valid(self):
        obs = _obs(total_eligible=50)  # below min_universe=80
        assert not validate_observation(obs)

    def test_normal_universe_is_valid(self):
        obs = _obs(total_eligible=200)
        assert validate_observation(obs)


# ---------------------------------------------------------------------------
# 3. Observation validation
# ---------------------------------------------------------------------------


class TestObservationValidation:
    def test_valid_observation(self):
        obs = _obs(total_eligible=100, grade="AA")
        assert validate_observation(obs)

    def test_exactly_min_universe(self):
        obs = _obs(total_eligible=80, grade="A")
        assert validate_observation(obs)

    def test_one_below_min_universe(self):
        obs = _obs(total_eligible=79, grade="A")
        assert not validate_observation(obs)


# ---------------------------------------------------------------------------
# 4. Qualification with enough samples
# ---------------------------------------------------------------------------


class TestQualification:
    def test_qualifies_with_enough_observations(self):
        obs_list = [
            _obs(grade="AAA", score=0.03, asof_date=f"2026-01-{i:02d}")
            for i in range(1, 101)
        ]
        q = qualify_grade(obs_list, min_observations=100)
        assert q.qualified
        assert q.independent_observations == 100
        assert q.failure_reasons == []

    def test_qualification_returns_correct_grade(self):
        obs_list = [_obs(grade="VVV", score=-0.02, asof_date=f"2026-01-{i:02d}") for i in range(1, 51)]
        q = qualify_grade(obs_list, min_observations=20)
        assert q.grade == "VVV"
        assert q.qualified

    def test_qualification_computes_hit_rate(self):
        # AAA = buy-side, positive scores should produce high hit rate
        obs_list = [_obs(grade="AAA", score=0.05, asof_date=f"2026-01-{i:02d}") for i in range(1, 51)]
        q = qualify_grade(obs_list, min_observations=10)
        assert q.direction_adjusted_hit_rate == 1.0

    def test_qualification_ci_non_trivial(self):
        obs_list = [
            _obs(grade="A", score=0.01 * (i % 3), asof_date=f"2026-01-{i:02d}")
            for i in range(1, 101)
        ]
        q = qualify_grade(obs_list, min_observations=10)
        lo, hi = q.confidence_interval_95
        assert lo < q.mean_raw_return < hi


# ---------------------------------------------------------------------------
# 5. Qualification fails with too few samples
# ---------------------------------------------------------------------------


class TestQualificationFails:
    def test_fails_below_minimum(self):
        obs_list = [_obs(grade="AA", score=0.04, asof_date=f"2026-01-{i:02d}") for i in range(1, 11)]
        q = qualify_grade(obs_list, min_observations=100)
        assert not q.qualified
        assert "insufficient_observations" in q.failure_reasons[0]

    def test_fails_with_empty_list(self):
        q = qualify_grade([], min_observations=100)
        assert not q.qualified
        assert "no_observations" in q.failure_reasons[0]


# ---------------------------------------------------------------------------
# 6. Ordering check (positive and negative)
# ---------------------------------------------------------------------------


class TestOrderingCheck:
    def test_perfect_positive_ordering(self):
        mapping = {"VVV": -0.05, "VV": -0.03, "V": -0.01, "neutral": 0.0, "A": 0.01, "AA": 0.03, "AAA": 0.05}
        rho = check_ordering(mapping)
        assert rho > 0.99

    def test_perfect_negative_ordering(self):
        mapping = {"VVV": 0.05, "VV": 0.03, "V": 0.01, "neutral": 0.0, "A": -0.01, "AA": -0.03, "AAA": -0.05}
        rho = check_ordering(mapping)
        assert rho < -0.99

    def test_flat_returns_give_zero(self):
        mapping = {"AAA": 0.01, "AA": 0.01, "A": 0.01}
        rho = check_ordering(mapping)
        assert rho == 0.0

    def test_single_grade_returns_zero(self):
        assert check_ordering({"AAA": 0.05}) == 0.0

    def test_unknown_grades_ignored(self):
        mapping = {"AAA": 0.05, "bogus": 0.99, "VVV": -0.05}
        rho = check_ordering(mapping)
        assert rho > 0  # AAA (rank 6) has higher return than VVV (rank 0)


# ---------------------------------------------------------------------------
# 7. Tie-breaking determinism
# ---------------------------------------------------------------------------


class TestTieBreaking:
    def test_tie_policy_first_deterministic(self):
        p = GradePolicy(
            version="v1",
            bands=DEFAULT_POLICY.bands,
            neutral_band=DEFAULT_POLICY.neutral_band,
            tie_policy="first",
            market="cn",
        )
        assert p.tie_policy == "first"

    def test_tie_policy_last_deterministic(self):
        p = GradePolicy(
            version="v1",
            bands=DEFAULT_POLICY.bands,
            neutral_band=DEFAULT_POLICY.neutral_band,
            tie_policy="last",
            market="cn",
        )
        assert p.tie_policy == "last"

    def test_tie_policy_random_stored(self):
        p = GradePolicy(
            version="v1",
            bands=DEFAULT_POLICY.bands,
            neutral_band=DEFAULT_POLICY.neutral_band,
            tie_policy="random",
            market="cn",
        )
        assert p.tie_policy == "random"


# ---------------------------------------------------------------------------
# 8. Policy serialisation roundtrip
# ---------------------------------------------------------------------------


class TestPolicySerialization:
    def test_dict_roundtrip(self):
        d = DEFAULT_POLICY.to_dict()
        p2 = GradePolicy.from_dict(d)
        assert p2.version == DEFAULT_POLICY.version
        assert p2.bands == DEFAULT_POLICY.bands
        assert p2.neutral_band == DEFAULT_POLICY.neutral_band
        assert p2.min_universe == DEFAULT_POLICY.min_universe
        assert p2.market == DEFAULT_POLICY.market

    def test_json_roundtrip(self):
        j = DEFAULT_POLICY.to_json()
        p2 = GradePolicy.from_json(j)
        assert p2.version == DEFAULT_POLICY.version
        assert p2.to_dict() == DEFAULT_POLICY.to_dict()

    def test_frozen_dataclass(self):
        with pytest.raises(AttributeError):
            DEFAULT_POLICY.version = "v2"  # type: ignore[misc]

    def test_grade_observation_frozen(self):
        obs = _obs()
        with pytest.raises(AttributeError):
            obs.score = 999.0  # type: ignore[misc]

    def test_grade_qualification_frozen(self):
        obs_list = [_obs(asof_date=f"2026-01-{i:02d}") for i in range(1, 101)]
        q = qualify_grade(obs_list, min_observations=50)
        with pytest.raises(AttributeError):
            q.qualified = False  # type: ignore[misc]
