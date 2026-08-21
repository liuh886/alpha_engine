"""Build one preview-channel Model Run Bundle v2 from governed model evidence.

Model-specific refresh/replay code may retain its compact evidence record while it
owns exact historical reproduction. The cross-strategy publication boundary is
native Bundle v2 only: no legacy package path or schema identity is exposed after
this module seals the run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_bundle_v2_builder import FormalBundleV2BuildError, build_plan
from src.artifacts.model_run_bundle_v2 import ModelRunBundleV2Error, validate_manifest
from src.artifacts.model_run_exporter import RunExportPlan, SectionPlan, export_model_run
from src.governance.active_strategy_catalog import ActiveStrategy
from src.governance.model_contract import ModelContractError, load_performance_semantics


class FormalPreviewBuildError(ValueError):
    """Raised when governed evidence cannot be sealed as a preview Bundle v2."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalPreviewBuildError(f"invalid formal evidence JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalPreviewBuildError(f"formal evidence root must be an object: {path}")
    return value


def _complete(value: object) -> dict[str, Any]:
    completeness = dict(value) if isinstance(value, Mapping) else {}
    missing = completeness.get("missing")
    if completeness.get("status") != "complete" or missing != []:
        raise FormalPreviewBuildError("governed evidence is not complete enough for publication")
    completeness.update(
        {
            "status": "complete",
            "quantity": "not_applicable_without_governed_capital_contract",
            "not_applicable": ["brokerage_quantity", "brokerage_fill_price"],
            "missing": [],
        }
    )
    return completeness


def _with_provisional_mtm(plan: RunExportPlan, source_path: Path) -> RunExportPlan:
    """Project the governed ranker MTM row into the Bundle v2 performance section."""

    package = _object(source_path)
    provisional = package.get("provisional_mtm")
    if provisional is None:
        return plan
    if not isinstance(provisional, Mapping):
        raise FormalPreviewBuildError(f"provisional_mtm must be an object: {source_path}")
    row = provisional.get("performance_row")
    as_of = str(provisional.get("as_of") or "")
    if (
        provisional.get("schema_version") != "ranker_provisional_mtm_v1"
        or provisional.get("research_only") is not True
        or provisional.get("trade_ready") is not False
        or not isinstance(row, Mapping)
        or row.get("provisional_mtm") is not True
        or row.get("settlement_status") != "provisional_mtm"
        or str(row.get("holding_end_date") or "") != as_of
        or as_of != plan.evidence_cutoff
    ):
        raise FormalPreviewBuildError(f"invalid provisional MTM contract: {source_path}")

    sections = []
    projected = False
    for section in plan.sections:
        if section.section_id != "performance":
            sections.append(section)
            continue
        if not isinstance(section.payload, Mapping):
            raise FormalPreviewBuildError(f"performance section unavailable for MTM: {source_path}")
        payload = dict(section.payload)
        report = payload.get("report")
        if not isinstance(report, list):
            raise FormalPreviewBuildError(f"performance report invalid: {source_path}")
        payload["report"] = [*report, dict(row)]
        payload["source_fields"] = ["report", "provisional_mtm.performance_row"]
        payload["provisional_mtm_projected"] = True
        sections.append(replace(section, payload=payload))
        projected = True
    if not projected:
        raise FormalPreviewBuildError(f"performance section missing for MTM: {source_path}")
    return replace(plan, sections=tuple(sections))


