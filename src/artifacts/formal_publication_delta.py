"""Classify whether a formal publication candidate changes governed evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes

DELTA_SCHEMA = "formal_publication_delta_v1"
PLAN_SCHEMA = "formal_refresh_plan_v5"
FAN_IN_SCHEMA = "formal_strategy_fan_in_v2"
REFRESH_RECEIPT_SCHEMA = "formal_refresh_receipt_v2"
MAX_REPORTED_PATHS = 100

_FRESHNESS_KEYS = {
    "schema_version",
    "cutoff_policy",
    "declared_at",
    "markets",
    "next_session_close_utc",
    "required_models",
    "date_range_end_required_models",
    "freshness_receipt_required_models",
    "research_only",
    "trade_ready",
}
_SYNC_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "publication_input",
    "active_strategy_ids",
    "active_model_version_ids",
    "native_promoted_model_ids",
    "retained_inactive_model_version_ids",
    "retained_formal_manifests",
    "preview_catalog_sha256",
    "freshness_source_sha256",
    "strategy_catalog_sha256",
    "formal_bundle_v2_catalog_sha256",
    "formal_bundle_v2_freshness_sha256",
    "model_selection_reopened",
    "historical_evidence_recomputed",
    "research_only",
    "trade_ready",
}
_READINESS_KEYS = {
    "schema_version",
    "built_at",
    "bundle_id",
    "evidence_cutoff",
    "summary",
    "research_only",
    "trade_ready",
}
_MODEL_DATA_BUNDLE_KEYS = {
    "schema_version",
    "built_at",
    "bundle_id",
    "components",
    "contract_id",
    "contract_path",
    "contract_sha256",
    "evidence_cutoff",
    "frontend_indexes",
    "summary",
    "training_profiles",
    "research_only",
    "trade_ready",
}


class FormalPublicationDeltaError(ValueError):
    """Raised when a candidate cannot be classified without weakening evidence."""


@dataclass(frozen=True)
class PublicationRoots:
    formal: Path
    preview: Path
    market_evidence: Path
    model_data: Path

    def by_id(self) -> dict[str, Path]:
        return {
            "formal": self.formal,
            "preview": self.preview,
            "market_evidence": self.market_evidence,
            "model_data": self.model_data,
        }


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(dict(value))


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalPublicationDeltaError(f"invalid publication JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalPublicationDeltaError(f"publication JSON root must be an object: {path}")
    return value


def _assert_document(
    value: Mapping[str, Any],
    *,
    path: Path,
    keys: set[str],
    schema_version: str,
) -> None:
    if set(value) != keys:
        raise FormalPublicationDeltaError(f"unsupported publication fields: {path}")
    if value.get("schema_version") != schema_version:
        raise FormalPublicationDeltaError(f"unsupported publication schema: {path}")
    if value.get("research_only") is not True or value.get("trade_ready") is not False:
        raise FormalPublicationDeltaError(f"invalid research boundary: {path}")


def _project_freshness(root: Path) -> bytes:
    path = root / "freshness.json"
    value = _load_object(path)
    _assert_document(value, path=path, keys=_FRESHNESS_KEYS, schema_version="1.0.0")
    value["declared_at"] = "<run-declared-at>"
    return _object_bytes(value)


def _project_sync_receipt(roots: PublicationRoots) -> bytes:
    path = roots.formal / "formal-bundle-v2-sync-receipt.json"
    value = _load_object(path)
    _assert_document(value, path=path, keys=_SYNC_RECEIPT_KEYS, schema_version="2.0.0")
    if value.get("status") != "active_formal_bundle_v2_built":
        raise FormalPublicationDeltaError(f"invalid formal sync status: {path}")
    freshness_path = roots.formal / "freshness.json"
    freshness_raw_sha = _sha256(freshness_path.read_bytes())
    for field in ("freshness_source_sha256", "formal_bundle_v2_freshness_sha256"):
        if value.get(field) != freshness_raw_sha:
            raise FormalPublicationDeltaError(f"invalid {field}: {path}")
    semantic_sha = _sha256(_project_freshness(roots.formal))
    value["freshness_source_sha256"] = semantic_sha
    value["formal_bundle_v2_freshness_sha256"] = semantic_sha
    return _object_bytes(value)


def _project_readiness(root: Path) -> bytes:
    path = root / "model-data-readiness.json"
    value = _load_object(path)
    _assert_document(value, path=path, keys=_READINESS_KEYS, schema_version="1.1")
    value["built_at"] = "<built-at>"
    return _object_bytes(value)


def _project_model_data_bundle(root: Path) -> bytes:
    path = root / "model-data-bundle.json"
    value = _load_object(path)
    _assert_document(value, path=path, keys=_MODEL_DATA_BUNDLE_KEYS, schema_version="1.1")
    indexes = value.get("frontend_indexes")
    if not isinstance(indexes, Mapping):
        raise FormalPublicationDeltaError(f"model-data frontend indexes are missing: {path}")
    readiness = indexes.get("model_data_readiness")
    if not isinstance(readiness, Mapping) or set(readiness) != {"path", "sha256"}:
        raise FormalPublicationDeltaError(f"model-data readiness index is invalid: {path}")
    if readiness.get("path") != "model-data-readiness.json":
        raise FormalPublicationDeltaError(f"model-data readiness path is invalid: {path}")
    readiness_path = root / "model-data-readiness.json"
    if readiness.get("sha256") != _sha256(readiness_path.read_bytes()):
        raise FormalPublicationDeltaError(f"model-data readiness digest is invalid: {path}")
    projected_indexes = dict(indexes)
    projected_readiness = dict(readiness)
    projected_readiness["sha256"] = _sha256(_project_readiness(root))
    projected_indexes["model_data_readiness"] = projected_readiness
    value["frontend_indexes"] = projected_indexes
    value["built_at"] = "<built-at>"
    return _object_bytes(value)


def _semantic_bytes(roots: PublicationRoots, root_id: str, relative: str) -> bytes:
    root = roots.by_id()[root_id]
    path = root / relative
    if path.is_symlink():
        raise FormalPublicationDeltaError(f"publication symlink is not allowed: {path}")
    if root_id == "formal" and relative == "freshness.json":
        return _project_freshness(root)
    if root_id == "formal" and relative == "formal-bundle-v2-sync-receipt.json":
        return _project_sync_receipt(roots)
    if root_id == "model_data" and relative == "model-data-readiness.json":
        return _project_readiness(root)
    if root_id == "model_data" and relative == "model-data-bundle.json":
        return _project_model_data_bundle(root)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FormalPublicationDeltaError(f"cannot read publication file: {path}") from exc


def _file_set(root: Path) -> set[str]:
    if not root.is_dir():
        raise FormalPublicationDeltaError(f"publication root is missing: {root}")
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _root_digest(records: list[tuple[str, str]]) -> str:
    payload = [{"path": path, "sha256": digest} for path, digest in records]
    return _sha256(canonical_json_bytes(payload))


def _bounded(values: list[str]) -> list[str]:
    return values[:MAX_REPORTED_PATHS]


def _required(reason: str, *, preconditions: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DELTA_SCHEMA,
        "status": "publication_required",
        "publication_required": True,
        "reason": reason,
        "preconditions": dict(preconditions),
        "root_deltas": [],
        "semantic_changed_path_count": 0,
        "semantic_changed_paths": [],
        "raw_metadata_only_path_count": 0,
        "raw_metadata_only_paths": [],
        "research_only": True,
        "trade_ready": False,
    }


def _preconditions(
    plan: Mapping[str, Any],
    fan_in: Mapping[str, Any],
    refresh_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], str | None]:
    documents = (
        (plan, PLAN_SCHEMA, "plan"),
        (fan_in, FAN_IN_SCHEMA, "fan-in"),
        (refresh_receipt, REFRESH_RECEIPT_SCHEMA, "refresh receipt"),
    )
    for value, schema, label in documents:
        if value.get("schema_version") != schema:
            raise FormalPublicationDeltaError(f"unsupported {label} schema")
        if value.get("research_only") is not True or value.get("trade_ready") is not False:
            raise FormalPublicationDeltaError(f"invalid {label} research boundary")

    execution = plan.get("execution_task_matrix")
    if not isinstance(execution, list):
        raise FormalPublicationDeltaError("formal plan execution matrix is invalid")
    changed = fan_in.get("changed_strategy_ids")
    retained = fan_in.get("retained_strategy_ids")
    if not isinstance(changed, list) or not isinstance(retained, list):
        raise FormalPublicationDeltaError("formal fan-in delta fields are invalid")
    summary = {
        "plan_refresh_required": plan.get("refresh_required"),
        "execution_task_count": len(execution),
        "fan_in_status": fan_in.get("status"),
        "changed_strategy_ids": list(changed),
        "retained_strategy_ids": list(retained),
        "refresh_status": refresh_receipt.get("status"),
    }
    if plan.get("refresh_required") is not False or execution:
        return summary, "plan_requires_refresh"
    if fan_in.get("status") != "complete" or changed or retained:
        return summary, "fan_in_not_semantically_idle"
    if refresh_receipt.get("status") != "candidate_ready_for_review":
        return summary, "refresh_not_ready_for_review"

    active_strategies = plan.get("active_strategy_ids")
    active_models = plan.get("active_model_version_ids")
    if not isinstance(active_strategies, list) or not isinstance(active_models, list):
        raise FormalPublicationDeltaError("formal plan active identity is invalid")
    if fan_in.get("expected_strategy_ids") != active_strategies:
        raise FormalPublicationDeltaError("formal fan-in strategy identity mismatch")
    if refresh_receipt.get("active_strategy_ids") != active_strategies:
        raise FormalPublicationDeltaError("formal refresh strategy identity mismatch")
    if refresh_receipt.get("active_model_version_ids") != active_models:
        raise FormalPublicationDeltaError("formal refresh model identity mismatch")
    if refresh_receipt.get("target_cutoffs") != plan.get("target_cutoffs"):
        raise FormalPublicationDeltaError("formal refresh cutoff identity mismatch")
    if plan.get("stale_model_ids") != [] or plan.get("mtm_refresh_model_ids") != []:
        raise FormalPublicationDeltaError("formal no-op plan contains stale models")
    if plan.get("planned_noop_strategy_ids") != active_strategies:
        raise FormalPublicationDeltaError("formal no-op plan membership mismatch")
    if fan_in.get("executed_strategy_ids") != []:
        raise FormalPublicationDeltaError("formal no-op fan-in executed strategies")
    if fan_in.get("planned_noop_strategy_ids") != active_strategies:
        raise FormalPublicationDeltaError("formal no-op fan-in membership mismatch")
    return summary, None


def _assert_candidate_identity(
    candidate: PublicationRoots,
    plan: Mapping[str, Any],
) -> None:
    freshness_path = candidate.formal / "freshness.json"
    freshness = _load_object(freshness_path)
    _assert_document(
        freshness,
        path=freshness_path,
        keys=_FRESHNESS_KEYS,
        schema_version="1.0.0",
    )
    if freshness.get("markets") != plan.get("target_cutoffs"):
        raise FormalPublicationDeltaError("candidate freshness cutoff identity mismatch")
    if freshness.get("required_models") != plan.get("active_model_version_ids"):
        raise FormalPublicationDeltaError("candidate freshness model identity mismatch")

    sync_path = candidate.formal / "formal-bundle-v2-sync-receipt.json"
    sync_receipt = _load_object(sync_path)
    _project_sync_receipt(candidate)
    if sync_receipt.get("active_strategy_ids") != plan.get("active_strategy_ids"):
        raise FormalPublicationDeltaError("candidate sync strategy identity mismatch")
    if sync_receipt.get("active_model_version_ids") != plan.get(
        "active_model_version_ids"
    ):
        raise FormalPublicationDeltaError("candidate sync model identity mismatch")


def classify_publication_delta(
    *,
    current: PublicationRoots,
    candidate: PublicationRoots,
    plan: Mapping[str, Any],
    fan_in: Mapping[str, Any],
    refresh_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a fail-closed receipt for the candidate publication delta."""

    preconditions, required_reason = _preconditions(plan, fan_in, refresh_receipt)
    if required_reason is not None:
        return _required(required_reason, preconditions=preconditions)
    _assert_candidate_identity(candidate, plan)

    root_deltas: list[dict[str, Any]] = []
    semantic_changed: list[str] = []
    raw_metadata_only: list[str] = []
    for root_id in current.by_id():
        current_files = _file_set(current.by_id()[root_id])
        candidate_files = _file_set(candidate.by_id()[root_id])
        missing = sorted(current_files - candidate_files)
        extra = sorted(candidate_files - current_files)
        common = sorted(current_files & candidate_files)
        current_records: list[tuple[str, str]] = []
        candidate_records: list[tuple[str, str]] = []
        root_semantic_changed: list[str] = []
        root_raw_metadata_only: list[str] = []
        for relative in common:
            current_raw = (current.by_id()[root_id] / relative).read_bytes()
            candidate_raw = (candidate.by_id()[root_id] / relative).read_bytes()
            current_semantic = _semantic_bytes(current, root_id, relative)
            candidate_semantic = _semantic_bytes(candidate, root_id, relative)
            current_records.append((relative, _sha256(current_semantic)))
            candidate_records.append((relative, _sha256(candidate_semantic)))
            qualified = f"{root_id}/{relative}"
            if current_semantic != candidate_semantic:
                root_semantic_changed.append(qualified)
            elif current_raw != candidate_raw:
                root_raw_metadata_only.append(qualified)
        semantic_changed.extend(f"{root_id}/{path}" for path in missing + extra)
        semantic_changed.extend(root_semantic_changed)
        raw_metadata_only.extend(root_raw_metadata_only)
        root_deltas.append(
            {
                "root_id": root_id,
                "current_file_count": len(current_files),
                "candidate_file_count": len(candidate_files),
                "missing_path_count": len(missing),
                "missing_paths": _bounded(missing),
                "extra_path_count": len(extra),
                "extra_paths": _bounded(extra),
                "semantic_changed_path_count": len(root_semantic_changed),
                "semantic_changed_paths": _bounded(root_semantic_changed),
                "raw_metadata_only_path_count": len(root_raw_metadata_only),
                "raw_metadata_only_paths": _bounded(root_raw_metadata_only),
                "current_semantic_sha256": _root_digest(current_records),
                "candidate_semantic_sha256": _root_digest(candidate_records),
            }
        )

    publication_required = bool(semantic_changed)
    return {
        "schema_version": DELTA_SCHEMA,
        "status": "publication_required" if publication_required else "semantic_no_change",
        "publication_required": publication_required,
        "reason": "semantic_difference" if publication_required else "semantic_identity",
        "preconditions": preconditions,
        "root_deltas": root_deltas,
        "semantic_changed_path_count": len(semantic_changed),
        "semantic_changed_paths": _bounded(semantic_changed),
        "raw_metadata_only_path_count": len(raw_metadata_only),
        "raw_metadata_only_paths": _bounded(raw_metadata_only),
        "research_only": True,
        "trade_ready": False,
    }
