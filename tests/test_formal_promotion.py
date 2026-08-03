from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.formal_promotion import (
    FormalPromotionError,
    _safe_extract,
    load_manifest,
    validate_artifact_metadata,
    verify_reproduction,
)


def _manifest(path: Path, *, expires_at: str = "2030-01-01T00:00:00Z") -> Path:
    payload = {
        "schema_version": "1.0.0",
        "model_id": "demo",
        "package_path": "data/research/formal_backtests/demo.json",
        "evidence_cutoff": "2026-01-01",
        "research_only": True,
        "trade_ready": False,
        "source": {
            "kind": "github_actions_artifact",
            "repository": "liuh886/alpha_engine",
            "workflow_run_id": 123,
            "workflow_head_sha": "a" * 40,
            "artifact_id": 456,
            "artifact_name": "demo-source",
            "artifact_digest": "sha256:" + "b" * 64,
            "expires_at": expires_at,
            "source_layout": {
                "materialize_under": "demo",
                "required_paths": ["evidence/input.json"],
            },
        },
        "durability": {
            "status": "time_bounded_actions_artifact",
            "on_expiry": "block_non_regenerable",
            "approved_durable_location": None,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifest_requires_research_boundary_and_safe_package_path(tmp_path: Path) -> None:
    path = _manifest(tmp_path / "demo.json")
    manifest = load_manifest(path)
    assert manifest.model_id == "demo"

    payload = json.loads(path.read_text())
    payload["trade_ready"] = True
    path.write_text(json.dumps(payload))
    with pytest.raises(FormalPromotionError, match="research boundary"):
        load_manifest(path)


def test_artifact_metadata_is_identity_bound_and_expiry_blocks(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path / "demo.json"))
    metadata = {
        "id": 456,
        "name": "demo-source",
        "digest": "sha256:" + "b" * 64,
        "expired": False,
        "workflow_run": {"id": 123},
    }
    validate_artifact_metadata(
        manifest,
        metadata,
        now=datetime(2029, 1, 1, tzinfo=timezone.utc),
    )

    metadata["digest"] = "sha256:" + "c" * 64
    with pytest.raises(FormalPromotionError, match="digest mismatch"):
        validate_artifact_metadata(
            manifest,
            metadata,
            now=datetime(2029, 1, 1, tzinfo=timezone.utc),
        )

    expired = load_manifest(
        _manifest(tmp_path / "expired.json", expires_at="2028-01-01T00:00:00Z")
    )
    metadata["digest"] = "sha256:" + "b" * 64
    with pytest.raises(FormalPromotionError, match="declared source expired"):
        validate_artifact_metadata(
            expired,
            metadata,
            now=datetime(2029, 1, 1, tzinfo=timezone.utc),
        )


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "bad")
    with pytest.raises(FormalPromotionError, match="unsafe archive member"):
        _safe_extract(archive, tmp_path / "out")


def _write_demo_workspace(tmp_path: Path, *, mismatch: bool = False) -> tuple:
    repo = tmp_path / "repo"
    manifest_path = _manifest(repo / "data/research/formal_promotions/demo.json")
    manifest_payload = json.loads(manifest_path.read_text())

    archives = repo / "artifacts/formal-promotion/archives"
    archives.mkdir(parents=True)
    archive = archives / "demo.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("evidence/input.json", "{}")
    import hashlib

    digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest_payload["source"]["artifact_digest"] = digest
    manifest_path.write_text(json.dumps(manifest_payload))
    manifest = load_manifest(manifest_path)

    package = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "model_id": "demo",
        "publication_status": "accepted_formal_baseline",
        "evidence_cutoff": "2026-01-01",
        "research_only": True,
        "trade_ready": False,
        "evidence": {
            "workflow_run_id": 123,
            "artifact_id": 456,
            "artifact_digest": digest,
        },
        "evidence_completeness": {
            "status": "complete",
            "missing": [],
        },
    }
    package_bytes = (
        json.dumps(package, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    package_hash = hashlib.sha256(package_bytes).hexdigest()
    catalog = {
        "records": [
            {
                "model_id": "demo",
                "path": "demo.json",
                "sha256": package_hash,
            }
        ]
    }
    catalog_bytes = (
        json.dumps(catalog, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    generated_catalog_bytes = catalog_bytes

    committed = repo / "data/research/formal_backtests"
    committed.mkdir(parents=True)
    (committed / "demo.json").write_bytes(
        package_bytes.replace(b'"complete"', b'"partial"') if mismatch else package_bytes
    )
    if mismatch:
        committed_hash = hashlib.sha256((committed / "demo.json").read_bytes()).hexdigest()
        catalog["records"][0]["sha256"] = committed_hash
        catalog_bytes = (
            json.dumps(catalog, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    (committed / "catalog.json").write_bytes(catalog_bytes)

    builder = repo / "scripts/demo_builder.py"
    builder.parent.mkdir(parents=True)
    builder.write_text(
        "import argparse, pathlib\n"
        "p=argparse.ArgumentParser(); p.add_argument('--source-root'); "
        "p.add_argument('--output-dir'); a=p.parse_args()\n"
        f"out=pathlib.Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)\n"
        f"(out/'demo.json').write_bytes({package_bytes!r})\n"
        f"(out/'catalog.json').write_bytes({generated_catalog_bytes!r})\n"
    )
    return repo, (manifest,), committed, builder


def test_full_reproduction_is_byte_exact(tmp_path: Path) -> None:
    repo, manifests, committed, builder = _write_demo_workspace(tmp_path)
    receipt = verify_reproduction(
        manifests,
        repository_root=repo,
        archive_dir=repo / "artifacts/formal-promotion/archives",
        source_root=repo / "artifacts/formal-promotion/source",
        generated_dir=repo / "artifacts/formal-promotion/generated",
        committed_dir=committed,
        builder=builder.relative_to(repo),
        receipt_path=repo / "artifacts/formal-promotion/receipt.json",
        summary_path=repo / "artifacts/formal-promotion/summary.md",
    )
    assert receipt["status"] == "verified"
    assert receipt["catalog_byte_exact"] is True


def test_reproduction_mismatch_emits_diff(tmp_path: Path) -> None:
    repo, manifests, committed, builder = _write_demo_workspace(tmp_path, mismatch=True)
    summary = repo / "artifacts/formal-promotion/summary.md"
    with pytest.raises(FormalPromotionError, match="differ"):
        verify_reproduction(
            manifests,
            repository_root=repo,
            archive_dir=repo / "artifacts/formal-promotion/archives",
            source_root=repo / "artifacts/formal-promotion/source",
            generated_dir=repo / "artifacts/formal-promotion/generated",
            committed_dir=committed,
            builder=builder.relative_to(repo),
            receipt_path=repo / "artifacts/formal-promotion/receipt.json",
            summary_path=summary,
        )
    assert "Differences" in summary.read_text()
