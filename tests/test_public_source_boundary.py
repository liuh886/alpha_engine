"""Verify public source boundary and historical projection integrity (#1288).

Enforces zero operational leakage in published assets while preserving
immutable canonical research evidence and cryptographic source bindings.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.artifacts.pages_release_verification import (
    PublishedSection,
    ReleaseVerificationError,
    validate_formal_catalog,
    validate_formal_manifest,
    validate_formal_section,
    validate_public_operations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = REPO_ROOT / "qlib-dashboard"
PUBLIC_DATA = DASHBOARD_ROOT / "public" / "data"


@pytest.fixture(scope="module")
def synced_public_assets() -> Path:
    """Run publication sync scripts to ensure public data is freshly generated."""
    # Run sync-formal-model-runs
    formal_sync = DASHBOARD_ROOT / "scripts" / "sync-formal-model-runs.mjs"
    res1 = subprocess.run(
        ["node", str(formal_sync)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "catalog-active formal Model Run Bundle v2 assets" in res1.stdout

    # Run sync-strategy-operations
    ops_sync = DASHBOARD_ROOT / "scripts" / "sync-strategy-operations.mjs"
    res2 = subprocess.run(
        ["node", str(ops_sync)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert res2.returncode == 0
    return PUBLIC_DATA


def test_public_formal_runs_have_zero_operational_leakage(synced_public_assets: Path) -> None:
    """Anonymous traversal across all public formal run files must find 0 operational leakage."""
    formal_dir = synced_public_assets / "formal-model-runs"
    assert formal_dir.is_dir()

    for path in formal_dir.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        # No section in formal model runs may contain operating_state
        assert '"operating_state"' not in text, f"Forbidden 'operating_state' found in {path}"
        if path.name == "lineage.json":
            assert '"current_weights"' not in text, f"Forbidden 'current_weights' found in {path}"
            assert '"target_weights"' not in text, f"Forbidden 'target_weights' found in {path}"


def test_cn_27_historical_projection_identity_contract(synced_public_assets: Path) -> None:
    """CN_27 public asset must declare projection contract and bind to canonical source."""
    catalog_path = synced_public_assets / "formal-model-runs" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    cn27_record = next(
        r for r in catalog["records"] if r["model_version_id"] == "cn_27_v1_3"
    )
    # Must declare projection_contract
    assert cn27_record.get("projection_contract") == "public_historical_projection_v1"
    assert cn27_record.get("canonical_bundle_id") == "fc5c939c85cb5152a55d0e849ae123d64af86a8dcd1f57e3d0ba6c04e1c768bc"
    assert cn27_record.get("canonical_manifest_sha256") == "9275429c7bccabbc96007ec63af0bae70e77d302222320d49a2d70e4a0f3731e"

    # Bundle ID must be the recomputed projection bundle ID, distinct from canonical
    assert cn27_record["bundle_id"] != cn27_record["canonical_bundle_id"]

    # Manifest must carry matching source identity
    manifest_path = synced_public_assets / "formal-model-runs" / cn27_record["manifest_path"]
    manifest_bytes = manifest_path.read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == cn27_record["manifest_sha256"]
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    assert manifest["bundle_id"] == cn27_record["bundle_id"]
    assert manifest["projection_contract"] == "public_historical_projection_v1"
    assert manifest["source_identity"] == {
        "canonical_bundle_id": cn27_record["canonical_bundle_id"],
        "canonical_manifest_sha256": cn27_record["canonical_manifest_sha256"],
    }


def test_all_public_formal_assets_pass_release_verifier(synced_public_assets: Path) -> None:
    """Every catalog-active public formal run and its sections must pass verification."""
    catalog_path = synced_public_assets / "formal-model-runs" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    records = validate_formal_catalog(catalog)
    assert len(records) == 4

    for record in records:
        manifest_path = synced_public_assets / "formal-model-runs" / record.manifest_path
        manifest_bytes = manifest_path.read_bytes()
        manifest, sections = validate_formal_manifest(record, manifest_bytes)
        manifest_dir = manifest_path.parent

        for section in sections:
            section_file = manifest_dir / section.path
            assert section_file.is_file(), f"Section file missing: {section_file}"
            payload = section_file.read_bytes()
            assert len(payload) == section.byte_size
            assert hashlib.sha256(payload).hexdigest() == section.sha256
            validate_formal_section(record, section, payload)

    # Strategy operations must bind to canonical bundle IDs
    ops_path = synced_public_assets / "strategy-operations" / "snapshots.json"
    ops = json.loads(ops_path.read_text(encoding="utf-8"))
    validate_public_operations(ops, records)


def test_gate_a4_security_audit_and_reopened_status() -> None:
    """Gate A4 security audit must cover the 5 surfaces and enforce FAIL status until full isolation."""
    audit_file = REPO_ROOT / "docs" / "architecture" / "current_operations_security_audit_1288.md"
    assert audit_file.is_file(), "Security audit document #1288 missing"
    text = audit_file.read_text(encoding="utf-8")
    for surface in (
        "公开 Git",
        "历史 Git",
        "Pages",
        "Actions Artifacts",
        "当前数据写入路径",
    ):
        assert surface in text, f"Surface '{surface}' not covered in security audit #1288"

    # Scorecard must declare Gate A4 as FAIL, rejecting premature green
    scorecard = (REPO_ROOT / "docs" / "product" / "product_completion_scorecard_2026-10-25.md").read_text(encoding="utf-8")
    assert "| A4 | FAIL |" in scorecard, "Gate A4 must remain FAIL in scorecard"
    assert "A4 PASS" not in scorecard, "A4 must not be prematurely marked PASS"


def test_four_surface_negative_proof_contract() -> None:
    """Security audit must mandate independent negative proofs across Public Git, Pages, Artifacts, and Write Pipelines."""
    audit_file = REPO_ROOT / "docs" / "architecture" / "current_operations_security_audit_1288.md"
    text = audit_file.read_text(encoding="utf-8")
    for proof in (
        "Public Git Negative Proof",
        "Pages Negative Proof",
        "Actions Artifacts Negative Proof",
        "Write Pipelines Negative Proof",
    ):
        assert proof in text, f"Missing required negative proof declaration: {proof}"
