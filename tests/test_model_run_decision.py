from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.artifacts.model_run_decision import (
    ModelRunDecisionError,
    build_decision,
    validate_bound_decision,
)
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, sha256_bytes

FIXTURE = Path("tests/fixtures/model_run_bundle_v2")


def _manifest() -> dict:
    return json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


def _decision(manifest: dict) -> dict:
    summary = next(
        row for row in manifest["sections"] if row["section_id"] == "summary"
    )
    source = {
        "source_path": summary["path"],
        "source_sha256": summary["sha256"],
    }
    return {
        "schema_version": "2.0.0",
        "run_id": manifest["run_id"],
        "bundle_id": manifest["bundle_id"],
        "verdict": "supported",
        "status": "completed",
        "gates": [
            {
                "claim_id": "minimum-evidence",
                "outcome": "passed",
                "statement": "The declared summary satisfies the reviewed evidence gate.",
                **source,
            }
        ],
        "supporting_evidence": [
            {
                "claim_id": "summary-identity",
                "outcome": "passed",
                "statement": "The canonical summary is bound to the immutable run identity.",
                **source,
            }
        ],
        "contradictory_evidence": [],
        "interpretation_limits": [
            "The receipt evaluates only the declared research gate."
        ],
        "failure_modes": ["Future evidence may invalidate this conclusion."],
        "next_permitted_validation_step": "Validate the same gate on one additional held-out window.",
        "research_only": True,
        "trade_ready": False,
    }


def test_decision_binds_every_claim_to_available_manifest_sections() -> None:
    manifest = _manifest()
    validate_bound_decision(manifest, _decision(manifest))


def test_decision_rejects_hash_or_verdict_drift() -> None:
    manifest = _manifest()
    wrong_hash = _decision(manifest)
    wrong_hash["gates"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ModelRunDecisionError, match="hash mismatch"):
        validate_bound_decision(manifest, wrong_hash)

    inconsistent = _decision(manifest)
    inconsistent["gates"][0]["outcome"] = "failed"
    with pytest.raises(ModelRunDecisionError, match="all gates passed"):
        validate_bound_decision(manifest, inconsistent)


def test_pending_and_action_language_fail_closed() -> None:
    manifest = _manifest()
    pending = _decision(manifest)
    pending["status"] = "pending_review"
    with pytest.raises(ModelRunDecisionError, match="must remain blocked"):
        validate_bound_decision(manifest, pending)

    actionable = _decision(manifest)
    actionable["next_permitted_validation_step"] = "Buy after the next report."
    with pytest.raises(ModelRunDecisionError, match="trading-action"):
        validate_bound_decision(manifest, actionable)


def test_builder_writes_canonical_immutable_receipt(tmp_path: Path) -> None:
    manifest = _manifest()
    decision = _decision(manifest)
    manifest_path = tmp_path / "manifest.json"
    draft_path = tmp_path / "draft.json"
    output_path = tmp_path / "decision.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    draft_path.write_text(json.dumps(decision), encoding="utf-8")

    receipt = build_decision(
        manifest_path=manifest_path,
        draft_path=draft_path,
        output_path=output_path,
    )
    assert output_path.read_bytes() == canonical_json_bytes(decision)
    assert receipt["sha256"] == sha256_bytes(output_path.read_bytes())
    assert receipt["bundle_id"] == manifest["bundle_id"]
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False


def test_blocked_receipt_requires_blocked_gate() -> None:
    manifest = _manifest()
    decision = copy.deepcopy(_decision(manifest))
    decision["verdict"] = "blocked"
    decision["status"] = "pending_review"
    decision["gates"][0]["outcome"] = "blocked"
    validate_bound_decision(manifest, decision)

    decision["gates"][0]["outcome"] = "passed"
    with pytest.raises(ModelRunDecisionError, match="blocked gate"):
        validate_bound_decision(manifest, decision)
