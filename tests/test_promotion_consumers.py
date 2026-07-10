"""Schema-equivalence tests for thin PromotionDecision consumer views."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.research.promotion_consumers import (
    build_agent_decision_summary,
    build_frontend_promotion_view,
    build_model_decision_pack_view,
    build_registry_decision_record,
    load_promotion_payload,
    validate_promotion_payload,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _promotion(*, status: str = "stronger_research_candidate") -> dict[str, object]:
    trade_ready = status == "trade_guidance_candidate"
    return {
        "schema_version": "1.0",
        "subject_id": "run-42",
        "status": status,
        "trade_ready": trade_ready,
        "candidate": {
            "candidate": "lgbm:daily_ranker:test/original",
            "mean_icir": 0.25,
        },
        "failed_gates": [] if trade_ready else ["mean_icir"],
        "missing_evidence": [],
        "evidence_refs": [
            {
                "name": "execution_identity",
                "path": "execution_identity.json",
                "sha256": _sha("identity"),
            },
            {
                "name": "walk_forward_stability",
                "path": "walk_forward_stability.json",
                "sha256": _sha("stability"),
            },
        ],
        "contract_sha256": _sha("contract"),
        "thresholds": {"min_mean_icir": 0.3},
        "rationale": "Candidate remains research-only.",
        "research_only_warning": "Not authorization for trading.",
    }


def test_all_consumer_views_preserve_same_status_and_readiness() -> None:
    promotion = _promotion()
    model_pack = build_model_decision_pack_view(promotion)
    frontend = build_frontend_promotion_view(
        promotion,
        market="cn",
        benchmark="000300",
        run_status="passed",
    )
    registry = build_registry_decision_record(promotion)
    agent = build_agent_decision_summary(promotion)

    assert model_pack["decision"]["status"] == promotion["status"]
    assert frontend["decision_status"] == promotion["status"]
    assert registry["promotion_status"] == promotion["status"]
    assert agent["status"] == promotion["status"]

    assert model_pack["decision"]["trade_ready"] is False
    assert frontend["trade_ready"] is False
    assert registry["trade_ready"] is False
    assert agent["trade_ready"] is False
    assert agent["may_recompute_decision"] is False


def test_trade_guidance_status_is_consistent_across_views() -> None:
    promotion = _promotion(status="trade_guidance_candidate")
    views = (
        build_model_decision_pack_view(promotion)["decision"]["trade_ready"],
        build_frontend_promotion_view(
            promotion,
            market="us",
            benchmark="QQQ",
            run_status="passed",
        )["trade_ready"],
        build_registry_decision_record(promotion)["trade_ready"],
        build_agent_decision_summary(promotion)["trade_ready"],
    )
    assert views == (True, True, True, True)


def test_frontend_metadata_carries_evidence_without_recomputing() -> None:
    promotion = _promotion()
    frontend = build_frontend_promotion_view(
        promotion,
        market="cn",
        benchmark="000300",
        run_status="passed",
        metrics={"mean_icir": 999.0},
    )
    assert frontend["trade_ready"] is False
    assert frontend["metadata"]["decision_source"] == "promotion_decision"
    assert frontend["metadata"]["contract_sha256"] == promotion["contract_sha256"]
    assert frontend["metadata"]["evidence_refs"] == promotion["evidence_refs"]


def test_registry_record_contains_only_persistence_fields() -> None:
    record = build_registry_decision_record(_promotion())
    assert set(record) == {
        "promotion_status",
        "trade_ready",
        "promotion_contract_sha256",
        "promotion_evidence_refs",
        "promotion_artifact_path",
    }
    assert "failed_gates" not in record


def test_load_promotion_payload_from_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-42"
    run_dir.mkdir()
    path = run_dir / "promotion_decision.json"
    path.write_text(json.dumps(_promotion(), indent=2), encoding="utf-8")
    payload = load_promotion_payload(run_dir)
    assert payload["status"] == "stronger_research_candidate"
    assert payload["artifact_path"] == str(path.resolve())


def test_consumer_rejects_inconsistent_trade_ready() -> None:
    payload = _promotion()
    payload["trade_ready"] = True
    with pytest.raises(ValueError, match="trade_ready"):
        validate_promotion_payload(payload)


def test_consumer_rejects_invalid_evidence_hash() -> None:
    payload = _promotion()
    payload["evidence_refs"][0]["sha256"] = "not-a-sha"
    with pytest.raises(ValueError, match="SHA-256"):
        validate_promotion_payload(payload)