def _base_preview_sections(
    run_dir: Path,
    plan: RunExportPlan,
) -> dict[str, SectionPlan]:
    manifest = _object(run_dir / "manifest.json")
    try:
        validate_manifest(manifest)
    except ModelRunBundleV2Error as exc:
        raise FormalPreviewBuildError(f"invalid base preview manifest: {run_dir}") from exc
    if (
        manifest.get("model_family_id") != plan.model_family_id
        or manifest.get("model_version_id") != plan.model_version_id
        or manifest.get("model_kind") != plan.model_kind
        or manifest.get("publication_channel") != "preview"
        or manifest.get("publication_status") != "ci_validated_preview"
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        raise FormalPreviewBuildError("base preview identity or research boundary changed")

    sections: dict[str, SectionPlan] = {}
    for declaration in manifest["sections"]:
        section_id = str(declaration["section_id"])
        availability = str(declaration["availability_status"])
        if availability != "available":
            sections[section_id] = SectionPlan(
                section_id,
                availability,
                bool(declaration["required_for_model_kind"]),
                reason=str(declaration.get("reason") or ""),
            )
            continue
        path = (run_dir / str(declaration["path"])).resolve()
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FormalPreviewBuildError(f"base preview section escapes run: {section_id}") from exc
        if not path.is_file():
            raise FormalPreviewBuildError(f"base preview section is missing: {section_id}")
        data = path.read_bytes()
        if (
            len(data) != declaration["byte_size"]
            or hashlib.sha256(data).hexdigest() != declaration["sha256"]
        ):
            raise FormalPreviewBuildError(f"base preview section identity changed: {section_id}")
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise FormalPreviewBuildError(f"base preview section JSON is invalid: {section_id}") from exc
        if not isinstance(payload, (dict, list)):
            raise FormalPreviewBuildError(f"base preview section root is invalid: {section_id}")
        sections[section_id] = SectionPlan(
            section_id,
            availability,
            bool(declaration["required_for_model_kind"]),
            payload=payload,
        )
    if set(sections) != {section.section_id for section in plan.sections}:
        raise FormalPreviewBuildError("base preview section inventory changed")
    return sections


def _preserve_mtm_base_preview(
    plan: RunExportPlan,
    source_path: Path,
    base_preview_run: Path,
) -> RunExportPlan:
    """Keep frozen native sections while replacing only the MTM performance view."""

    package = _object(source_path)
    provisional = package.get("provisional_mtm")
    if not isinstance(provisional, Mapping):
        raise FormalPreviewBuildError("base preview projection requires provisional MTM")
    base = _base_preview_sections(base_preview_run.resolve(), plan)
    projected: list[SectionPlan] = []
    for section in plan.sections:
        retained = base[section.section_id]
        if section.section_id == "performance":
            projected.append(
                replace(
                    section,
                    required_for_model_kind=retained.required_for_model_kind,
                )
            )
            continue
        if section.section_id == "summary" and isinstance(retained.payload, Mapping):
            summary = dict(retained.payload)
            summary["run_id"] = plan.run_id
            projected.append(replace(retained, payload=summary))
            continue
        if section.section_id == "lineage" and isinstance(retained.payload, Mapping):
            lineage = dict(retained.payload)
            lineage["mtm_projection"] = dict(provisional)
            projected.append(replace(retained, payload=lineage))
            continue
        projected.append(retained)
    return replace(plan, sections=tuple(projected))


def _native_sections(
    plan: RunExportPlan,
    strategy: ActiveStrategy,
) -> tuple[SectionPlan, ...]:
    """Remove legacy publication identity and bind methodology to the model contract."""

    try:
        governed_semantics = load_performance_semantics(strategy)
    except ModelContractError as exc:
        raise FormalPreviewBuildError(str(exc)) from exc

    sections: list[SectionPlan] = []
    for section in plan.sections:
        payload = section.payload
        if section.availability_status != "available" or not isinstance(payload, Mapping):
            sections.append(section)
            continue

        value = dict(payload)
        if section.section_id == "summary":
            source_sha = value.pop("source_package_sha256", None)
            if source_sha:
                value["evidence_source_sha256"] = source_sha
            value["evidence_contract"] = "native_bundle_v2"
            value["model_contract"] = strategy.model_contract
            value["evidence_completeness"] = _complete(value.get("evidence_completeness"))
        elif section.section_id == "performance":
            value["performance_semantics"] = governed_semantics
        elif section.section_id == "diagnostics":
            if "evidence_completeness" in value:
                value["evidence_completeness"] = _complete(value.get("evidence_completeness"))
        elif section.section_id == "lineage":
            source_sha = value.get("source_sha256") or value.get("source_package_sha256")
            value = {
                "schema_version": "2.0.0",
                "publication_origin": "governed_model_evidence",
                "model_contract": strategy.model_contract,
                "evidence_source_sha256": source_sha,
                "source_backtest_id": value.get("source_backtest_id"),
                "source_evidence": value.get("source_evidence"),
                "source_freshness": value.get("source_freshness"),
                "source_evidence_completeness": _complete(
                    value.get("source_evidence_completeness")
                ),
                "historical_evidence_recomputed": value.get(
                    "historical_evidence_recomputed"
                ) is True,
                "model_selection_reopened": False,
                "research_only": True,
                "trade_ready": False,
            }
        sections.append(replace(section, payload=value))
    return tuple(sections)


def build_preview_bundle(
    source_path: Path,
    strategy: ActiveStrategy,
    *,
    output_root: Path,
) -> Path:
    """Seal one governed strategy evidence record into the preview Bundle v2 channel."""

    try:
        plan = build_plan(source_path, strategy)
    except FormalBundleV2BuildError as exc:
        raise FormalPreviewBuildError(str(exc)) from exc
    plan = _with_provisional_mtm(plan, source_path)
    preview = replace(
        plan,
        publication_channel="preview",
        publication_status="ci_validated_preview",
        sections=_native_sections(plan, strategy),
    )
    return export_model_run(preview, output_root=output_root)


def project_provisional_mtm_preview(
    source_path: Path,
    strategy: ActiveStrategy,
    *,
    base_preview_run: Path,
    output_root: Path,
) -> Path:
    """Project one MTM row without flattening the native preview evidence closure."""

    try:
        plan = build_plan(source_path, strategy)
    except FormalBundleV2BuildError as exc:
        raise FormalPreviewBuildError(str(exc)) from exc
    plan = _with_provisional_mtm(plan, source_path)
    preview = replace(
        plan,
        publication_channel="preview",
        publication_status="ci_validated_preview",
        sections=_native_sections(plan, strategy),
    )
    preserved = _preserve_mtm_base_preview(preview, source_path, base_preview_run)
    return export_model_run(preserved, output_root=output_root)
