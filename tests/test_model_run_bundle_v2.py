from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.artifacts.model_run_bundle_v2 import (
    ModelRunBundleV2Error,
    canonical_json_bytes,
    comparability_identity,
    compute_bundle_id,
    sha256_bytes,
    validate_catalog,
    validate_manifest,
    validate_metric,
)

FIXTURE = Path("tests/fixtures/model_run_bundle_v2")


def _read(name: str):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def test_valid_fixture_binds_summary_and_bundle_identity() -> None:
    manifest = _read("manifest.json")
    summary_path = FIXTURE / "summary.json"
    validate_manifest(manifest)
    summary = manifest["sections"][0]
    assert summary["byte_size"] == len(summary_path.read_bytes())
    assert summary["sha256"] == sha256_bytes(summary_path.read_bytes())
    assert manifest["bundle_id"] == compute_bundle_id(manifest)
    assert len(comparability_identity(manifest)) == 64


def test_manifest_rejects_weakened_research_boundary() -> None:
    manifest = _read("manifest.json")
    manifest["trade_ready"] = True
    manifest["bundle_id"] = compute_bundle_id(manifest)
    with pytest.raises(ModelRunBundleV2Error, match="trade_ready"):
        validate_manifest(manifest)


def test_manifest_rejects_preview_formal_promotion() -> None:
    manifest = _read("manifest.json")
    manifest["publication_status"] = "accepted_formal_baseline"
    manifest["bundle_id"] = compute_bundle_id(manifest)
    with pytest.raises(ModelRunBundleV2Error, match="formal"):
        validate_manifest(manifest)


def test_unavailable_section_cannot_declare_fabricated_file() -> None:
    manifest = _read("manifest.json")
    performance = manifest["sections"][1]
    performance.update({"path": "performance.json", "sha256": "0" * 64, "byte_size": 2, "media_type": "application/json"})
    manifest["bundle_id"] = compute_bundle_id(manifest)
    with pytest.raises(ModelRunBundleV2Error, match="cannot declare path"):
        validate_manifest(manifest)


def test_metric_availability_and_unit_fail_closed() -> None:
    summary = _read("summary.json")
    available = summary["metrics"][0]
    unavailable = summary["metrics"][1]
    validate_metric(available)
    validate_metric(unavailable)

    wrong_unit = dict(available, unit="bps")
    with pytest.raises(ModelRunBundleV2Error, match="invalid unit"):
        validate_metric(wrong_unit)

    missing_reason = dict(unavailable, unavailable_reason=None)
    with pytest.raises(ModelRunBundleV2Error, match="reason missing"):
        validate_metric(missing_reason)


def test_catalog_requires_order_and_channel_isolation() -> None:
    manifest = _read("manifest.json")
    record = {
        "model_family_id": manifest["model_family_id"],
        "model_version_id": manifest["model_version_id"],
        "run_id": manifest["run_id"],
        "bundle_id": manifest["bundle_id"],
        "model_kind": manifest["model_kind"],
        "publication_status": manifest["publication_status"],
        "manifest_path": "us_ranker/us_x1_1/manifest.json",
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest)),
        "evidence_cutoff": manifest["evidence_cutoff"],
    }
    catalog = {
        "schema_version": "2.0.0",
        "channel": "preview",
        "generated_at": "2026-08-03T08:00:00Z",
        "research_only": True,
        "trade_ready": False,
        "records": [record],
    }
    validate_catalog(catalog)

    formal_leak = copy.deepcopy(catalog)
    formal_leak["records"][0]["publication_status"] = "accepted_formal_baseline"
    with pytest.raises(ModelRunBundleV2Error, match="formal record"):
        validate_catalog(formal_leak)
