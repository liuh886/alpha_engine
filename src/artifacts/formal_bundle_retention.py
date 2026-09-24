"""Retention primitive for formal Bundle v2 runs that must survive rotation.

The accepted formal catalog promotes exactly one active run per strategy and
replaces each active model directory on every refresh. Two classes of run must
survive that rotation:

- inactive model versions: superseded predecessors kept as an immutable audit
  closure consumed through ``load_retained_formal_run``;
- pinned benchmark bundles: runs referenced by a live frozen contract's
  ``benchmark_manifest`` even while their model remains active.

Both classes are copied verbatim, validated with the same evidence standard as
the active catalog, and never enter the active catalog. Every rotation path
must retain them, so the primitive lives here instead of inside one script.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle


class FormalBundleRetentionError(ValueError):
    """Raised when a retained formal bundle is missing or inconsistent."""


@dataclass(frozen=True)
class RetainedFormalRuns:
    """Relative manifest paths of retained runs, keyed to their manifest digest."""

    inactive_manifests: dict[str, str] = field(default_factory=dict)
    pinned_benchmark_manifests: dict[str, str] = field(default_factory=dict)

    @property
    def inactive_model_version_ids(self) -> list[str]:
        return sorted({Path(path).parts[1] for path in self.inactive_manifests})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBundleRetentionError(
            f"invalid retained formal manifest: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise FormalBundleRetentionError(
            f"retained formal manifest root must be an object: {path}"
        )
    return payload


def pinned_benchmark_manifest_paths(repository_root: Path) -> set[Path]:
    """Resolved manifests pinned as a live contract ``benchmark_manifest``.

    A frozen historical challenge contract pins one immutable formal run by
    repository path. Active-model rotation replaces a model's whole run
    directory, so such a bundle must be retained or the frozen contract would
    silently lose its benchmark.
    """

    pinned: set[Path] = set()
    configs = repository_root / "configs"
    if not configs.is_dir():
        return pinned
    for path in sorted(configs.rglob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        _collect_benchmark_manifests(payload, repository_root, pinned)
    return pinned


def _collect_benchmark_manifests(
    value: object, repository_root: Path, found: set[Path]
) -> None:
    if isinstance(value, Mapping):
        reference = value.get("benchmark_manifest")
        if isinstance(reference, str) and reference:
            found.add((repository_root / reference).resolve())
        for child in value.values():
            _collect_benchmark_manifests(child, repository_root, found)
    elif isinstance(value, list):
        for child in value:
            _collect_benchmark_manifests(child, repository_root, found)


def _copy_validated_bundle(source: Path, destination: Path, *, label: str) -> str:
    try:
        validate_formal_evidence_bundle(source)
    except ValueError as exc:
        raise FormalBundleRetentionError(
            f"invalid retained formal bundle: {label}"
        ) from exc
    shutil.copytree(source, destination)
    validate_formal_evidence_bundle(destination)
    return _sha256(destination / "manifest.json")


def retain_formal_runs(
    source_root: Path,
    output_root: Path,
    *,
    active_model_ids: set[str],
    repository_root: Path,
) -> RetainedFormalRuns:
    """Copy every inactive or pinned bundle from ``source_root`` to ``output_root``."""

    pinned_manifests = pinned_benchmark_manifest_paths(repository_root)
    inactive: dict[str, str] = {}
    pinned: dict[str, str] = {}
    for manifest in sorted(source_root.glob("*/*/*/manifest.json")):
        relative = manifest.relative_to(source_root)
        if len(relative.parts) != 4:
            raise FormalBundleRetentionError(
                f"retained formal manifest has invalid layout: {relative.as_posix()}"
            )
        payload = _read_manifest(manifest)
        model_family_id = str(payload.get("model_family_id") or "")
        model_version_id = str(payload.get("model_version_id") or "")
        is_pinned = manifest.resolve() in pinned_manifests
        is_inactive = model_version_id not in active_model_ids
        if not is_pinned and not is_inactive:
            continue
        if (
            not model_family_id
            or not model_version_id
            or relative.parts[0] != model_family_id
            or relative.parts[1] != model_version_id
        ):
            raise FormalBundleRetentionError(
                f"retained formal manifest identity mismatch: {relative.as_posix()}"
            )
        destination = output_root / relative.parent
        if destination.exists():
            if is_pinned and not is_inactive:
                # The active promotion already wrote this exact run.
                continue
            raise FormalBundleRetentionError(
                f"retained formal destination already exists: {relative.parent.as_posix()}"
            )
        digest = _copy_validated_bundle(
            manifest.parent, destination, label=relative.as_posix()
        )
        if is_inactive:
            inactive[relative.as_posix()] = digest
        else:
            pinned[relative.as_posix()] = digest
    return RetainedFormalRuns(
        inactive_manifests=inactive,
        pinned_benchmark_manifests=pinned,
    )
