from __future__ import annotations

import hashlib
import json

import pytest

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, compute_bundle_id
from src.artifacts.pages_release_verification import (
    PublishedBundleArtifact,
    PublishedFormalRun,
    ReleaseVerificationError,
    validate_bundle_artifact_bytes,
    validate_bundle_manifest,
    validate_deployment,
    validate_formal_catalog,
    validate_formal_manifest,
    validate_formal_section,
    validate_shell,
)


def _catalog() -> dict[str, object]:
    records = [
        ("cn_ranker", "cn_x1_0", "cn_x1_0_run", "2026-08-03", "a"),
        ("qqq_rotation", "qqqi_qqq_tqqq_v4_2", "qqq_v4_2_run", "2026-07-31", "b"),
        ("us_ranker", "us_x1_1", "us_x1_1_run", "2026-07-31", "c"),
    ]
    return {
        "schema_version": "2.0.0",
        "channel": "formal",
        "generated_at": "2026-08-03T09:15:00Z",
        "research_only": True,
        "trade_ready": False,
        "records": [
            {
                "model_family_id": family,
                "model_version_id": version,
                "run_id": run,
                "bundle_id": character * 64,
                "manifest_path": f"{family}/{version}/{run}/manifest.json",
                "manifest_sha256": chr(ord(character) + 3) * 64,
                "evidence_cutoff": cutoff,
                "publication_status": "accepted_formal_baseline",
            }
            for family, version, run, cutoff, character in records
        ],
    }


