from __future__ import annotations

import hashlib
import json

import pytest

from src.artifacts.operating_acceptance import build_acceptance_report
from src.artifacts.operating_review_declarations import (
    compute_declaration_digest,
    record_declaration,
    verify_declarations,
)

RUN_ID = 1
ATTEMPT = 1
DAY = "2026-10-14"
IDENTITY = f"{RUN_ID}:{ATTEMPT}"


def _binding(root, name):
    path = root / name
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _scenario(tmp_path, *, observation=None, blockers=None):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    row = observation or {
        "schema_version": "operating_observation_v1",
        "run_id": RUN_ID,
        "run_attempt": ATTEMPT,
        "head_sha": "a" * 40,
        "research_only": True,
        "trade_ready": False,
        "expected_cutoffs": {"us": DAY},
        "actual_cutoffs": {"us": DAY},
        "collection_blockers": blockers or [],
    }
    (evidence / "operating-observation.json").write_text(json.dumps(row))
    final = {
        "run": {
            "id": RUN_ID, "run_attempt": ATTEMPT, "head_sha": "a" * 40, "status": "completed",
            "conclusion": "success", "path": ".github/workflows/formal-backtest-refresh.yml",
        },
        "jobs": [{"status": "completed"}],
    }
    (evidence / "final.json").write_text(json.dumps(final))
    (evidence / "operations.json").write_text(json.dumps({"records": []}))
    (evidence / "plan.json").write_text(json.dumps({"tasks": []}))
    (evidence / "decision.json").write_text(json.dumps({"signal": {}}))
    draft = {
        IDENTITY: {
            "observation_sha256": hashlib.sha256((evidence / "operating-observation.json").read_bytes()).hexdigest(),
            "manual_interventions": None,
            "reviewed_by": None,
            "cadence_and_freshness_verified": False,
            "final_actions_metadata": _binding(evidence, "final.json"),
            "operations_snapshot": _binding(evidence, "operations.json"),
            "operating_inputs": {"plan": _binding(evidence, "plan.json")},
            "decision_delivery_evidence": [{"strategy_id": "stub", "decision": _binding(evidence, "decision.json")}],
        }
    }
    (evidence / "review-draft.json").write_text(json.dumps(draft))
    return evidence, draft[IDENTITY]


def _record(evidence, review, store, **overrides):
    values = {
        "observation_path": evidence / "operating-observation.json",
        "evidence": review,
        "evidence_root": evidence,
        "declarations_path": store,
        "reviewed_by": "owner",
        "manual_interventions": 0,
        "cadence_and_freshness_verified": True,
        "reviewed_at": "2026-10-15T00:00:00Z",
    }
    values.update(overrides)
    return record_declaration(**values)


def test_valid_declaration_is_counted(tmp_path, monkeypatch):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    assert _record(evidence, review, store)["status"] == "recorded"
    monkeypatch.setattr("src.artifacts.operating_acceptance._review_strategies", lambda *args: [])
    report = build_acceptance_report(evidence, declarations=store, through=DAY)
    assert report["markets"]["us"]["qualified_sessions"] == 1
    assert report["markets"]["us"]["sessions"][0]["status"] == "qualified"
    assert report["manual_interventions"] == {IDENTITY: 0}


def test_wrong_observation_hash_is_refused(tmp_path):
    evidence, review = _scenario(tmp_path)
    review["observation_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="observation hash"):
        _record(evidence, review, evidence / "reviews.json")
    assert not (evidence / "reviews.json").exists()


def test_bound_file_drift_is_refused(tmp_path):
    evidence, review = _scenario(tmp_path)
    (evidence / "operations.json").write_text(json.dumps({"records": [{"tampered": True}]}))
    with pytest.raises(ValueError, match="bound evidence hash mismatch"):
        _record(evidence, review, evidence / "reviews.json")


def test_bound_file_drift_after_recording_fails_acceptance_and_verify(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    (evidence / "operations.json").write_text(json.dumps({"records": [{"tampered": True}]}))
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_declarations(store)
    with pytest.raises(ValueError, match="hash mismatch"):
        build_acceptance_report(evidence, declarations=store, through=DAY)


def test_duplicate_conflicting_declaration_is_refused(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    before = store.read_bytes()
    with pytest.raises(ValueError, match="conflicting declaration"):
        _record(evidence, review, store, manual_interventions=1)
    assert store.read_bytes() == before


def test_identical_rerecord_is_idempotent(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    first = _record(evidence, review, store)
    before = store.read_bytes()
    second = _record(evidence, review, store, reviewed_at="2026-10-16T12:00:00Z")
    assert first["status"] == "recorded"
    assert second["status"] == "unchanged"
    assert store.read_bytes() == before


@pytest.mark.parametrize("reviewed_by", ["", "   ", None, 7])
def test_empty_or_invalid_reviewer_is_refused(tmp_path, reviewed_by):
    evidence, review = _scenario(tmp_path)
    with pytest.raises(ValueError, match="reviewed_by"):
        _record(evidence, review, evidence / "reviews.json", reviewed_by=reviewed_by)


@pytest.mark.parametrize("manual", [None, -1, True, 1.0])
def test_missing_or_invalid_manual_interventions_is_refused(tmp_path, manual):
    evidence, review = _scenario(tmp_path)
    with pytest.raises(ValueError, match="manual_interventions"):
        _record(evidence, review, evidence / "reviews.json", manual_interventions=manual)


def test_cadence_assertion_is_required(tmp_path):
    evidence, review = _scenario(tmp_path)
    with pytest.raises(ValueError, match="cadence_and_freshness_verified"):
        _record(evidence, review, evidence / "reviews.json", cadence_and_freshness_verified=False)


def test_run_identity_mismatch_is_refused(tmp_path):
    evidence, review = _scenario(tmp_path)
    with pytest.raises(ValueError, match="run identity"):
        _record(evidence, review, evidence / "reviews.json", run_id=2, run_attempt=ATTEMPT)


def test_observation_research_boundary_is_enforced(tmp_path):
    evidence, review = _scenario(tmp_path, observation={
        "schema_version": "operating_observation_v1", "run_id": RUN_ID, "run_attempt": ATTEMPT,
        "research_only": False, "trade_ready": False,
    })
    with pytest.raises(ValueError, match="research boundary"):
        _record(evidence, review, evidence / "reviews.json")


def test_verify_detects_tampered_observation(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    row = json.loads((evidence / "operating-observation.json").read_text())
    row["head_sha"] = "b" * 40
    (evidence / "operating-observation.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="observation hash mismatch"):
        verify_declarations(store)


def test_verify_detects_tampered_declaration(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    payload = json.loads(store.read_text())
    payload[IDENTITY]["manual_interventions"] = 3
    store.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="declaration digest mismatch"):
        verify_declarations(store)


def test_verify_detects_missing_binding(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    (evidence / "decision.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        verify_declarations(store)


def test_store_is_deterministically_formatted(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    raw = store.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert raw == json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert parsed[IDENTITY]["declaration_digest"] == compute_declaration_digest(parsed[IDENTITY])
    assert parsed[IDENTITY]["research_only"] is True
    assert parsed[IDENTITY]["trade_ready"] is False


def test_verify_summary_reports_every_declaration(tmp_path):
    evidence, review = _scenario(tmp_path)
    store = evidence / "reviews.json"
    _record(evidence, review, store)
    summary = verify_declarations(store)
    assert summary["declaration_count"] == 1
    assert summary["identities"] == [IDENTITY]
    assert summary["research_only"] is True and summary["trade_ready"] is False
