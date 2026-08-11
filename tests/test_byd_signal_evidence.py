"""Production-contract tests for BYD v1.3 signal evidence binding."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.research.byd_signal_evidence import (
    BYDSignalEvidenceError,
    bind_final_signal_identity,
    bind_manifest_observation_identity,
    close_evidence_is_current,
)
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID


def _observation() -> dict:
    return {
        "schema_version": "byd_v1_3_low_vol_prospective_v1",
        "candidate_model_id": MODEL_ID,
        "signal_date": "2026-08-10",
        "data_version": "v1-3-2026-08-10",
        "common_open_eligible": True,
        "source": {"recovery_event_observation_sha256": "a" * 64},
        "targets": {MODEL_ID: {"byd_weight": 0.75, "etf_weight": 0.25, "cash_weight": 0.0}},
        "champion": {"model_id": "byd_v1_2_convex_momentum_budget_v1"},
        "factors": {
            "market_state": "bear",
            "vol_state": "high",
            "mom_20": 0.01,
            "mom_60": -0.08,
            "drawdown_252": -0.20,
        },
    }


def _alert() -> dict:
    return {
        "fingerprint": "decision-identity",
        "markdown": "<!-- signal-fingerprint:decision-identity -->\n",
        "data_provenance": {
            "v1_3_source_manifest_sha256": "a" * 64,
            "source_observation_sha256": "b" * 64,
            "source_workflow": "byd-daily-signal-alert",
        },
        "factor_evidence": {
            "catalog_implementation_hash": "d" * 64,
            "source_sha256": "e" * 64,
        },
    }


def test_formal_close_freshness_uses_final_governed_observation_not_forward_label() -> None:
    observation = _observation()
    observation["prospective_eligible"] = False
    observation["prelaunch_seed"] = True
    assert close_evidence_is_current(observation) is True


def test_formal_close_freshness_accepts_exact_immutable_legacy_seed() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation.update(
        {
            "kind": "v1_3_low_vol_recovery_observation",
            "launch_after": "2026-08-10",
            "prelaunch_seed": True,
        }
    )
    assert close_evidence_is_current(observation) is True


def test_formal_close_freshness_rejects_missing_identity_after_legacy_seed() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation.update(
        {
            "kind": "v1_3_low_vol_recovery_observation",
            "launch_after": "2026-08-10",
            "prelaunch_seed": False,
            "signal_date": "2026-08-11",
        }
    )
    assert close_evidence_is_current(observation) is False


def test_manifest_hash_binds_immutable_observation_with_legacy_missing_field() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation["signal_date"] = "2026-08-11"
    bound = bind_manifest_observation_identity(
        observation,
        observation_sha256="a" * 64,
        manifest={
            "schema_version": observation["schema_version"],
            "candidate_model_id": MODEL_ID,
            "observation_sha256": {"2026-08-11": "a" * 64},
        },
    )
    assert bound["candidate_model_id"] == MODEL_ID
    assert "candidate_model_id" not in observation


def test_manifest_binding_rejects_unsealed_observation() -> None:
    with pytest.raises(BYDSignalEvidenceError, match="not sealed"):
        bind_manifest_observation_identity(
            _observation(),
            observation_sha256="b" * 64,
            manifest={
                "schema_version": "byd_v1_3_low_vol_prospective_v1",
                "candidate_model_id": MODEL_ID,
                "observation_sha256": {"2026-08-10": "a" * 64},
            },
        )


def test_close_freshness_fails_when_final_source_identity_is_missing() -> None:
    observation = _observation()
    observation["source"] = {}
    assert close_evidence_is_current(observation) is False


def test_close_freshness_fails_on_wrong_model_identity() -> None:
    observation = _observation()
    observation["candidate_model_id"] = "wrong"
    assert close_evidence_is_current(observation) is False


def test_final_fingerprint_binds_factor_and_source_identity() -> None:
    first = bind_final_signal_identity(deepcopy(_alert()))
    changed = _alert()
    changed["factor_evidence"]["catalog_implementation_hash"] = "f" * 64
    second = bind_final_signal_identity(changed)

    assert first["decision_fingerprint"] == second["decision_fingerprint"]
    assert first["fingerprint"] != second["fingerprint"]
    assert f"signal-fingerprint:{first['fingerprint']}" in first["markdown"]
    assert "signal-fingerprint:decision-identity" not in first["markdown"]
