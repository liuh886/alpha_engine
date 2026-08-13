"""Build one preview-channel Model Run Bundle v2 from governed model evidence.

Model-specific refresh/replay code may retain its compact evidence record while it
owns exact historical reproduction. The cross-strategy publication boundary is
native Bundle v2 only: no legacy package path or schema identity is exposed after
this module seals the run.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_bundle_v2_builder import FormalBundleV2BuildError, build_plan
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
