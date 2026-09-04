"""Fetch and verify immutable GitHub Actions data artifacts.

The locator is deliberately review-bound. Runtime discovery of a "latest"
successful artifact is prohibited because failed workflows can still upload
diagnostic artifacts and a mutable name cannot identify training evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import requests
import yaml

from src.data.selected_pool_event_population import (
    verify_selected_pool_event_bundle,
)
from src.factors.reusable_panel import _verify_reusable_tree

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class GovernedActionsArtifactError(ValueError):
    """Raised when remote or extracted evidence differs from its locator."""


@dataclass(frozen=True)
class ManifestBinding:
    path: str
    sha256: str


@dataclass(frozen=True)
class GovernedSource:
    source_id: str
    source_kind: str
    workflow_path: str
    workflow_run_id: int
    head_branch: str
    head_sha: str
    artifact_id: int
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int
    expires_at: str
    market: str
    pool_id: str
    evidence_cutoff: str
    expected_symbol_count: int
    max_uncompressed_bytes: int
    max_member_count: int
    component_manifests: tuple[ManifestBinding, ...]


@dataclass(frozen=True)
class GovernedSourceRegistry:
    repository: str
    sources: Mapping[str, GovernedSource]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise GovernedActionsArtifactError(f"{label} must be a mapping")
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise GovernedActionsArtifactError(f"governed source requires {key}")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = int(payload.get(key, 0))
    if value <= 0:
        raise GovernedActionsArtifactError(f"governed source requires positive {key}")
    return value


def load_governed_source_registry(path: Path) -> GovernedSourceRegistry:
    payload = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "registry")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise GovernedActionsArtifactError("governed source research boundary changed")
    repository = _required_text(payload, "repository")
    if not _REPOSITORY.fullmatch(repository):
        raise GovernedActionsArtifactError("invalid GitHub repository identity")
    raw_sources = _mapping(payload.get("sources"), "sources")
    sources: dict[str, GovernedSource] = {}
    for raw_id, raw in raw_sources.items():
        source_id = str(raw_id).strip()
        if not _SOURCE_ID.fullmatch(source_id):
            raise GovernedActionsArtifactError(f"invalid governed source ID: {source_id}")
        row = _mapping(raw, source_id)
        digest = _required_text(row, "artifact_digest").lower()
        if not digest.startswith("sha256:") or not _SHA256.fullmatch(digest[7:]):
            raise GovernedActionsArtifactError(f"invalid artifact digest: {source_id}")
        head_sha = _required_text(row, "head_sha").lower()
        if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
            raise GovernedActionsArtifactError(f"invalid head SHA: {source_id}")
        bindings: list[ManifestBinding] = []
        raw_bindings = row.get("component_manifests")
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise GovernedActionsArtifactError(f"component manifests required: {source_id}")
        for item in raw_bindings:
            binding = _mapping(item, f"{source_id}.component_manifest")
            relative = _required_text(binding, "path")
            expected = _required_text(binding, "sha256").lower()
            if not _safe_relative(relative) or not _SHA256.fullmatch(expected):
                raise GovernedActionsArtifactError(
                    f"invalid component manifest binding: {source_id}/{relative}"
                )
            bindings.append(ManifestBinding(relative, expected))
        source = GovernedSource(
            source_id=source_id,
            source_kind=_required_text(row, "source_kind"),
            workflow_path=_required_text(row, "workflow_path"),
            workflow_run_id=_positive_int(row, "workflow_run_id"),
            head_branch=_required_text(row, "head_branch"),
            head_sha=head_sha,
            artifact_id=_positive_int(row, "artifact_id"),
            artifact_name=_required_text(row, "artifact_name"),
            artifact_digest=digest,
            artifact_size_bytes=_positive_int(row, "artifact_size_bytes"),
            expires_at=_required_text(row, "expires_at"),
            market=_required_text(row, "market").lower(),
            pool_id=_required_text(row, "pool_id"),
            evidence_cutoff=_required_text(row, "evidence_cutoff"),
            expected_symbol_count=_positive_int(row, "expected_symbol_count"),
            max_uncompressed_bytes=_positive_int(row, "max_uncompressed_bytes"),
            max_member_count=_positive_int(row, "max_member_count"),
            component_manifests=tuple(bindings),
        )
        sources[source_id] = source
    if not sources:
        raise GovernedActionsArtifactError("governed source registry is empty")
    return GovernedSourceRegistry(repository=repository, sources=sources)


def _safe_relative(value: str) -> bool:
    if "\\" in value or ":" in value:
        return False
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _validate_remote_metadata(
    source: GovernedSource,
    *,
    run: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> None:
    expected_run = {
        "id": source.workflow_run_id,
        "head_branch": source.head_branch,
        "head_sha": source.head_sha,
        "path": source.workflow_path,
        "status": "completed",
        "conclusion": "success",
    }
    for key, expected in expected_run.items():
        if run.get(key) != expected:
            raise GovernedActionsArtifactError(
                f"workflow run {key} mismatch: expected {expected!r}, got {run.get(key)!r}"
            )
    expected_artifact = {
        "id": source.artifact_id,
        "name": source.artifact_name,
        "digest": source.artifact_digest,
        "size_in_bytes": source.artifact_size_bytes,
        "expired": False,
        "expires_at": source.expires_at,
    }
    for key, expected in expected_artifact.items():
        if artifact.get(key) != expected:
            raise GovernedActionsArtifactError(
                f"artifact {key} mismatch: expected {expected!r}, got {artifact.get(key)!r}"
            )
    workflow_run = _mapping(artifact.get("workflow_run"), "artifact.workflow_run")
    if (
        workflow_run.get("id") != source.workflow_run_id
        or workflow_run.get("head_sha") != source.head_sha
        or workflow_run.get("head_branch") != source.head_branch
    ):
        raise GovernedActionsArtifactError("artifact workflow-run identity mismatch")


def _download_archive(
    *, repository: str, source: GovernedSource, token: str, destination: Path
) -> None:
    api_url = (
        f"https://api.github.com/repos/{repository}/actions/artifacts/"
        f"{source.artifact_id}/zip"
    )
    response = requests.get(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        allow_redirects=False,
        timeout=30,
    )
    response.raise_for_status()
    location = response.headers.get("Location", "")
    if response.status_code not in {301, 302, 303, 307, 308} or not location.startswith(
        "https://"
    ):
        raise GovernedActionsArtifactError("artifact API did not return an HTTPS redirect")
    # The signed blob URL must not receive the GitHub bearer token.
    with requests.get(location, stream=True, timeout=(30, 120)) as archive:
        archive.raise_for_status()
        digest = hashlib.sha256()
        size = 0
        with destination.open("wb") as handle:
            for chunk in archive.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > source.artifact_size_bytes:
                    raise GovernedActionsArtifactError("artifact archive exceeds declared size")
                digest.update(chunk)
                handle.write(chunk)
    if size != source.artifact_size_bytes:
        raise GovernedActionsArtifactError("artifact archive size mismatch")
    if f"sha256:{digest.hexdigest()}" != source.artifact_digest:
        raise GovernedActionsArtifactError("artifact archive digest mismatch")


def _safe_extract(source: GovernedSource, archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as handle:
        members = handle.infolist()
        if len(members) > source.max_member_count:
            raise GovernedActionsArtifactError("artifact member count exceeds limit")
        total = 0
        for member in members:
            if not _safe_relative(member.filename):
                raise GovernedActionsArtifactError(
                    f"unsafe artifact member path: {member.filename}"
                )
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise GovernedActionsArtifactError(
                    f"artifact symlink is not allowed: {member.filename}"
                )
            total += member.file_size
            if total > source.max_uncompressed_bytes:
                raise GovernedActionsArtifactError("artifact expansion exceeds limit")
        handle.extractall(destination)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GovernedActionsArtifactError(f"JSON object required: {path}")
    return payload


def _verify_bound_manifests(source: GovernedSource, root: Path) -> None:
    for binding in source.component_manifests:
        path = root / binding.path
        if not path.is_file() or _sha256(path) != binding.sha256:
            raise GovernedActionsArtifactError(
                f"component manifest hash mismatch: {source.source_id}/{binding.path}"
            )


def _verify_alpha158(source: GovernedSource, root: Path) -> None:
    panel_root = root / "alpha158"
    manifest = _load_json(panel_root / "factor_panel_manifest.json")
    expected = {
        "component_id": "factors.qlib_alpha158.panel.cn.v1",
        "component_kind": "factor_panel",
        "market": source.market,
        "pool_id": source.pool_id,
        "evidence_cutoff": source.evidence_cutoff,
        "expected_symbol_count": source.expected_symbol_count,
        "research_only": True,
        "trade_ready": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise GovernedActionsArtifactError(f"Alpha158 {key} mismatch")
    identity = str(manifest.get("input_identity_sha256", ""))
    if not _SHA256.fullmatch(identity):
        raise GovernedActionsArtifactError("Alpha158 input identity is invalid")
    _verify_reusable_tree(
        output=panel_root,
        manifest=manifest,
        expected_identity=identity,
    )
    profiles = json.loads((root / "frontend/training-profiles.json").read_text(encoding="utf-8"))
    if not isinstance(profiles, list):
        raise GovernedActionsArtifactError("Alpha158 training profiles must be a list")
    profile = next(
        (row for row in profiles if row.get("profile_id") == "cn_selected_alpha158_v1"),
        None,
    )
    if not isinstance(profile, dict) or profile.get("status") != "ready":
        raise GovernedActionsArtifactError("CN Alpha158 training profile is not ready")


def _verify_events(source: GovernedSource, root: Path) -> None:
    manifest = verify_selected_pool_event_bundle(root)
    expected = {
        "market": source.market,
        "pool_id": source.pool_id,
        "evidence_cutoff": source.evidence_cutoff,
        "expected_symbol_count": source.expected_symbol_count,
        "publication_eligible": True,
        "research_only": True,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise GovernedActionsArtifactError(f"event bundle {key} mismatch")


def verify_extracted_source(source: GovernedSource, root: Path) -> None:
    _verify_bound_manifests(source, root)
    if source.source_kind == "alpha158_panel":
        _verify_alpha158(source, root)
    elif source.source_kind == "selected_pool_events":
        _verify_events(source, root)
    else:
        raise GovernedActionsArtifactError(
            f"unsupported governed source kind: {source.source_kind}"
        )


def fetch_governed_sources(
    *,
    registry_path: Path,
    source_ids: Sequence[str],
    output_root: Path,
    token: str,
) -> dict[str, Any]:
    registry = load_governed_source_registry(registry_path)
    if not token.strip():
        raise GovernedActionsArtifactError("GitHub token is required")
    output = output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    for source_id in source_ids:
        source = registry.sources.get(source_id)
        if source is None:
            raise GovernedActionsArtifactError(f"unknown governed source: {source_id}")
        destination = output / source_id
        if destination.exists():
            raise GovernedActionsArtifactError(
                f"governed source destination already exists: {destination}"
            )
        api_root = f"https://api.github.com/repos/{registry.repository}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        run_response = requests.get(
            f"{api_root}/actions/runs/{source.workflow_run_id}",
            headers=headers,
            timeout=30,
        )
        run_response.raise_for_status()
        artifact_response = requests.get(
            f"{api_root}/actions/artifacts/{source.artifact_id}",
            headers=headers,
            timeout=30,
        )
        artifact_response.raise_for_status()
        run = _mapping(run_response.json(), "workflow run")
        artifact = _mapping(artifact_response.json(), "artifact")
        _validate_remote_metadata(source, run=run, artifact=artifact)
        with tempfile.TemporaryDirectory(
            prefix=f"alpha-engine-{source_id}-", dir=output
        ) as temporary:
            temp = Path(temporary)
            archive = temp / "artifact.zip"
            extracted = temp / "extracted"
            extracted.mkdir()
            _download_archive(
                repository=registry.repository,
                source=source,
                token=token,
                destination=archive,
            )
            _safe_extract(source, archive, extracted)
            verify_extracted_source(source, extracted)
            destination.mkdir()
            for binding in source.component_manifests:
                source_path = extracted / binding.path
                target_path = destination / binding.path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
        receipts.append(
            {
                "source_id": source.source_id,
                "source_kind": source.source_kind,
                "workflow_run_id": source.workflow_run_id,
                "head_sha": source.head_sha,
                "artifact_id": source.artifact_id,
                "artifact_name": source.artifact_name,
                "artifact_digest": source.artifact_digest,
                "artifact_size_bytes": source.artifact_size_bytes,
                "expires_at": source.expires_at,
                "market": source.market,
                "pool_id": source.pool_id,
                "evidence_cutoff": source.evidence_cutoff,
                "component_manifests": [
                    {"path": row.path, "sha256": row.sha256}
                    for row in source.component_manifests
                ],
                "installed_payload": "verified_component_manifests_only",
                "training_payload_retrieval": "exact_artifact_locator_required",
                "research_only": True,
                "trade_ready": False,
            }
        )
    receipt = {
        "schema_version": "1.0",
        "repository": registry.repository,
        "verification_policy": "exact_run_artifact_archive_and_component_hashes",
        "sources": receipts,
        "research_only": True,
        "trade_ready": False,
    }
    receipt_path = output / "governed-source-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt
