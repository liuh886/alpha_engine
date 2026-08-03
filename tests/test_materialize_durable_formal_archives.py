from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.materialize_durable_formal_archives import (
    DurableArchiveError,
    materialize,
)


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / "data/research/formal_promotions/archive/demo.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"exact-source-archive")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = {
        "model_id": "demo",
        "source": {
            "artifact_digest": f"sha256:{digest}",
            "workflow_run_id": 123,
            "artifact_id": 456,
            "expires_at": "2026-08-15T00:00:00Z",
        },
        "durability": {
            "status": "durable_repository_archive",
            "approved_durable_location": archive.relative_to(tmp_path).as_posix(),
            "non_regenerable_after_expiry": False,
        },
    }
    manifest_path = tmp_path / "data/research/formal_promotions/demo.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path, archive


def test_materializes_exact_repository_archive(tmp_path: Path) -> None:
    root, archive = _workspace(tmp_path)
    output = root / "artifacts/archives"
    receipt = materialize(
        root,
        Path("data/research/formal_promotions"),
        output,
    )
    assert receipt["status"] == "materialized"
    assert receipt["archives"][0]["archive_digest"].startswith("sha256:")
    assert (output / "demo.zip").read_bytes() == archive.read_bytes()


def test_rejects_digest_mismatch(tmp_path: Path) -> None:
    root, archive = _workspace(tmp_path)
    archive.write_bytes(b"mutated")
    with pytest.raises(DurableArchiveError, match="digest mismatch"):
        materialize(
            root,
            Path("data/research/formal_promotions"),
            root / "artifacts/archives",
        )


def test_rejects_missing_archive(tmp_path: Path) -> None:
    root, archive = _workspace(tmp_path)
    archive.unlink()
    with pytest.raises(DurableArchiveError, match="archive missing"):
        materialize(
            root,
            Path("data/research/formal_promotions"),
            root / "artifacts/archives",
        )


def test_rejects_time_bounded_durability(tmp_path: Path) -> None:
    root, _ = _workspace(tmp_path)
    manifest_path = root / "data/research/formal_promotions/demo.json"
    payload = json.loads(manifest_path.read_text())
    payload["durability"]["status"] = "time_bounded_actions_artifact"
    manifest_path.write_text(json.dumps(payload))
    with pytest.raises(DurableArchiveError, match="not durable"):
        materialize(
            root,
            Path("data/research/formal_promotions"),
            root / "artifacts/archives",
        )
