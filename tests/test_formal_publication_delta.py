from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.artifacts.formal_publication_delta import (
    FormalPublicationDeltaError,
    PublicationRoots,
    classify_publication_delta,
)
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _roots(tmp_path: Path, name: str, *, stamp: str) -> PublicationRoots:
    base = tmp_path / name
    roots = PublicationRoots(
        formal=base / "formal",
        preview=base / "preview",
        market_evidence=base / "market-evidence",
        model_data=base / "model-data",
    )
    freshness = {
        "schema_version": "1.0.0",
        "cutoff_policy": "governed_benchmark_market_session",
        "declared_at": stamp,
        "markets": {"cn": "2026-08-21", "us": "2026-08-21"},
        "next_session_close_utc": {
            "cn": "2026-08-24T08:30:00+00:00",
            "us": "2026-08-24T23:30:00+00:00",
        },
        "required_models": ["cn_x1_2"],
        "date_range_end_required_models": ["cn_x1_2"],
        "freshness_receipt_required_models": ["cn_x1_2"],
        "research_only": True,
        "trade_ready": False,
    }
    _write(roots.formal / "freshness.json", freshness)
    _write(
        roots.formal / "catalog.json",
        {"model_version_id": "cn_x1_2", "evidence_cutoff": "2026-08-21"},
    )
    _write(
        roots.formal / "evidence.json",
        {
            "metrics": {"total_return": 1.5},
            "lineage": {"pool": "cn_selected_equities_v3"},
            "research_only": True,
            "trade_ready": False,
        },
    )
    _write(
        roots.preview / "catalog.json",
        {"model_version_id": "cn_x1_2", "bundle_id": "a" * 64},
    )
    _write(
        roots.market_evidence / "cn" / "catalog.json",
        {
            "provider_identity_sha256": "b" * 64,
            "lifecycle_contract_sha256": "c" * 64,
        },
    )
    freshness_sha = _sha(roots.formal / "freshness.json")
    _write(
        roots.formal / "formal-bundle-v2-sync-receipt.json",
        {
            "schema_version": "2.0.0",
            "status": "active_formal_bundle_v2_built",
            "publication_input": "active_preview_bundle_v2",
            "active_strategy_ids": ["cn_x"],
            "active_model_version_ids": ["cn_x1_2"],
            "native_promoted_model_ids": ["cn_x1_2"],
            "retained_inactive_model_version_ids": [],
            "retained_formal_manifests": {},
            "preview_catalog_sha256": _sha(roots.preview / "catalog.json"),
            "freshness_source_sha256": freshness_sha,
            "strategy_catalog_sha256": "d" * 64,
            "formal_bundle_v2_catalog_sha256": _sha(roots.formal / "catalog.json"),
            "formal_bundle_v2_freshness_sha256": freshness_sha,
            "model_selection_reopened": False,
            "historical_evidence_recomputed": False,
            "research_only": True,
            "trade_ready": False,
        },
    )

    _write(roots.model_data / "data-components.json", {"components": ["cn"]})
    _write(roots.model_data / "training-profiles.json", {"profiles": ["cn"]})
    readiness = {
        "schema_version": "1.1",
        "built_at": stamp,
        "bundle_id": "e" * 64,
        "evidence_cutoff": "2026-08-21",
        "summary": {"ready_component_count": 1},
        "research_only": True,
        "trade_ready": False,
    }
    _write(roots.model_data / "model-data-readiness.json", readiness)
    _write(
        roots.model_data / "model-data-bundle.json",
        {
            "schema_version": "1.1",
            "built_at": stamp,
            "bundle_id": "e" * 64,
            "components": [{"component_id": "prices.cn", "manifest_sha256": "f" * 64}],
            "contract_id": "model_data_bundle_v1",
            "contract_path": "configs/data_contracts/model_data_bundle_v1.yaml",
            "contract_sha256": "1" * 64,
            "evidence_cutoff": "2026-08-21",
            "frontend_indexes": {
                "data_components": {
                    "path": "data-components.json",
                    "sha256": _sha(roots.model_data / "data-components.json"),
                },
                "model_data_readiness": {
                    "path": "model-data-readiness.json",
                    "sha256": _sha(roots.model_data / "model-data-readiness.json"),
                },
                "training_profiles": {
                    "path": "training-profiles.json",
                    "sha256": _sha(roots.model_data / "training-profiles.json"),
                },
            },
            "summary": {"ready_component_count": 1},
            "training_profiles": [{"profile_id": "cn_selected_price_only_v1"}],
            "research_only": True,
            "trade_ready": False,
        },
    )
    return roots


def _documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = {
        "schema_version": "formal_refresh_plan_v5",
        "refresh_required": False,
        "execution_task_matrix": [],
        "active_strategy_ids": ["cn_x"],
        "active_model_version_ids": ["cn_x1_2"],
        "stale_model_ids": [],
        "mtm_refresh_model_ids": [],
        "planned_noop_strategy_ids": ["cn_x"],
        "target_cutoffs": {"cn": "2026-08-21", "us": "2026-08-21"},
        "research_only": True,
        "trade_ready": False,
    }
    fan_in = {
        "schema_version": "formal_strategy_fan_in_v2",
        "status": "complete",
        "expected_strategy_ids": ["cn_x"],
        "executed_strategy_ids": [],
        "planned_noop_strategy_ids": ["cn_x"],
        "changed_strategy_ids": [],
        "retained_strategy_ids": [],
        "research_only": True,
        "trade_ready": False,
    }
    refresh = {
        "schema_version": "formal_refresh_receipt_v2",
        "status": "candidate_ready_for_review",
        "target_cutoffs": {"cn": "2026-08-21", "us": "2026-08-21"},
        "active_strategy_ids": ["cn_x"],
        "active_model_version_ids": ["cn_x1_2"],
        "research_only": True,
        "trade_ready": False,
    }
    return plan, fan_in, refresh


