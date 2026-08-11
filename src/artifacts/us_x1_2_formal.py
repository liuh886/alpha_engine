"""Promote complete governed US x1.2 Bundle v2 evidence into the formal channel."""

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
from src.artifacts.performance_semantics import SCHEMA_VERSION as PERFORMANCE_SEMANTICS_SCHEMA

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


def _formal_metrics(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise USX12FormalPromotionError("US x1.2 canonical metrics are invalid")
    metrics = [copy.deepcopy(dict(row)) for row in value]
    for metric in metrics:
        if metric.get("estimator") == "governed_us_x1_2_preview_trace":
            metric["estimator"] = "governed_us_x1_2_trace"
        if metric.get("metric_id") == "ic" and metric.get("availability_status") == "not_computed":
            metric["unavailable_reason"] = (
                "The governed US x1.2 builder does not compute raw IC; Rank IC is retained."
            )
    return metrics


def _rewrite_summary(path: Path) -> None:
    source = _object(path)
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": MODEL_FAMILY_ID,
        "model_version_id": MODEL_ID,
        "run_id": source["run_id"],
        "display_name": "US x1.2",
        "market": "us",
        "benchmark": "QQQ",
        "baseline_status": "accepted_formal_baseline",
        "formal_acceptance_status": "accepted_by_explicit_user_direction",
        "formal_promotion_authority": PROMOTION_AUTHORITY,
        "trade_readiness_status": "prospective_gate_pending",
        "decision_status": "absent",
        "evidence_contract": "native_formal_bundle_v2",
        "metrics": _formal_metrics(source.get("metrics")),
        "evidence_completeness": _formal_completeness(source.get("evidence_completeness")),
        "research_only": True,
        "trade_ready": False,
    }
    path.write_bytes(canonical_json_bytes(summary))


def _rewrite_performance(path: Path) -> None:
    """Normalize the accepted US x1.2 evidence onto the formal semantics schema."""

    source = _object(path)
    raw = source.get("performance_semantics")
    if not isinstance(raw, Mapping):
        raise USX12FormalPromotionError("US x1.2 performance semantics are missing")
    cost = raw.get("cost")
    if not isinstance(cost, Mapping):
        raise USX12FormalPromotionError("US x1.2 cost semantics are missing")
    source["performance_semantics"] = {
        **dict(raw),
        "schema_version": PERFORMANCE_SEMANTICS_SCHEMA,
        "trace_frequency": "non_overlapping_10_session",
        "session_unit": "provider_session",
        "execution_delay_sessions": 0,
        "holding_period_sessions": 10,
        "holding_end_offset_sessions": 10,
        "performance_date_field": "holding_end_date",
        "cost": {
            **dict(cost),
            "row_cost_field": "transaction_cost",
            "browser_recomputation_permitted": False,
        },
        "source": "governed_us_x1_2_formal_evidence",
        "research_only": True,
        "trade_ready": False,
    }
    path.write_bytes(canonical_json_bytes(source))


def _rewrite_risk(path: Path) -> None:
    source = _object(path)
    risk = {
        **source,
        "metrics": _formal_metrics(source.get("metrics")),
        "interpretation_limit": (
            "Accepted formal research evidence. The untouched six-month prospective gate "
            "remains a trade-readiness requirement and is not claimed as passed."
        ),
    }
    path.write_bytes(canonical_json_bytes(risk))


def _rewrite_robustness(path: Path) -> None:
    robustness = _object(path)
    robustness["interpretation_limit"] = (
        "2026H1 remains reporting-only and 2026H2 remains an incomplete prospective "
        "window; neither is reclassified as untouched trade-readiness evidence."
    )
    path.write_bytes(canonical_json_bytes(robustness))


def _rewrite_diagnostics(path: Path) -> None:
    source = _object(path)
    diagnostics = {
        "schema_version": "2.0.0",
        "evidence_completeness": _formal_completeness(source.get("evidence_completeness")),
        "interpretation_notes": [
            "US x1.2 is the accepted formal research baseline by explicit user direction dated 2026-08-12.",
            "The untouched six-month prospective gate remains pending for trade readiness only; trade_ready=false.",
            "Entry and exit prices are governed adjusted-close model evidence, not brokerage fills.",
            "Normalized notional uses NAV=1 because no governed portfolio-capital or brokerage quantity contract exists.",
            "Brokerage quantity and fill price are not applicable under this evidence contract and are never fabricated.",
        ],
        "research_only": True,
        "trade_ready": False,
    }
    path.write_bytes(canonical_json_bytes(diagnostics))


def _rewrite_lineage(path: Path, source_manifest: Mapping[str, Any]) -> None:
    source = _object(path)
    lineage = {
        "schema_version": "2.0.0",
        "source_preview_bundle_id": source_manifest["bundle_id"],
        "source_model_config": source.get("source_model_config"),
        "source_model_config_sha256": source.get("source_model_config_sha256"),
        "evidence_builder_source_sha256": source.get("builder_source_sha256"),
        "universe_config_sha256": source.get("universe_config_sha256"),
        "classification_config_sha256": source.get("classification_config_sha256"),
        "provider_identity_sha256": source.get("provider_identity_sha256"),
        "calibration_identity": source.get("calibration_identity"),
        "selected_candidate": source.get("selected_candidate"),
        "certification_workflow_run_id": source.get("certification_workflow_run_id"),
        "formal_promotion_authority": PROMOTION_AUTHORITY,
        "formal_acceptance_basis": "explicit_user_direction",
        "formal_baseline_superseded": SUPERSEDED_FORMAL_MODEL,
        "prospective_gate_scope": "trade_readiness_only",
        "prospective_gate_status": "pending",
        "historical_evidence_recomputed": source.get("historical_evidence_recomputed") is True,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    path.write_bytes(canonical_json_bytes(lineage))


def promote_preview_bundle(source_run_dir: Path, output_root: Path) -> Path:
    """Copy exact governed evidence, rewrite publication metadata, and seal a formal bundle."""

    source_run_dir = source_run_dir.resolve()
    output_root = output_root.resolve()
    source_manifest = _verify_source_bundle(source_run_dir)
    target = output_root / MODEL_FAMILY_ID / MODEL_ID / str(source_manifest["run_id"])
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_run_dir, target)

    _rewrite_summary(target / "summary.json")
    _rewrite_performance(target / "performance.json")
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
