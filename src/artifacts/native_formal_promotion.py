"""Promote a governed preview Bundle v2 into the accepted formal channel.

The formal catalog consumes bundles, not legacy model-package layouts. This module
contains the model-neutral promotion operation used by active models that do not
need US x1.3-specific acceptance metadata.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle
from src.artifacts.model_run_bundle_v2 import (
    canonical_json_bytes,
    compute_bundle_id,
    validate_manifest,
)
from src.governance.active_strategy_catalog import ActiveStrategy


class NativeFormalPromotionError(ValueError):
    """Raised when a native preview bundle cannot be promoted exactly."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeFormalPromotionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise NativeFormalPromotionError(f"JSON root must be an object: {path}")
    return value


def _verify_preview(run_dir: Path, strategy: ActiveStrategy) -> dict[str, Any]:
    manifest = _object(run_dir / "manifest.json")
    validate_manifest(manifest)
    if (
        manifest.get("model_family_id") != strategy.model_family_id
        or manifest.get("model_version_id") != strategy.model_version_id
        or manifest.get("model_kind") != strategy.model_kind
        or manifest.get("publication_channel") != "preview"
        or manifest.get("publication_status") != "ci_validated_preview"
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        raise NativeFormalPromotionError(
            f"preview boundary mismatch: {strategy.model_version_id}"
        )
    for section in manifest["sections"]:
        if section["availability_status"] != "available":
            continue
        path = run_dir / str(section["path"])
        if not path.is_file():
            raise NativeFormalPromotionError(
                f"preview section is missing: {section['section_id']}"
            )
        data = path.read_bytes()
        if (
            len(data) != section["byte_size"]
            or hashlib.sha256(data).hexdigest() != section["sha256"]
        ):
            raise NativeFormalPromotionError(
                f"preview section identity mismatch: {section['section_id']}"
            )
    return manifest


def promote_preview_bundle(
    source_run_dir: Path,
    output_root: Path,
    strategy: ActiveStrategy,
) -> Path:
    """Copy one exact preview bundle and seal it as accepted formal evidence."""

    source_run_dir = source_run_dir.resolve()
    output_root = output_root.resolve()
    source_manifest = _verify_preview(source_run_dir, strategy)
    target = (
        output_root
        / strategy.model_family_id
        / strategy.model_version_id
        / str(source_manifest["run_id"])
    )
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_run_dir, target)

    manifest = copy.deepcopy(source_manifest)
    manifest["publication_channel"] = "formal"
    manifest["publication_status"] = strategy.formal_status
    for section in manifest["sections"]:
        if section["availability_status"] != "available":
            continue
        path = target / str(section["path"])
        data = path.read_bytes()
        section["sha256"] = hashlib.sha256(data).hexdigest()
        section["byte_size"] = len(data)
    manifest["bundle_id"] = "0" * 64
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    (target / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    validate_formal_evidence_bundle(target)
    return target / "manifest.json"