def _formal_manifest() -> tuple[dict[str, object], bytes, bytes]:
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": "us_ranker",
        "model_version_id": "us_x1_1",
        "run_id": "us_x1_1_run",
        "display_name": "US x1.1",
        "source_package_sha256": "9" * 64,
        "research_only": True,
        "trade_ready": False,
        "metrics": [],
    }
    summary_bytes = canonical_json_bytes(summary)
    manifest: dict[str, object] = {
        "schema_version": "2.0.0",
        "model_family_id": "us_ranker",
        "model_version_id": "us_x1_1",
        "run_id": "us_x1_1_run",
        "model_kind": "cross_sectional_ranker",
        "publication_channel": "formal",
        "publication_status": "accepted_formal_baseline",
        "generated_at": "2026-08-03T09:15:00Z",
        "evidence_cutoff": "2026-07-31",
        "research_only": True,
        "trade_ready": False,
        "comparability_key": {
            "market": "us",
            "universe_id": "us87",
            "benchmark_id": "qqq",
            "start": "2024-01-01",
            "end": "2026-07-31",
            "trace_frequency": "daily",
            "horizon": "10d",
            "rebalance_contract_id": "weekly_v1",
            "cost_contract_id": "cost_v1",
        },
        "sections": [
            {
                "section_id": "summary",
                "availability_status": "available",
                "required_for_model_kind": True,
                "path": "summary.json",
                "sha256": hashlib.sha256(summary_bytes).hexdigest(),
                "byte_size": len(summary_bytes),
                "media_type": "application/json",
                "reason": None,
            },
            {
                "section_id": "risk",
                "availability_status": "not_retained",
                "required_for_model_kind": False,
                "path": None,
                "sha256": None,
                "byte_size": None,
                "media_type": None,
                "reason": "The accepted source did not retain a separate risk section.",
            },
        ],
    }
    manifest["bundle_id"] = compute_bundle_id(manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    return manifest, manifest_bytes, summary_bytes


def _bundle_fixture() -> tuple[dict[str, object], dict[str, bytes]]:
    models = json.dumps(
        [{"id": "us_x1_0"}, {"id": "us_x1_1"}, {"id": "cn_x1_0"}],
        separators=(",", ":"),
    ).encode()
    export = json.dumps(
        {
            "source": "repository_research_store",
            "research_only": True,
            "trade_ready": False,
            "blocked_gates": ["primary_run_curve_unavailable"],
        },
        separators=(",", ":"),
    ).encode()
    payloads = {"data/models.json": models, "data/manifest.json": export}
    return (
        {
            "schema_version": "1.0.0",
            "bundle_id": "d" * 64,
            "research_only": True,
            "trade_ready": False,
            "artifacts": [
                {
                    "kind": "model_index",
                    "path": "data/models.json",
                    "byte_size": len(models),
                    "sha256": hashlib.sha256(models).hexdigest(),
                    "required": True,
                },
                {
                    "kind": "static_export_manifest",
                    "path": "data/manifest.json",
                    "byte_size": len(export),
                    "sha256": hashlib.sha256(export).hexdigest(),
                    "required": True,
                },
            ],
        },
        payloads,
    )


def test_accepts_expected_deployment_and_formal_v2_catalog() -> None:
    validate_deployment({"commit_sha": "abc123"}, expected_commit="abc123")
    records = validate_formal_catalog(_catalog())
    assert {record.model_version_id for record in records} == {
        "qqqi_qqq_tqqq_v4_2",
        "us_x1_1",
        "cn_x1_0",
    }


def test_rejects_stale_deployment_or_extra_formal_model() -> None:
    with pytest.raises(ReleaseVerificationError, match="stale deployment"):
        validate_deployment({"commit_sha": "old"}, expected_commit="new")
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    records.append(
        {
            "model_family_id": "us_ranker",
            "model_version_id": "us_x1_0",
            "run_id": "us_x1_0_run",
            "bundle_id": "e" * 64,
            "manifest_path": "us_ranker/us_x1_0/us_x1_0_run/manifest.json",
            "manifest_sha256": "f" * 64,
            "evidence_cutoff": "2026-07-31",
            "publication_status": "accepted_formal_baseline",
        }
    )
    records.sort(key=lambda row: (row["model_family_id"], row["model_version_id"], row["run_id"]))
    with pytest.raises(ReleaseVerificationError, match="unexpected formal model version"):
        validate_formal_catalog(catalog)


def test_verifies_manifest_identity_and_available_sections() -> None:
    manifest, manifest_bytes, summary_bytes = _formal_manifest()
    record = PublishedFormalRun(
        model_family_id="us_ranker",
        model_version_id="us_x1_1",
        run_id="us_x1_1_run",
        bundle_id=str(manifest["bundle_id"]),
        manifest_path="us_ranker/us_x1_1/us_x1_1_run/manifest.json",
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        evidence_cutoff="2026-07-31",
    )
    _, sections = validate_formal_manifest(record, manifest_bytes)
    assert [section.section_id for section in sections] == ["summary"]
    validate_formal_section(record, sections[0], summary_bytes)
    with pytest.raises(ReleaseVerificationError, match="section digest mismatch"):
        validate_formal_section(record, sections[0], summary_bytes[:-1] + b" ")


def test_rejects_catalog_manifest_identity_drift() -> None:
    manifest, manifest_bytes, _ = _formal_manifest()
    record = PublishedFormalRun(
        model_family_id="us_ranker",
        model_version_id="us_x1_1",
        run_id="different_run",
        bundle_id=str(manifest["bundle_id"]),
        manifest_path="us_ranker/us_x1_1/different_run/manifest.json",
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        evidence_cutoff="2026-07-31",
    )
    with pytest.raises(ReleaseVerificationError, match="catalog/manifest identity mismatch"):
        validate_formal_manifest(record, manifest_bytes)


def test_verifies_required_research_bundle_artifacts() -> None:
    bundle, payloads = _bundle_fixture()
    bundle_id, artifacts = validate_bundle_manifest(bundle)
    assert bundle_id == "d" * 64
    assert {artifact.kind for artifact in artifacts} == {
        "model_index",
        "static_export_manifest",
    }
    for artifact in artifacts:
        validate_bundle_artifact_bytes(artifact, payloads[artifact.path])


def test_rejects_corrupted_bundle_artifact() -> None:
    bundle, payloads = _bundle_fixture()
    _, artifacts = validate_bundle_manifest(bundle)
    model_index = next(artifact for artifact in artifacts if artifact.kind == "model_index")
    with pytest.raises(ReleaseVerificationError, match="digest mismatch"):
        validate_bundle_artifact_bytes(
            PublishedBundleArtifact(
                kind=model_index.kind,
                path=model_index.path,
                byte_size=model_index.byte_size,
                sha256="0" * 64,
            ),
            payloads[model_index.path],
        )


def test_rejects_legacy_shell() -> None:
    validate_shell(b"<html>Governed Model Runs</html>")
    with pytest.raises(ReleaseVerificationError, match="missing marker"):
        validate_shell(b"<html>Complete backtest review</html>")