def _classify(
    current: PublicationRoots,
    candidate: PublicationRoots,
    *,
    documents: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan, fan_in, refresh = documents or _documents()
    return classify_publication_delta(
        current=current,
        candidate=candidate,
        plan=plan,
        fan_in=fan_in,
        refresh_receipt=refresh,
    )


def _rewrite_sync_freshness_digest(roots: PublicationRoots) -> None:
    path = roots.formal / "formal-bundle-v2-sync-receipt.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    digest = _sha(roots.formal / "freshness.json")
    value["freshness_source_sha256"] = digest
    value["formal_bundle_v2_freshness_sha256"] = digest
    _write(path, value)


def test_byte_identical_publication_is_semantic_no_change(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T15:00:00Z")

    receipt = _classify(current, candidate)

    assert receipt["status"] == "semantic_no_change"
    assert receipt["publication_required"] is False
    assert receipt["semantic_changed_path_count"] == 0
    assert receipt["raw_metadata_only_path_count"] == 0


def test_known_build_timestamp_churn_is_semantic_no_change(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")

    receipt = _classify(current, candidate)

    assert receipt["status"] == "semantic_no_change"
    assert receipt["publication_required"] is False
    assert set(receipt["raw_metadata_only_paths"]) == {
        "formal/formal-bundle-v2-sync-receipt.json",
        "formal/freshness.json",
        "model_data/model-data-bundle.json",
        "model_data/model-data-readiness.json",
    }


@pytest.mark.parametrize(
    ("root_id", "relative", "field", "value"),
    (
        ("formal", "evidence.json", "metrics", {"total_return": 1.6}),
        ("preview", "catalog.json", "model_version_id", "cn_x1_3"),
        ("market_evidence", "cn/catalog.json", "provider_identity_sha256", "9" * 64),
        ("model_data", "data-components.json", "components", ["cn", "us"]),
    ),
)
def test_governed_evidence_change_requires_publication(
    tmp_path: Path,
    root_id: str,
    relative: str,
    field: str,
    value: object,
) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")
    path = candidate.by_id()[root_id] / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    _write(path, payload)

    receipt = _classify(current, candidate)

    assert receipt["publication_required"] is True
    assert f"{root_id}/{relative}" in receipt["semantic_changed_paths"]


def test_cutoff_change_requires_publication(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")
    path = candidate.formal / "freshness.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["markets"]["cn"] = "2026-08-22"
    _write(path, payload)
    _rewrite_sync_freshness_digest(candidate)

    receipt = _classify(current, candidate)

    assert receipt["publication_required"] is True
    assert "formal/freshness.json" in receipt["semantic_changed_paths"]


def test_missing_or_extra_file_requires_publication(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")
    _write(candidate.market_evidence / "cn" / "new-symbol.json", {"symbol": "000001"})

    receipt = _classify(current, candidate)

    assert receipt["publication_required"] is True
    assert "market_evidence/cn/new-symbol.json" in receipt["semantic_changed_paths"]


def test_forged_derived_digest_fails_closed(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")
    path = candidate.model_data / "model-data-bundle.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["frontend_indexes"]["model_data_readiness"]["sha256"] = "0" * 64
    _write(path, payload)

    with pytest.raises(FormalPublicationDeltaError, match="readiness digest"):
        _classify(current, candidate)


def test_refresh_required_plan_never_short_circuits_publication(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T15:00:00Z")
    plan, fan_in, refresh = _documents()
    plan["refresh_required"] = True
    plan["execution_task_matrix"] = [{"strategy_id": "cn_x"}]

    receipt = _classify(current, candidate, documents=(plan, fan_in, refresh))

    assert receipt["publication_required"] is True
    assert receipt["reason"] == "plan_requires_refresh"


def test_degraded_fan_in_never_short_circuits_publication(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T15:00:00Z")
    plan, fan_in, refresh = _documents()
    fan_in["status"] = "degraded"
    fan_in["retained_strategy_ids"] = ["cn_x"]

    receipt = _classify(current, candidate, documents=(plan, fan_in, refresh))

    assert receipt["publication_required"] is True
    assert receipt["reason"] == "fan_in_not_semantically_idle"


def test_unknown_projected_document_field_fails_closed(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")
    path = candidate.formal / "freshness.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown_clock"] = "unsafe-to-ignore"
    _write(path, payload)
    _rewrite_sync_freshness_digest(candidate)

    with pytest.raises(FormalPublicationDeltaError, match="unsupported publication fields"):
        _classify(current, candidate)


def test_research_boundary_change_fails_closed(tmp_path: Path) -> None:
    current = _roots(tmp_path, "current", stamp="2026-08-23T15:00:00Z")
    candidate = _roots(tmp_path, "candidate", stamp="2026-08-23T16:00:00Z")
    path = candidate.model_data / "model-data-readiness.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["trade_ready"] = True
    _write(path, payload)
    bundle_path = candidate.model_data / "model-data-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["frontend_indexes"]["model_data_readiness"]["sha256"] = _sha(path)
    _write(bundle_path, bundle)

    with pytest.raises(FormalPublicationDeltaError, match="invalid research boundary"):
        _classify(current, candidate)
