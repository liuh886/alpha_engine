from __future__ import annotations

import hashlib
import json

import pytest

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, compute_bundle_id
from src.artifacts.pages_release_verification import (
    PublishedFormalRun,
    ReleaseVerificationError,
    validate_deployment,
    validate_formal_catalog,
    validate_formal_manifest,
    validate_formal_section,
    validate_public_operations,
    validate_shell,
)


def _catalog() -> dict[str, object]:
    records = [
        (
            "byd_allocation",
            "byd_v1_2_convex_momentum_budget_v1",
            "byd_v1_2_run",
            "2026-08-03",
            "1",
            "a",
        ),
        ("cn_ranker", "cn_x1_1", "cn_x1_1_run", "2026-08-03", "2", "b"),
        (
            "qqq_rotation",
            "qqqi_qqq_tqqq_v4_2",
            "qqq_v4_2_run",
            "2026-07-31",
            "3",
            "c",
        ),
        ("us_ranker", "us_x1_1", "us_x1_1_run", "2026-07-31", "4", "d"),
    ]
    return {
        "schema_version": "2.0.0",
        "channel": "formal",
        "generated_at": "2026-08-06T09:52:48Z",
        "research_only": True,
        "trade_ready": False,
        "records": [
            {
                "model_family_id": family,
                "model_version_id": version,
                "run_id": run,
                "bundle_id": bundle_character * 64,
                "manifest_path": f"{family}/{version}/{run}/manifest.json",
                "manifest_sha256": manifest_character * 64,
                "evidence_cutoff": cutoff,
                "publication_status": "accepted_formal_baseline",
            }
            for (
                family,
                version,
                run,
                cutoff,
                bundle_character,
                manifest_character,
            ) in records
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


def test_accepts_expected_deployment_and_catalog_governed_formal_runs() -> None:
    validate_deployment({"commit_sha": "abc123"}, expected_commit="abc123")
    records = validate_formal_catalog(_catalog())
    assert {record.model_version_id for record in records} == {
        "byd_v1_2_convex_momentum_budget_v1",
        "cn_x1_1",
        "qqqi_qqq_tqqq_v4_2",
        "us_x1_1",
    }


def test_rejects_stale_deployment_or_duplicate_formal_model() -> None:
    with pytest.raises(ReleaseVerificationError, match="stale deployment"):
        validate_deployment({"commit_sha": "old"}, expected_commit="new")
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    duplicate = dict(records[0])
    duplicate["run_id"] = "duplicate_run"
    duplicate["bundle_id"] = "5" * 64
    duplicate["manifest_path"] = (
        "byd_allocation/byd_v1_2_convex_momentum_budget_v1/duplicate_run/manifest.json"
    )
    duplicate["manifest_sha256"] = "e" * 64
    records.append(duplicate)
    records.sort(
        key=lambda row: (
            row["model_family_id"],
            row["model_version_id"],
            row["run_id"],
        )
    )
    with pytest.raises(ReleaseVerificationError, match="duplicate formal model version"):
        validate_formal_catalog(catalog)


def test_accepts_new_catalog_model_without_verifier_code_change() -> None:
    catalog = _catalog()
    records = catalog["records"]
    assert isinstance(records, list)
    records.append(
        {
            "model_family_id": "future_family",
            "model_version_id": "future_formal_v1",
            "run_id": "future_formal_run",
            "bundle_id": "6" * 64,
            "manifest_path": (
                "future_family/future_formal_v1/future_formal_run/manifest.json"
            ),
            "manifest_sha256": "f" * 64,
            "evidence_cutoff": "2026-08-06",
            "publication_status": "accepted_formal_baseline",
        }
    )
    records.sort(
        key=lambda row: (
            row["model_family_id"],
            row["model_version_id"],
            row["run_id"],
        )
    )
    observed = validate_formal_catalog(catalog)
    assert "future_formal_v1" in {record.model_version_id for record in observed}


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


def test_verifies_stable_shell_bootstrap_without_product_copy_dependency() -> None:
    validate_shell(b'<html><body><div id="root"></div><script type="module" src="/assets/app.js"></script></body></html>')
    with pytest.raises(ReleaseVerificationError, match="bootstrap markers"):
        validate_shell(b"<html>Governed Model Runs</html>")


def _public_operations() -> dict:
    return {
        "schema_version": "2.2.0",
        "generated_at": "2026-08-06T09:52:48Z",
        "research_only": True,
        "trade_ready": False,
        "records": [
            {
                "strategy_id": record.model_family_id,
                "model_version_id": record.model_version_id,
                "status": "blocked",
                "read_state": "protected",
                "as_of": None,
                "latest_completed_session": None,
                "decision_cadence": "Every completed market session",
                "next_decision_policy": "Evaluate after the close.",
                "state_label": "Runtime current operations",
                "decision_reason": "Current holdings and signals are delivered from the runtime access plane.",
                "allocations": [],
                "turnover": None,
                "estimated_cost": None,
                "data_freshness": "unknown",
                "factor_freshness": "blocked",
                "delivery_status": "not available",
                "source_label": "Runtime current operations",
                "source_href": None,
                "note": "Current holdings, targets, drivers and decision-ledger provenance are never included in the public static bundle.",
                "factor_evidence": [],
                "source_identity": {
                    "formal_bundle_id": record.bundle_id,
                    "formal_run_id": record.run_id,
                    "formal_evidence_cutoff": record.evidence_cutoff,
                    "ledger_fingerprint": None,
                    "signal_sha256": None,
                    "factor_catalog_implementation_hash": None,
                    "workflow_run_id": None,
                    "commit_sha": None,
                    "github_issue_number": None,
                },
            }
            for record in validate_formal_catalog(_catalog())
        ],
    }


def test_public_operations_bind_all_formal_runs_and_reject_missing_rows() -> None:
    operations = _public_operations()
    records = validate_formal_catalog(_catalog())
    validate_public_operations(operations, records)
    operations["records"].pop()
    with pytest.raises(ReleaseVerificationError, match="differ from the formal catalog"):
        validate_public_operations(operations, records)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("as_of", "2026-08-06"),
        ("latest_completed_session", "2026-08-06"),
        ("evaluation_changed", True),
        ("decision_schedule", {"state": "due"}),
        ("turnover", 0.3),
        ("read_state", None),
        ("source_href", "https://example.com/private-ledger"),
        ("decision_reason", "Protected signal explanation"),
        ("unexpected_runtime_field", "protected"),
    ],
)
def test_public_operations_reject_current_fields(field: str, value: object) -> None:
    operations = _public_operations()
    operations["records"][0][field] = value
    with pytest.raises(ReleaseVerificationError, match="protected evidence"):
        validate_public_operations(operations, validate_formal_catalog(_catalog()))


@pytest.mark.parametrize("field", [
    "ledger_fingerprint", "signal_sha256", "factor_catalog_implementation_hash",
    "workflow_run_id", "commit_sha", "github_issue_number", "formal_run_id",
    "formal_bundle_id", "formal_evidence_cutoff", "unexpected_identity",
])
def test_public_operations_reject_private_or_mismatched_identity(field: str) -> None:
    operations = _public_operations()
    operations["records"][0]["source_identity"][field] = "unexpected"
    with pytest.raises(ReleaseVerificationError, match="source identity mismatch"):
        validate_public_operations(operations, validate_formal_catalog(_catalog()))
