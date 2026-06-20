"""Tests for T48.4 -- fail-closed model registration and promotion.

Verifies that:
1. A model with failed walk-forward gets CANDIDATE or REJECTED stage
2. A model with missing metrics cannot be STAGING or RECOMMENDED
3. Evidence from another model is rejected
4. Promotion from CANDIDATE to STAGING requires walk-forward pass
5. Promotion from STAGING to RECOMMENDED requires inference + reconstruction
6. The stage enum rejects unknown stages
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.assistant.model_registry_index import (
    _MODEL_STAGES,
    ModelRegistryIndex,
    _has_finite_metrics,
    _normalize_stage,
    validate_evidence_binding,
    validate_stage_for_registration,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_registry.db"


@pytest.fixture
def registry(db_path):
    return ModelRegistryIndex(db_path=db_path)


def _make_entry(
    *,
    version_id: str = "us_model_20260101_120000",
    stage: str = "STAGING",
    market: str = "us",
    wf_passed: bool = True,
    metrics: dict | None = None,
    inference_passed: bool | None = None,
    wf_model_id: str | None = None,
) -> dict:
    """Helper to build a registration entry."""
    if metrics is None:
        metrics = {"annualized_return": 0.12, "max_drawdown": -0.08}
    entry = {
        "id": version_id,
        "tag": "test",
        "name": "test_model",
        "market": market,
        "type": "LGBModel",
        "path": "/tmp/model.pkl",
        "stage": stage,
        "backtest": {"metrics": metrics},
    }
    # Walk-forward data
    wf = {"gate_passed": wf_passed, "mean_ic": 0.05, "ic_ir": 0.5}
    if wf_model_id is not None:
        wf["model_id"] = wf_model_id
    entry["walk_forward"] = wf
    entry["gate_passed"] = wf_passed

    if inference_passed is not None:
        entry["inference_passed"] = inference_passed

    return entry


# ---------------------------------------------------------------------------
# Test 1: Stage enum rejects unknown stages
# ---------------------------------------------------------------------------


class TestStageEnum:
    """Only known stages should be accepted by _normalize_stage."""

    def test_valid_stages_accepted(self):
        for stage in _MODEL_STAGES:
            assert _normalize_stage(stage) == stage

    def test_case_insensitive(self):
        assert _normalize_stage("staging") == "STAGING"
        assert _normalize_stage("Recommended") == "RECOMMENDED"

    def test_unknown_stage_rejected(self):
        with pytest.raises(ValueError, match="Unknown model stage"):
            _normalize_stage("PRODUCTION")

    def test_empty_string_defaults_to_candidate(self):
        assert _normalize_stage("") == "CANDIDATE"
        assert _normalize_stage(None) == "CANDIDATE"

    def test_all_expected_stages_present(self):
        expected = {"CANDIDATE", "STAGING", "RECOMMENDED", "REJECTED", "SUPERSEDED"}
        assert _MODEL_STAGES == expected


# ---------------------------------------------------------------------------
# Test 2: Failed walk-forward produces CANDIDATE stage
# ---------------------------------------------------------------------------


class TestFailedWalkForward:
    """A model with failed walk-forward must never be STAGING or RECOMMENDED."""

    def test_failed_wf_downgrades_staging_to_candidate(self):
        entry = _make_entry(stage="STAGING", wf_passed=False)
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_failed_wf_downgrades_recommended_to_candidate(self):
        entry = _make_entry(
            stage="RECOMMENDED", wf_passed=False, inference_passed=True
        )
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_missing_wf_downgrades_staging_to_candidate(self):
        entry = _make_entry(stage="STAGING", wf_passed=False)
        entry.pop("walk_forward", None)
        # gate_passed is still False from _make_entry
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_no_wf_data_at_all_defaults_to_candidate(self):
        entry = {
            "id": "test_model",
            "stage": "STAGING",
            "market": "us",
            "backtest": {"metrics": {"return": 0.1}},
        }
        # No walk_forward, no gate_passed -- should default to CANDIDATE
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_candidate_stage_preserved_on_wf_fail(self):
        entry = _make_entry(stage="CANDIDATE", wf_passed=False)
        assert validate_stage_for_registration(entry) == "CANDIDATE"


# ---------------------------------------------------------------------------
# Test 3: Missing metrics prevents STAGING/RECOMMENDED
# ---------------------------------------------------------------------------


class TestMissingMetrics:
    """Missing or non-finite metrics must prevent STAGING or RECOMMENDED."""

    def test_empty_metrics_downgrades_to_candidate(self):
        entry = _make_entry(stage="STAGING", wf_passed=True, metrics={})
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_none_metrics_downgrades_to_candidate(self):
        entry = _make_entry(stage="STAGING", wf_passed=True, metrics=None)
        entry["backtest"] = {"metrics": None}
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_nan_metrics_downgrades_to_candidate(self):
        entry = _make_entry(
            stage="STAGING",
            wf_passed=True,
            metrics={"return": float("nan")},
        )
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_inf_metrics_downgrades_to_candidate(self):
        entry = _make_entry(
            stage="STAGING",
            wf_passed=True,
            metrics={"return": float("inf")},
        )
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_bool_metrics_downgrades_to_candidate(self):
        entry = _make_entry(
            stage="STAGING",
            wf_passed=True,
            metrics={"passed": True},
        )
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_valid_metrics_allows_staging(self):
        entry = _make_entry(
            stage="STAGING",
            wf_passed=True,
            metrics={"return": 0.12, "sharpe": 1.5},
        )
        assert validate_stage_for_registration(entry) == "STAGING"


# ---------------------------------------------------------------------------
# Test 4: RECOMMENDED requires inference pass
# ---------------------------------------------------------------------------


class TestRecommendedRequiresInference:
    """RECOMMENDED stage requires both walk-forward AND inference to pass."""

    def test_recommended_without_inference_downgrades(self):
        entry = _make_entry(
            stage="RECOMMENDED",
            wf_passed=True,
            inference_passed=False,
        )
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_recommended_with_inference_none_downgrades(self):
        entry = _make_entry(
            stage="RECOMMENDED",
            wf_passed=True,
            inference_passed=None,
        )
        assert validate_stage_for_registration(entry) == "CANDIDATE"

    def test_recommended_with_inference_pass_accepted(self):
        entry = _make_entry(
            stage="RECOMMENDED",
            wf_passed=True,
            inference_passed=True,
        )
        assert validate_stage_for_registration(entry) == "RECOMMENDED"


# ---------------------------------------------------------------------------
# Test 5: Evidence binding rejects cross-model evidence
# ---------------------------------------------------------------------------


class TestEvidenceBinding:
    """Evidence from another model must be rejected."""

    def test_wf_from_different_model_rejected(self):
        entry = _make_entry(
            version_id="us_model_20260101",
            wf_model_id="us_model_20251201",  # different model
        )
        errors = validate_evidence_binding(entry)
        assert any("belongs to model" in e for e in errors)

    def test_wf_from_same_model_accepted(self):
        entry = _make_entry(
            version_id="us_model_20260101",
            wf_model_id="us_model_20260101",
        )
        errors = validate_evidence_binding(entry)
        # Should not have model mismatch error
        assert not any("belongs to model" in e for e in errors)

    def test_empty_metrics_rejected(self):
        entry = _make_entry(metrics={})
        errors = validate_evidence_binding(entry)
        assert any("Metrics are missing" in e for e in errors)

    def test_empty_artifact_id_rejected(self):
        entry = _make_entry()
        entry["artifact_id"] = "  "
        errors = validate_evidence_binding(entry)
        assert any("artifact_id" in e for e in errors)

    def test_empty_market_rejected(self):
        entry = _make_entry(market="")
        errors = validate_evidence_binding(entry)
        assert any("market is empty" in e for e in errors)

    def test_valid_entry_no_errors(self):
        entry = _make_entry(version_id="m1", wf_model_id="m1")
        errors = validate_evidence_binding(entry)
        assert errors == []


# ---------------------------------------------------------------------------
# Test 6: Promotion requires correct gate evidence
# ---------------------------------------------------------------------------


class TestPromoteModel:
    """Promotion must follow the stage transition graph and require evidence."""

    def test_promote_candidate_to_staging_requires_wf(self, registry):
        entry = _make_entry(stage="CANDIDATE", wf_passed=False)
        entry["stage"] = "CANDIDATE"
        registry.upsert_entry(entry, validate=False)

        # Without walk_forward_passed evidence, promotion should fail
        result = registry.promote_model(
            entry["id"],
            target_stage="STAGING",
            evidence={},
        )
        assert result["ok"] is False
        assert "walk_forward_passed" in result["reason"]

    def test_promote_candidate_to_staging_succeeds_with_wf(self, registry):
        entry = _make_entry(stage="CANDIDATE", wf_passed=False)
        entry["stage"] = "CANDIDATE"
        registry.upsert_entry(entry, validate=False)

        result = registry.promote_model(
            entry["id"],
            target_stage="STAGING",
            evidence={"walk_forward_passed": True},
        )
        assert result["ok"] is True
        assert result["stage"] == "STAGING"

        # Verify the DB was updated
        stored = registry.get_version(entry["id"])
        assert stored["stage"] == "STAGING"

    def test_promote_staging_to_recommended_requires_inference(self, registry):
        entry = _make_entry(stage="STAGING", wf_passed=True)
        registry.upsert_entry(entry, validate=False)

        # Without inference_passed, promotion should fail
        result = registry.promote_model(
            entry["id"],
            target_stage="RECOMMENDED",
            evidence={"walk_forward_passed": True},
        )
        assert result["ok"] is False
        assert "inference_passed" in result["reason"]

    def test_promote_staging_to_recommended_succeeds(self, registry):
        entry = _make_entry(stage="STAGING", wf_passed=True)
        registry.upsert_entry(entry, validate=False)

        result = registry.promote_model(
            entry["id"],
            target_stage="RECOMMENDED",
            evidence={
                "walk_forward_passed": True,
                "inference_passed": True,
            },
        )
        assert result["ok"] is True
        assert result["stage"] == "RECOMMENDED"

    def test_invalid_transition_rejected(self, registry):
        entry = _make_entry(stage="CANDIDATE", wf_passed=False)
        entry["stage"] = "CANDIDATE"
        registry.upsert_entry(entry, validate=False)

        # Cannot jump from CANDIDATE to RECOMMENDED
        result = registry.promote_model(
            entry["id"],
            target_stage="RECOMMENDED",
            evidence={
                "walk_forward_passed": True,
                "inference_passed": True,
            },
        )
        assert result["ok"] is False
        assert "Invalid transition" in result["reason"]

    def test_promote_nonexistent_model_fails(self, registry):
        result = registry.promote_model(
            "nonexistent_id",
            target_stage="STAGING",
            evidence={"walk_forward_passed": True},
        )
        assert result["ok"] is False
        assert "not found" in result["reason"]

    def test_unknown_target_stage_rejected(self, registry):
        entry = _make_entry(stage="CANDIDATE", wf_passed=False)
        entry["stage"] = "CANDIDATE"
        registry.upsert_entry(entry, validate=False)

        result = registry.promote_model(
            entry["id"],
            target_stage="PRODUCTION",
            evidence={},
        )
        assert result["ok"] is False
        assert "Unknown model stage" in result["reason"]

    def test_rejected_can_reenter_candidate(self, registry):
        entry = _make_entry(stage="REJECTED", wf_passed=False)
        entry["stage"] = "REJECTED"
        registry.upsert_entry(entry, validate=False)

        result = registry.promote_model(
            entry["id"],
            target_stage="CANDIDATE",
            evidence={},
        )
        assert result["ok"] is True
        assert result["stage"] == "CANDIDATE"

    def test_superseded_is_terminal(self, registry):
        entry = _make_entry(stage="SUPERSEDED", wf_passed=False)
        entry["stage"] = "SUPERSEDED"
        registry.upsert_entry(entry, validate=False)

        result = registry.promote_model(
            entry["id"],
            target_stage="CANDIDATE",
            evidence={},
        )
        assert result["ok"] is False
        assert "Invalid transition" in result["reason"]

    def test_promotion_preserves_other_fields(self, registry):
        entry = _make_entry(
            stage="CANDIDATE",
            wf_passed=False,
            version_id="preserve_test",
        )
        entry["stage"] = "CANDIDATE"
        registry.upsert_entry(entry, validate=False)

        registry.promote_model(
            "preserve_test",
            target_stage="STAGING",
            evidence={"walk_forward_passed": True},
        )

        stored = registry.get_version("preserve_test")
        assert stored["name"] == "test_model"
        assert stored["market"] == "us"
        assert stored["stage"] == "STAGING"


# ---------------------------------------------------------------------------
# Test 7: _has_finite_metrics helper
# ---------------------------------------------------------------------------


class TestHasFiniteMetrics:
    """Unit tests for the _has_finite_metrics helper."""

    def test_none_returns_false(self):
        assert _has_finite_metrics(None) is False

    def test_empty_dict_returns_false(self):
        assert _has_finite_metrics({}) is False

    def test_non_dict_returns_false(self):
        assert _has_finite_metrics("not a dict") is False

    def test_all_nan_returns_false(self):
        assert _has_finite_metrics({"a": float("nan")}) is False

    def test_all_inf_returns_false(self):
        assert _has_finite_metrics({"a": float("inf")}) is False

    def test_bool_only_returns_false(self):
        assert _has_finite_metrics({"passed": True}) is False

    def test_one_finite_returns_true(self):
        assert _has_finite_metrics({"return": 0.1, "bad": float("nan")}) is True

    def test_integer_value_returns_true(self):
        assert _has_finite_metrics({"count": 42}) is True


# ---------------------------------------------------------------------------
# Test 8: Backward compatibility -- upsert_entry with validate=False
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """upsert_entry with validate=False must accept any valid stage."""

    def test_validate_false_accepts_staging(self, registry):
        entry = _make_entry(stage="STAGING", wf_passed=False)
        assert registry.upsert_entry(entry, validate=False) is True
        stored = registry.get_version(entry["id"])
        assert stored["stage"] == "STAGING"

    def test_validate_true_downgrades_staging(self, registry):
        entry = _make_entry(stage="STAGING", wf_passed=False)
        assert registry.upsert_entry(entry, validate=True) is True
        stored = registry.get_version(entry["id"])
        assert stored["stage"] == "CANDIDATE"

    def test_default_validate_is_true(self, registry):
        entry = _make_entry(stage="STAGING", wf_passed=False)
        # Default should apply validation
        assert registry.upsert_entry(entry) is True
        stored = registry.get_version(entry["id"])
        assert stored["stage"] == "CANDIDATE"


# ---------------------------------------------------------------------------
# Test 9: Integration -- register_model determines stage correctly
# ---------------------------------------------------------------------------


class TestRegisterModelStageLogic:
    """register_model must assign stage based on walk-forward results."""

    def test_determine_stage_with_passed_wf(self):
        from src.research.registry import _determine_stage

        assert _determine_stage({"gate_passed": True}) == "STAGING"

    def test_determine_stage_with_failed_wf(self):
        from src.research.registry import _determine_stage

        assert _determine_stage({"gate_passed": False}) == "CANDIDATE"

    def test_determine_stage_with_no_wf(self):
        from src.research.registry import _determine_stage

        assert _determine_stage(None) == "CANDIDATE"
        assert _determine_stage({}) == "CANDIDATE"

    def test_determine_stage_with_missing_gate_key(self):
        from src.research.registry import _determine_stage

        assert _determine_stage({"mean_ic": 0.05}) == "CANDIDATE"
