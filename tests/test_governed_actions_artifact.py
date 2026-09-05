from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

import pytest

from src.data.governed_actions_artifact import (
    GovernedActionsArtifactError,
    GovernedSource,
    ManifestBinding,
    _download_archive,
    _safe_extract,
    _validate_remote_metadata,
    _verify_bound_manifests,
    load_governed_source_registry,
)


REGISTRY = Path("configs/data/formal_model_data_sources_v1.yaml")


def _source(**overrides) -> GovernedSource:
    values = {
        "source_id": "fixture",
        "source_kind": "selected_pool_events",
        "workflow_path": ".github/workflows/fixture.yml",
        "workflow_run_id": 123,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "artifact_id": 456,
        "artifact_name": "fixture-artifact",
        "artifact_digest": "sha256:" + hashlib.sha256(b"zip").hexdigest(),
        "artifact_size_bytes": 3,
        "expires_at": "2026-12-01T00:00:00Z",
        "market": "cn",
        "pool_id": "cn_selected_equities_v3",
        "evidence_cutoff": "2026-08-31",
        "expected_symbol_count": 130,
        "max_uncompressed_bytes": 1024,
        "max_member_count": 5,
        "component_manifests": (ManifestBinding("manifest.json", "b" * 64),),
    }
    values.update(overrides)
    return GovernedSource(**values)


def _remote(source: GovernedSource) -> tuple[dict, dict]:
    run = {
        "id": source.workflow_run_id,
        "head_branch": source.head_branch,
        "head_sha": source.head_sha,
        "path": source.workflow_path,
        "status": "completed",
        "conclusion": "success",
    }
    artifact = {
        "id": source.artifact_id,
        "name": source.artifact_name,
        "digest": source.artifact_digest,
        "size_in_bytes": source.artifact_size_bytes,
        "expired": False,
        "expires_at": source.expires_at,
        "workflow_run": {
            "id": source.workflow_run_id,
            "head_branch": source.head_branch,
            "head_sha": source.head_sha,
        },
    }
    return run, artifact


def test_checked_in_registry_freezes_exact_current_cn_sources() -> None:
    registry = load_governed_source_registry(REGISTRY)

    assert registry.repository == "liuh886/alpha_engine"
    assert set(registry.sources) == {
        "cn_alpha158",
        "cn_events",
    }
    assert registry.sources["cn_alpha158"].artifact_id == 9961938297
    assert registry.sources["cn_events"].artifact_id == 9962408566
    assert {source.evidence_cutoff for source in registry.sources.values()} == {
        "2026-09-04"
    }


def test_formal_refresh_source_roles_and_manifest_paths_match_registry() -> None:
    registry = load_governed_source_registry(REGISTRY)
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    source_ids = re.findall(r"--source ([a-z0-9_.-]+)\s", workflow)
    assert len(source_ids) == len(set(source_ids))
    assert set(source_ids) == set(registry.sources)
    component_paths = re.findall(
        r"\$\{CANDIDATE_MODEL_DATA_ROOT\}/sources/([^:]+):cn", workflow
    )
    assert len(component_paths) == 3
    for path in component_paths:
        source_id, relative = path.split("/", 1)
        assert relative in {
            binding.path for binding in registry.sources[source_id].component_manifests
        }


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("run", "conclusion", "failure"),
        ("run", "head_sha", "c" * 40),
        ("artifact", "expired", True),
        ("artifact", "digest", "sha256:" + "d" * 64),
        ("artifact", "name", "mutable-latest-name"),
    ],
)
def test_remote_metadata_drift_fails_closed(target: str, key: str, value) -> None:
    source = _source()
    run, artifact = _remote(source)
    (run if target == "run" else artifact)[key] = value

    with pytest.raises(GovernedActionsArtifactError, match="mismatch"):
        _validate_remote_metadata(source, run=run, artifact=artifact)


def test_artifact_workflow_identity_cannot_cross_runs() -> None:
    source = _source()
    run, artifact = _remote(source)
    artifact["workflow_run"]["id"] = 999

    with pytest.raises(GovernedActionsArtifactError, match="workflow-run identity"):
        _validate_remote_metadata(source, run=run, artifact=artifact)


@pytest.mark.parametrize("member", ["../escape.json", "C:/escape.json"])
def test_safe_extract_rejects_path_traversal(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(member, "{}")

    with pytest.raises(GovernedActionsArtifactError, match="unsafe artifact member"):
        _safe_extract(_source(), archive, tmp_path / "output")


def test_safe_extract_rejects_expansion_limit(tmp_path: Path) -> None:
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("large.bin", b"x" * 20)

    with pytest.raises(GovernedActionsArtifactError, match="expansion exceeds"):
        _safe_extract(_source(max_uncompressed_bytes=10), archive, tmp_path / "output")


def test_bound_manifest_tamper_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    source = _source(
        component_manifests=(ManifestBinding("manifest.json", "0" * 64),)
    )

    with pytest.raises(GovernedActionsArtifactError, match="manifest hash mismatch"):
        _verify_bound_manifests(source, tmp_path)


def test_download_does_not_forward_github_token_to_blob(monkeypatch, tmp_path: Path) -> None:
    payload = b"zip"
    source = _source()
    calls: list[dict] = []

    class Response:
        def __init__(self, *, status_code=200, headers=None, body=b""):
            self.status_code = status_code
            self.headers = headers or {}
            self.body = body

        def raise_for_status(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def iter_content(self, *, chunk_size):
            assert chunk_size == 256 * 1024
            yield self.body

    def get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if url.startswith("https://api.github.com/"):
            return Response(
                status_code=302,
                headers={"Location": "https://signed.example/artifact.zip"},
            )
        return Response(body=payload)

    monkeypatch.setattr(
        "src.data.governed_actions_artifact.requests.get",
        get,
    )
    destination = tmp_path / "artifact.zip"

    _download_archive(
        repository="owner/repo",
        source=source,
        token="secret-token",
        destination=destination,
    )

    assert destination.read_bytes() == payload
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert "headers" not in calls[1]


def test_receipt_contract_stays_json_serializable() -> None:
    source = _source()
    assert json.loads(json.dumps(source.component_manifests[0].__dict__)) == {
        "path": "manifest.json",
        "sha256": "b" * 64,
    }
