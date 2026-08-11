"""Promote the complete governed US x1.2 Bundle v2 evidence into the formal channel."""

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

MODEL_ID = "us_x1_2"
MODEL_FAMILY_ID = "us_ranker"
SUPERSEDED_FORMAL_MODEL = "us_x1_1"
PROMOTION_AUTHORITY = "explicit_user_direction_2026_08_12"


class USX12FormalPromotionError(ValueError):
    """Raised when the governed US x1.2 evidence cannot be promoted exactly."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise USX12FormalPromotionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise USX12FormalPromotionError(f"JSON root must be an object: {path}")
    return value


def _verify_source_bundle(run_dir: Path) -> dict[str, Any]:
    manifest = _object(run_dir / "manifest.json")
    validate_manifest(manifest)
    if (
        manifest.get("model_family_id") != MODEL_FAMILY_ID
        or manifest.get("model_version_id") != MODEL_ID
        or manifest.get("publication_channel") != "preview"
        or manifest.get("publication_status") != "ci_validated_preview"
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        raise USX12FormalPromotionError("US x1.2 source bundle is not the governed preview")
    for section in manifest["sections"]:
        if section["availability_status"] != "available":
            continue
        path = run_dir / str(section["path"])
        if not path.is_file():
            raise USX12FormalPromotionError(f"source section is missing: {section['section_id']}")
        data = path.read_bytes()
        if len(data) != section["byte_size"] or hashlib.sha256(data).hexdigest() != section["sha256"]:
            raise USX12FormalPromotionError(f"source section identity mismatch: {section['section_id']}")
    return manifest


def _formal_completeness(value: object) -> dict[str, Any]:
    completeness = copy.deepcopy(value) if isinstance(value, Mapping) else {}
    completeness.update(
        {
            "status": "complete",
            "quantity": "not_applicable_without_governed_capital_contract",
            "not_applicable": ["brokerage_quantity", "brokerage_fill_price"],
            "missing": [],
        }
    )
    return completeness


def _rewrite_summary(path: Path) -> None:
    summary = _object(path)
    summary["baseline_status"] = "accepted_formal_baseline"
    summary["formal_acceptance_status"] = "accepted_by_explicit_user_direction"
    summary["formal_promotion_authority"] = PROMOTION_AUTHORITY
    summary["trade_readiness_status"] = "prospective_gate_pending"
    summary["decision_status"] = "absent"
    summary["evidence_contract"] = "native_formal_bundle_v2"
    summary["evidence_completeness"] = _formal_completeness(
        summary.get("evidence_completeness")
    )
    path.write_bytes(canonical_json_bytes(summary))


def _rewrite_risk(path: Path) -> None:
    risk = _object(path)
    risk["interpretation_limit"] = (
        "Accepted formal research evidence. The untouched six-month prospective gate "
        "remains a trade-readiness requirement and is not claimed as passed."
    )
    path.write_bytes(canonical_json_bytes(risk))


def _rewrite_robustness(path: Path) -> None:
    robustness = _object(path)
    robustness["interpretation_limit"] = (
        "2026H1 remains reporting-only and 2026H2 remains an incomplete prospective "
        "window; neither is reclassified as untouched trade-readiness evidence."
    )
    path.write_bytes(canonical_json_bytes(robustness))


def _rewrite_diagnostics(path: Path) -> None:
    diagnostics = _object(path)
    diagnostics["evidence_completeness"] = _formal_completeness(
        diagnostics.get("evidence_completeness")
    )
    diagnostics["interpretation_notes"] = [
        "US x1.2 is the accepted formal research baseline by explicit user direction dated 2026-08-12.",
        "The untouched six-month prospective gate remains pending for trade readiness only; trade_ready=false.",
        "Entry and exit prices are governed adjusted-close model evidence, not brokerage fills.",
        "Normalized notional uses NAV=1 because no governed portfolio-capital or brokerage quantity contract exists.",
        "Brokerage quantity and fill price are not applicable under this evidence contract and are never fabricated.",
    ]
    path.write_bytes(canonical_json_bytes(diagnostics))


def _rewrite_lineage(path: Path, source_manifest: Mapping[str, Any]) -> None:
    lineage = _object(path)
    lineage.pop("formal_acceptance_gate_passed", None)
    lineage.pop("formal_baseline_superseded_for_research", None)
    lineage.update(
        {
            "source_preview_bundle_id": source_manifest["bundle_id"],
            "formal_promotion_authority": PROMOTION_AUTHORITY,
            "formal_acceptance_basis": "explicit_user_direction",
            "formal_baseline_superseded": SUPERSEDED_FORMAL_MODEL,
            "prospective_gate_scope": "trade_readiness_only",
            "prospective_gate_status": "pending",
            "model_selection_reopened": False,
            "research_only": True,
            "trade_ready": False,
        }
    )
    path.write_bytes(canonical_json_bytes(lineage))


def promote_preview_bundle(source_run_dir: Path, output_root: Path) -> Path:
    """Copy exact governed evidence, rewrite publication metadata, and seal a formal bundle."""

    source_run_dir = source_run_dir.resolve()
    output_root = output_root.resolve()
    source_manifest = _verify_source_bundle(source_run_dir)
    target = (
        output_root
        / MODEL_FAMILY_ID
        / MODEL_ID
        / str(source_manifest["run_id"])
    )
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_run_dir, target)

    _rewrite_summary(target / "summary.json")
    _rewrite_risk(target / "risk.json")
    _rewrite_robustness(target / "robustness.json")
    _rewrite_diagnostics(target / "diagnostics.json")
    _rewrite_lineage(target / "lineage.json", source_manifest)

    manifest = copy.deepcopy(source_manifest)
    manifest["publication_channel"] = "formal"
    manifest["publication_status"] = "accepted_formal_baseline"
    for section in manifest["sections"]:
        if section["availability_status"] != "available":
            if section["section_id"] == "decision":
                section["reason"] = (
                    "Formal promotion authority is retained in governed model metadata and lineage; "
                    "no circular decision receipt is embedded in the bundle manifest."
                )
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
