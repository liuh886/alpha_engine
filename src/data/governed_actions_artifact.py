"""Fetch and verify immutable GitHub Actions data artifacts.

The locator is deliberately review-bound. Runtime discovery of a "latest"
successful artifact is prohibited because failed workflows can still upload
diagnostic artifacts and a mutable name cannot identify training evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import quote

import requests
import yaml

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
class DurableRelease:
    """Immutable GitHub Release asset that survives Actions artifact expiry."""

    tag: str
    asset_name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class DurableGitArchive:
    repository: str
    commit: str
    path: str
    sha256: str
    size_bytes: int


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
    durable_release: DurableRelease | None = None
    research_reference_contract_sha256: str | None = None
    durable_git: DurableGitArchive | None = None


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


def _durable_release(row: Mapping[str, Any], source_id: str) -> DurableRelease | None:
    raw = row.get("durable_release")
    if raw is None:
        return None
    binding = _mapping(raw, f"{source_id}.durable_release")
    digest = _required_text(binding, "sha256").lower()
    if not _SHA256.fullmatch(digest):
        raise GovernedActionsArtifactError(f"invalid durable release digest: {source_id}")
    if f"sha256:{digest}" != row.get("artifact_digest") or binding.get("size_bytes") != row.get("artifact_size_bytes"):
        raise GovernedActionsArtifactError("durable release must preserve exact Actions archive")
    return DurableRelease(
        tag=_required_text(binding, "tag"),
        asset_name=_required_text(binding, "asset_name"),
        sha256=digest,
        size_bytes=_positive_int(binding, "size_bytes"),
    )


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
        research_contract = row.get("research_reference_contract_sha256")
        if research_contract is not None and (
            row.get("source_kind") != "etf_reference_bundle"
            or not isinstance(research_contract, str)
            or not _SHA256.fullmatch(research_contract)
        ):
            raise GovernedActionsArtifactError("invalid research reference contract binding")
        durable_git = None
        if row.get("durable_git") is not None:
            git = _mapping(row["durable_git"], "durable_git")
            repository_binding = _required_text(git, "repository")
            commit = _required_text(git, "commit")
            member = _required_text(git, "path")
            if not _REPOSITORY.fullmatch(repository_binding) or not re.fullmatch(r"[0-9a-f]{40}", commit) or not _safe_relative(member):
                raise GovernedActionsArtifactError("invalid private Git archive identity")
            git_digest = _required_text(git, "sha256")
            size = _positive_int(git, "size_bytes")
            if f"sha256:{git_digest}" != row.get("artifact_digest") or size != row.get("artifact_size_bytes"):
                raise GovernedActionsArtifactError("private Git archive must preserve exact Actions bytes")
            durable_git = DurableGitArchive(repository_binding, commit, member, git_digest, size)
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
            durable_release=_durable_release(row, source_id),
            research_reference_contract_sha256=research_contract,
            durable_git=durable_git,
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


def inspect_source_retention(
    registry_path: Path, *, source_ids: Sequence[str] = (), as_of: datetime | None = None,
) -> dict[str, Any]:
    """Describe pinned retention boundaries without downloading or validating data."""
    registry = load_governed_source_registry(registry_path)
    observed_at = as_of or datetime.now(timezone.utc)
    if observed_at.utcoffset() is None:
        raise GovernedActionsArtifactError("retention observation requires a timezone")
    rows = []
    for source_id in sorted(set(source_ids) if source_ids else registry.sources):
        source = registry.sources.get(source_id)
        if source is None:
            raise GovernedActionsArtifactError(f"unknown governed source: {source_id}")
        try:
            expiry = datetime.fromisoformat(source.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GovernedActionsArtifactError(f"invalid source expiry: {source_id}") from exc
        if expiry.utcoffset() is None:
            raise GovernedActionsArtifactError(f"source expiry requires a timezone: {source_id}")
        expired = expiry <= observed_at
        release = source.durable_release
        rows.append({
            "source_id": source_id, "market": source.market, "pool_id": source.pool_id,
            "evidence_cutoff": source.evidence_cutoff,
            "workflow_run_id": source.workflow_run_id, "artifact_id": source.artifact_id,
            "artifact_digest": source.artifact_digest, "expires_at": source.expires_at,
            "actions_expired": expired,
            "retention_status": "durable_mirror_declared" if release or source.durable_git else "actions_expired" if expired else "actions_only",
            "durable_git": source.durable_git.__dict__ if source.durable_git else None,
            "durable_release": None if release is None else {
                "tag": release.tag, "asset_name": release.asset_name,
                "sha256": release.sha256, "size_bytes": release.size_bytes,
            },
            "retrieval_verified": False,
            "next_action": "verify_pinned_durable_git" if source.durable_git else "verify_pinned_durable_release" if release else "restore_exact_archive" if expired else "retain_exact_archive_before_expiry",
        })
    return {
        "schema_version": "1.0", "scope": "source_retention_only",
        "repository": registry.repository, "registry_sha256": _sha256(registry_path),
        "as_of": observed_at.isoformat(), "sources": rows,
        "research_only": True, "trade_ready": False,
    }


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


def _download_durable_release(
    *,
    repository: str,
    release: DurableRelease,
    destination: Path,

) -> None:
    """Verify a public mirror of the exact archive.

    The release asset is the durable source of truth: it carries the same
    content digest as the original Actions artifact but never expires, so the
    governed fetch cannot be broken by artifact retention or purge.
    """

    url = (
        f"https://github.com/{repository}/releases/download/"
        f"{quote(release.tag, safe='')}/{quote(release.asset_name, safe='')}"
    )
    with requests.get(url, stream=True, timeout=(30, 300), allow_redirects=True) as asset:
        asset.raise_for_status()
        digest = hashlib.sha256()
        size = 0
        with destination.open("wb") as handle:
            for chunk in asset.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > release.size_bytes:
                    raise GovernedActionsArtifactError(
                        "durable release asset exceeds declared size"
                    )
                digest.update(chunk)
                handle.write(chunk)
    if size != release.size_bytes:
        raise GovernedActionsArtifactError("durable release asset size mismatch")
    if digest.hexdigest() != release.sha256:
        raise GovernedActionsArtifactError("durable release asset digest mismatch")


@contextmanager
def _private_git_environment(ssh_key: str) -> Iterator[tuple[Path, dict[str, str]]]:
    """Keep scoped SSH credentials in temporary files with pinned host identity."""
    if not ssh_key.strip():
        raise GovernedActionsArtifactError("private archive SSH key is required")
    with tempfile.TemporaryDirectory(prefix="alpha-source-ssh-") as temporary:
        root = Path(temporary)
        key = root / "identity"
        key.write_text(ssh_key.strip() + "\n", encoding="utf-8", newline="\n")
        key.chmod(0o600)
        hosts = root / "known_hosts"
        # GitHub's published Ed25519 host key; never trust an unverified scan.
        hosts.write_text("[ssh.github.com]:443 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n", encoding="utf-8", newline="\n")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_VARIANT": "ssh"}
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {shlex.quote(key.as_posix())} -o IdentitiesOnly=yes -o BatchMode=yes "
            f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={shlex.quote(hosts.as_posix())}"
        )
        repository = root / "repo"
        repository.mkdir()
        yield repository, env


def _download_durable_git(*, archive: DurableGitArchive, destination: Path, ssh_key: str) -> None:
    """Read exact bytes with a repository-scoped read-only deploy key, no PAT."""
    if (not _REPOSITORY.fullmatch(archive.repository) or not re.fullmatch(r"[0-9a-f]{40}", archive.commit)
            or not _safe_relative(archive.path) or not _SHA256.fullmatch(archive.sha256)
            or not 0 < archive.size_bytes <= 90 * 1024 * 1024):
        raise GovernedActionsArtifactError("invalid private archive binding")
    with _private_git_environment(ssh_key) as (repository, env):
        commands = [
            ["git", "init", "--quiet"],
            ["git", "remote", "add", "origin", _private_archive_remote(archive.repository)],
            ["git", "config", "remote.origin.promisor", "true"],
            ["git", "config", "remote.origin.partialclonefilter", "blob:none"],
            ["git", "fetch", "--quiet", "--filter=blob:none", "--depth=1", "origin", archive.commit],
        ]
        try:
            for command in commands:
                subprocess.run(command, cwd=repository, env=env, check=True, capture_output=True, timeout=120)
            size = subprocess.run(["git", "cat-file", "-s", f"{archive.commit}:{archive.path}"],
                cwd=repository, env=env, check=True, capture_output=True, timeout=120).stdout
            if int(size) != archive.size_bytes:
                raise GovernedActionsArtifactError("private Git archive size or digest mismatch")
            with destination.open("wb") as handle:
                subprocess.run(["git", "show", f"{archive.commit}:{archive.path}"], cwd=repository, env=env, check=True, stdout=handle, stderr=subprocess.PIPE, timeout=120)
        except (subprocess.SubprocessError, OSError) as exc:
            raise GovernedActionsArtifactError(f"private Git archive retrieval failed: {type(exc).__name__}") from None
    if destination.stat().st_size != archive.size_bytes or _sha256(destination) != archive.sha256:
        raise GovernedActionsArtifactError("private Git archive size or digest mismatch")


def _private_archive_remote(repository: str) -> str:
    return f"ssh://git@ssh.github.com:443/{repository}.git"


def _archive_git(worktree: Path, env: dict[str, str], *args: str) -> str:
    try:
        result = subprocess.run(["git", "-c", f"core.hooksPath={worktree / 'no-hooks'}", *args],
            cwd=worktree, env=env, check=True, capture_output=True, timeout=180)
        return result.stdout.decode().strip()
    except (subprocess.SubprocessError, OSError):
        raise GovernedActionsArtifactError("private archive Git operation failed") from None


def retain_private_archive(*, repository: str, member: str, archive_path: Path, ssh_key: str) -> dict[str, Any]:
    """Append one source archive using a key scoped only to the private archive repo."""
    if (not _REPOSITORY.fullmatch(repository) or not _safe_relative(member)
            or not re.fullmatch(r"archives/[A-Za-z0-9_./-]+", member)):
        raise GovernedActionsArtifactError("invalid private archive destination")
    if not archive_path.is_file() or archive_path.stat().st_size > 90 * 1024 * 1024:
        raise GovernedActionsArtifactError("source archive missing or exceeds private Git size limit")
    with _private_git_environment(ssh_key) as (worktree, env):
        remote = _private_archive_remote(repository)
        # Freeze bytes once. Concurrency retries append this same immutable member;
        # they never replay a producer or retry the mutable ledger CAS protocol.
        captured = worktree.parent / "captured.zip"
        shutil.copyfile(archive_path, captured)
        size = captured.stat().st_size
        if not 0 < size <= 90 * 1024 * 1024:
            raise GovernedActionsArtifactError("source archive exceeds private Git size limit")
        digest = _sha256(captured)

        def git(*args: str) -> str:
            return _archive_git(worktree, env, *args)

        git("init", "--quiet")
        git("remote", "add", "origin", remote)
        git("config", "remote.origin.promisor", "true")
        git("config", "remote.origin.partialclonefilter", "blob:none")
        for attempt in range(5):
            git("fetch", "--quiet", "--filter=blob:none", "--depth=1", "origin", "main")
            parent = git("rev-parse", "FETCH_HEAD")
            blob = git("hash-object", "-w", str(captured))
            existing = git("ls-tree", parent, "--", member)
            if existing:
                if existing != f"100644 blob {blob}\t{member}":
                    raise GovernedActionsArtifactError("refusing to replace an existing private source archive")
                commit = parent
                break
            git("read-tree", parent)
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{member}")
            tree = git("write-tree")
            commit = git("-c", "user.name=Alpha Engine Research", "-c", "user.email=research@alphaengine.local",
                "commit-tree", tree, "-p", parent, "-m", f"Retain source evidence {member}")
            try:
                git("push", "--quiet", "origin", f"{commit}:refs/heads/main")
                break
            except GovernedActionsArtifactError:
                git("fetch", "--quiet", "--filter=blob:none", "--depth=1", "origin", "main")
                if git("rev-parse", "FETCH_HEAD") == parent or attempt == 4:
                    raise GovernedActionsArtifactError("private archive append failed or concurrency budget exhausted") from None
        else:  # pragma: no cover - bounded loop either returns or raises
            raise GovernedActionsArtifactError("private archive concurrency budget exhausted")
    return {"repository": repository, "commit": commit, "path": member, "sha256": digest, "size_bytes": size}


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
    from src.factors.reusable_panel import _verify_reusable_tree

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
    from src.data.selected_pool_event_population import verify_selected_pool_event_bundle

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


def _verify_reference_bundle(source: GovernedSource, root: Path) -> None:
    manifest = _load_json(root / "bundle_manifest.json")
    raw_symbols = manifest.get("symbols", [])
    symbols = sorted(
        {str(symbol).strip().upper() for symbol in raw_symbols if str(symbol).strip()}
    )
    if not symbols:
        raise GovernedActionsArtifactError("reference bundle symbols are missing")
    if (
        source.market != "us"
        or manifest.get("bundle_id") != source.pool_id
        or len(symbols) != source.expected_symbol_count
        or len(raw_symbols) != len(symbols)
    ):
        raise GovernedActionsArtifactError("reference bundle identity mismatch")
    if manifest.get("strategy_data_ready") is not True:
        raise GovernedActionsArtifactError("reference bundle strategy data is not ready")
    if source.research_reference_contract_sha256 is not None:
        if (
            manifest.get("contract_sha256") != source.research_reference_contract_sha256
            or manifest.get("source_policy") != "yahoo_research_v2"
            or symbols != ["QQQ", "QQQI", "TQQQ"]
            or manifest.get("selected_providers") != {symbol: "yfinance" for symbol in symbols}
            or manifest.get("professional_source_ready") is not False
            or any("tiingo" in str(path).lower() for path in manifest.get("files", {}))
        ):
            raise GovernedActionsArtifactError("research reference source contract mismatch")
    elif manifest.get("professional_source_ready") is not True:
        raise GovernedActionsArtifactError(
            "reference bundle professional source is not ready"
        )
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise GovernedActionsArtifactError("reference bundle research boundary mismatch")
    reconciliation = manifest.get("reconciliation_status", {})
    if not isinstance(reconciliation, dict):
        raise GovernedActionsArtifactError("reference bundle reconciliation is invalid")
    quarantined = sorted(
        symbol
        for symbol, status in reconciliation.items()
        if str(status).lower() == "quarantine"
    )
    if quarantined:
        raise GovernedActionsArtifactError(
            f"reference bundle quarantined symbols: {quarantined}"
        )
    if str(manifest.get("common_history_end", "")) != source.evidence_cutoff:
        raise GovernedActionsArtifactError("reference bundle cutoff mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise GovernedActionsArtifactError("reference bundle file inventory is missing")
    for relative, digest in files.items():
        if not isinstance(relative, str) or not _safe_relative(relative):
            raise GovernedActionsArtifactError("reference bundle member path is unsafe")
        member = root / relative
        if (
            not isinstance(digest, str) or not _SHA256.fullmatch(digest)
            or not member.is_file() or _sha256(member) != digest
        ):
            raise GovernedActionsArtifactError(f"reference bundle member hash mismatch: {relative}")
    if not all(f"canonical/{symbol}.csv" in files for symbol in symbols):
        raise GovernedActionsArtifactError("reference bundle canonical members are missing")


def verify_extracted_source(source: GovernedSource, root: Path) -> None:
    _verify_bound_manifests(source, root)
    if source.source_kind == "alpha158_panel":
        _verify_alpha158(source, root)
    elif source.source_kind == "selected_pool_events":
        _verify_events(source, root)
    elif source.source_kind == "etf_reference_bundle":
        _verify_reference_bundle(source, root)
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
    archive_ssh_key: str | None = None,
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
        retrieval_method = "actions_artifact"
        retrieval_note: str | None = None
        with tempfile.TemporaryDirectory(
            prefix=f"alpha-engine-{source_id}-", dir=output
        ) as temporary:
            temp = Path(temporary)
            archive = temp / "artifact.zip"
            extracted = temp / "extracted"
            extracted.mkdir()
            if source.durable_git is not None:
                try:
                    _download_durable_git(archive=source.durable_git, destination=archive, ssh_key=archive_ssh_key or "")
                    retrieval_method = "durable_git"
                except GovernedActionsArtifactError as exc:
                    retrieval_note = f"private archive unavailable; exact Actions fallback: {type(exc).__name__}"
            if source.durable_release is not None:
                try:
                    _download_durable_release(
                        repository=registry.repository,
                        release=source.durable_release,
                        destination=archive,
                    )
                    retrieval_method = "durable_release"
                except (GovernedActionsArtifactError, OSError) as exc:
                    retrieval_note = (
                        "durable release unavailable; fell back to the Actions "
                        f"artifact: {type(exc).__name__}"
                    )
            if retrieval_method not in {"durable_release", "durable_git"}:
                api_root = f"https://api.github.com/repos/{registry.repository}"
                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                try:
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
                except requests.RequestException as exc:
                    raise GovernedActionsArtifactError(
                        f"no durable release or Actions artifact is available for "
                        f"{source_id}: {exc}"
                    ) from exc
                run = _mapping(run_response.json(), "workflow run")
                artifact = _mapping(artifact_response.json(), "artifact")
                _validate_remote_metadata(source, run=run, artifact=artifact)
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
                "retrieval_method": retrieval_method,
                "retrieval_note": retrieval_note,
                "durable_git": source.durable_git.__dict__ if source.durable_git else None,
                "durable_release": (
                    None
                    if source.durable_release is None
                    else {
                        "tag": source.durable_release.tag,
                        "asset_name": source.durable_release.asset_name,
                        "sha256": source.durable_release.sha256,
                        "size_bytes": source.durable_release.size_bytes,
                    }
                ),
                "installed_payload": "verified_component_manifests_only",
                "training_payload_retrieval": "exact_artifact_locator_required",
                "research_only": True,
                "trade_ready": False,
            }
        )
    receipt = {
        "schema_version": "1.0",
        "repository": registry.repository,
        "verification_policy": (
            "durable_release_or_exact_run_artifact_archive_and_component_hashes"
        ),
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
