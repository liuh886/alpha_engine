from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.materialize_formal_backtest_base import FormalBaseMaterializationError, materialize


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    source = root / "data/research/formal_backtests"
    source.mkdir(parents=True)
    payloads = {
        "catalog": ("catalog.json", b'{"records":[]}\n'),
        "qqqi_qqq_tqqq_v4_2": ("qqqi_qqq_tqqq_v4_2.json", b'{"model_id":"qqqi_qqq_tqqq_v4_2"}\n'),
        "us_x1_1": ("us_x1_1.json", b'{"model_id":"us_x1_1","evidence_cutoff":"2025-12-31"}\n'),
        "cn_x1_0": ("cn_x1_0.json", b'{"model_id":"cn_x1_0","evidence_cutoff":"2026-06-15"}\n'),
    }
    files = {}
    for file_id, (name, payload) in payloads.items():
        path = source / name
        path.write_bytes(payload)
        files[file_id] = {"path": path.relative_to(root).as_posix(), "output_name": name, "sha256": hashlib.sha256(payload).hexdigest()}
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    commit = _git(root, "rev-parse", "HEAD")
    manifest = root / "base_manifest.json"
    manifest.write_text(json.dumps({"schema_version":"1.0.0","base_commit":commit,"files":files,"research_only":True,"trade_ready":False}), encoding="utf-8")
    for path in source.glob("*.json"):
        path.write_text('{"changed":true}\n', encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "later")
    return root, manifest, commit


def test_materializes_exact_complete_pinned_release(tmp_path: Path) -> None:
    root, manifest, commit = _fixture(tmp_path)
    output = tmp_path / "output"
    receipt = materialize(repository_root=root, manifest_path=manifest, output_dir=output, fetch=False)
    assert receipt["status"] == "materialized"
    assert receipt["base_commit"] == commit
    assert set(path.name for path in output.glob("*.json")) == {"catalog.json", "qqqi_qqq_tqqq_v4_2.json", "us_x1_1.json", "cn_x1_0.json"}
    assert json.loads((output / "us_x1_1.json").read_text())["evidence_cutoff"] == "2025-12-31"
    assert json.loads((output / "cn_x1_0.json").read_text())["evidence_cutoff"] == "2026-06-15"


def test_rejects_digest_mismatch(tmp_path: Path) -> None:
    root, manifest, _ = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"]["us_x1_1"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FormalBaseMaterializationError, match="digest mismatch"):
        materialize(repository_root=root, manifest_path=manifest, output_dir=tmp_path / "output", fetch=False)


def test_rejects_incomplete_release(tmp_path: Path) -> None:
    root, manifest, _ = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"].pop("catalog")
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FormalBaseMaterializationError, match="complete formal release"):
        materialize(repository_root=root, manifest_path=manifest, output_dir=tmp_path / "output", fetch=False)


def test_rejects_weakened_research_boundary(tmp_path: Path) -> None:
    root, manifest, _ = _fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["trade_ready"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FormalBaseMaterializationError, match="research boundary"):
        materialize(repository_root=root, manifest_path=manifest, output_dir=tmp_path / "output", fetch=False)
