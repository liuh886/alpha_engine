"""Build one preview-channel Model Run Bundle v2 from governed formal evidence.

This is the publication seam used by the formal-refresh transaction. Model-specific
refresh/replay code may still produce its in-memory evidence record, but fan-in no
longer hands that record to the production formal catalog. Every strategy is sealed
as Bundle v2 before the cross-strategy publication step.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_bundle_v2_builder import FormalBundleV2BuildError, build_plan
from src.artifacts.model_run_exporter import RunExportPlan, export_model_run
from src.governance.active_strategy_catalog import ActiveStrategy


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
    )
    return export_model_run(preview, output_root=output_root)
