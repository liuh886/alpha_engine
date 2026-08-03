"""Generic, adapter-driven Model Run Bundle v2 exporter."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.artifacts.model_run_bundle_v2 import (
    ModelRunBundleV2Error,
    canonical_json_bytes,
    compute_bundle_id,
    sha256_bytes,
    validate_catalog,
    validate_manifest,
    validate_metric,
)


class ModelRunExportError(ValueError):
    """Raised when a governed model run cannot be exported safely."""


@dataclass(frozen=True)
class SectionPlan:
    section_id: str
    availability_status: str
    required_for_model_kind: bool
    payload: Mapping[str, Any] | list[Any] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RunExportPlan:
    model_family_id: str
    model_version_id: str
    run_id: str
    model_kind: str
    publication_channel: str
    publication_status: str
    generated_at: str
    evidence_cutoff: str
    comparability_key: Mapping[str, Any]
    sections: tuple[SectionPlan, ...]
    research_only: bool = True
    trade_ready: bool = False


class ModelRunSourceAdapter(Protocol):
    adapter_id: str

    def build_plan(self, source: Path) -> RunExportPlan:
        """Translate a source-specific artifact into a generic export plan."""


_ADAPTERS: dict[str, type[ModelRunSourceAdapter]] = {}


def register_adapter(adapter: type[ModelRunSourceAdapter]) -> type[ModelRunSourceAdapter]:
    adapter_id = str(getattr(adapter, "adapter_id", ""))
    if not adapter_id:
        raise ModelRunExportError("adapter_id is required")
    if adapter_id in _ADAPTERS:
        raise ModelRunExportError(f"duplicate adapter_id: {adapter_id}")
    _ADAPTERS[adapter_id] = adapter
    return adapter


def get_adapter(adapter_id: str) -> ModelRunSourceAdapter:
    adapter_type = _ADAPTERS.get(adapter_id)
    if adapter_type is None:
        raise ModelRunExportError(f"unknown model-run adapter: {adapter_id}")
    return adapter_type()


def registered_adapters() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRunExportError(f"invalid adapter input: {path}") from exc
    if not isinstance(value, dict):
        raise ModelRunExportError("adapter input must be a JSON object")
    return value


@register_adapter
class DeclarativeJsonAdapter:
    """Reference adapter for predeclared, source-bound model-run sections."""

    adapter_id = "declarative_json_v1"

    def build_plan(self, source: Path) -> RunExportPlan:
        value = _read_object(source)
        raw_sections = value.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ModelRunExportError("declarative adapter sections are missing")
        sections: list[SectionPlan] = []
        for raw in raw_sections:
            if not isinstance(raw, dict):
                raise ModelRunExportError("invalid declarative section")
            availability = str(raw.get("availability_status") or "")
            payload = raw.get("payload")
            reason = raw.get("reason")
            if availability == "available":
                if not isinstance(payload, (dict, list)):
                    raise ModelRunExportError(
                        f"available section {raw.get('section_id')} needs JSON payload"
                    )
                if raw.get("section_id") == "summary" and isinstance(payload, dict):
                    metrics = payload.get("metrics", [])
                    if not isinstance(metrics, list):
                        raise ModelRunExportError("summary metrics must be a list")
                    for metric in metrics:
                        if not isinstance(metric, dict):
                            raise ModelRunExportError("invalid canonical metric")
                        validate_metric(metric)
            else:
                if payload is not None:
                    raise ModelRunExportError(
                        f"unavailable section {raw.get('section_id')} cannot carry payload"
                    )
                if not isinstance(reason, str) or not reason.strip():
                    raise ModelRunExportError(
                        f"unavailable section {raw.get('section_id')} needs reason"
                    )
            sections.append(
                SectionPlan(
                    section_id=str(raw.get("section_id") or ""),
                    availability_status=availability,
                    required_for_model_kind=bool(raw.get("required_for_model_kind")),
                    payload=payload,
                    reason=reason if isinstance(reason, str) else None,
                )
            )
        comparability = value.get("comparability_key")
        if not isinstance(comparability, dict):
            raise ModelRunExportError("comparability_key is missing")
        return RunExportPlan(
            model_family_id=str(value.get("model_family_id") or ""),
            model_version_id=str(value.get("model_version_id") or ""),
            run_id=str(value.get("run_id") or ""),
            model_kind=str(value.get("model_kind") or ""),
            publication_channel=str(value.get("publication_channel") or ""),
            publication_status=str(value.get("publication_status") or ""),
            generated_at=str(value.get("generated_at") or ""),
            evidence_cutoff=str(value.get("evidence_cutoff") or ""),
            comparability_key=comparability,
            sections=tuple(sections),
            research_only=value.get("research_only") is True,
            trade_ready=value.get("trade_ready") is True,
        )


def _section_filename(section_id: str) -> str:
    if not section_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in section_id):
        raise ModelRunExportError(f"unsafe section_id: {section_id!r}")
    return f"{section_id}.json"


def _manifest_for_plan(plan: RunExportPlan, staging: Path) -> dict[str, Any]:
    declarations: list[dict[str, Any]] = []
    for section in plan.sections:
        if section.availability_status == "available":
            if section.payload is None:
                raise ModelRunExportError(f"available section missing payload: {section.section_id}")
            filename = _section_filename(section.section_id)
            encoded = canonical_json_bytes(section.payload)
            (staging / filename).write_bytes(encoded)
            declarations.append(
                {
                    "section_id": section.section_id,
                    "availability_status": "available",
                    "required_for_model_kind": section.required_for_model_kind,
                    "reason": None,
                    "path": filename,
                    "sha256": sha256_bytes(encoded),
                    "byte_size": len(encoded),
                    "media_type": "application/json",
                }
            )
        else:
            declarations.append(
                {
                    "section_id": section.section_id,
                    "availability_status": section.availability_status,
                    "required_for_model_kind": section.required_for_model_kind,
                    "reason": section.reason,
                    "path": None,
                    "sha256": None,
                    "byte_size": None,
                    "media_type": None,
                }
            )
    manifest: dict[str, Any] = {
        "schema_version": "2.0.0",
        "model_family_id": plan.model_family_id,
        "model_version_id": plan.model_version_id,
        "run_id": plan.run_id,
        "bundle_id": "0" * 64,
        "model_kind": plan.model_kind,
        "publication_channel": plan.publication_channel,
        "publication_status": plan.publication_status,
        "generated_at": plan.generated_at,
        "evidence_cutoff": plan.evidence_cutoff,
        "research_only": plan.research_only,
        "trade_ready": plan.trade_ready,
        "comparability_key": dict(plan.comparability_key),
        "sections": declarations,
    }
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    return manifest


def _same_tree(left: Path, right: Path) -> bool:
    left_files = sorted(path.relative_to(left) for path in left.rglob("*") if path.is_file())
    right_files = sorted(path.relative_to(right) for path in right.rglob("*") if path.is_file())
    if left_files != right_files:
        return False
    return all((left / path).read_bytes() == (right / path).read_bytes() for path in left_files)


def export_model_run(
    plan: RunExportPlan,
    *,
    output_root: Path,
) -> Path:
    """Write one immutable bundle atomically and return its manifest path."""

    target = output_root / plan.model_family_id / plan.model_version_id / plan.run_id
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{plan.run_id}.", dir=str(target.parent))
    )
    try:
        manifest = _manifest_for_plan(plan, staging)
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        if target.exists():
            if _same_tree(target, staging):
                return target / "manifest.json"
            raise ModelRunExportError(
                f"immutable run identity collision: {plan.model_family_id}/{plan.model_version_id}/{plan.run_id}"
            )
        os.replace(staging, target)
        return target / "manifest.json"
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def catalog_record(manifest_path: Path, *, catalog_path: Path) -> dict[str, Any]:
    manifest = _read_object(manifest_path)
    validate_manifest(manifest)
    try:
        relative = manifest_path.relative_to(catalog_path.parent).as_posix()
    except ValueError as exc:
        raise ModelRunExportError("manifest must be inside the catalog tree") from exc
    return {
        "model_family_id": manifest["model_family_id"],
        "model_version_id": manifest["model_version_id"],
        "run_id": manifest["run_id"],
        "bundle_id": manifest["bundle_id"],
        "model_kind": manifest["model_kind"],
        "publication_status": manifest["publication_status"],
        "manifest_path": relative,
        "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "evidence_cutoff": manifest["evidence_cutoff"],
    }


def update_catalog(
    manifest_paths: list[Path],
    *,
    catalog_path: Path,
    channel: str,
) -> dict[str, Any]:
    """Update a channel catalog deterministically and atomically."""

    records = [catalog_record(path, catalog_path=catalog_path) for path in manifest_paths]
    records.sort(
        key=lambda row: (
            row["model_family_id"],
            row["model_version_id"],
            row["run_id"],
        )
    )
    if len({(row["model_family_id"], row["model_version_id"], row["run_id"]) for row in records}) != len(records):
        raise ModelRunExportError("duplicate run identity in catalog input")
    generated_at_values = []
    for path in manifest_paths:
        manifest = _read_object(path)
        if manifest["publication_channel"] != channel:
            raise ModelRunExportError(
                f"catalog channel {channel} cannot contain {manifest['publication_channel']} bundle"
            )
        generated_at_values.append(str(manifest["generated_at"]))
    catalog = {
        "schema_version": "2.0.0",
        "channel": channel,
        "generated_at": max(generated_at_values, default="1970-01-01T00:00:00Z"),
        "research_only": True,
        "trade_ready": False,
        "records": records,
    }
    validate_catalog(catalog)
    encoded = canonical_json_bytes(catalog)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    if catalog_path.exists() and catalog_path.read_bytes() == encoded:
        return catalog
    temporary = catalog_path.with_suffix(catalog_path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, catalog_path)
    return catalog


def export_from_adapter(
    *,
    adapter_id: str,
    source: Path,
    output_root: Path,
    catalog_path: Path | None = None,
) -> Path:
    adapter = get_adapter(adapter_id)
    plan = adapter.build_plan(source)
    manifest_path = export_model_run(plan, output_root=output_root)
    if catalog_path is not None:
        manifests = sorted(output_root.rglob("manifest.json"))
        update_catalog(
            manifests,
            catalog_path=catalog_path,
            channel=plan.publication_channel,
        )
    return manifest_path
