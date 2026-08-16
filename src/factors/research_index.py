"""Agent-facing derived index over canonical Alpha Engine factor definitions.

The index never owns formulas. It projects registered :class:`FactorLibrary`
sources, active model contracts, and immutable factor-evidence records into one
queryable JSON document. Formula identity remains authoritative in the source
libraries; evidence remains authoritative in linked receipts.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.factors.evidence import EVIDENCE_STATUSES, FactorEvidenceRecord, load_factor_evidence
from src.factors.library import FactorLibrary, load_factor_library

INDEX_SCHEMA_VERSION = "1.0"
REGISTRY_SCHEMA_VERSION = "1.0"
_STATUS_PRECEDENCE = {
    "model_active": 50,
    "validated": 40,
    "candidate": 30,
    "diagnostic_only": 20,
    "rejected": 10,
}
_HORIZON_SUFFIX = re.compile(r"(?:_?\d+d?|\d+)$", re.IGNORECASE)


def _repository_path(root: Path, raw: str) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / raw).resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"factor catalog path escapes repository root: {raw}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_factor_catalog_registry(
    path: str | Path,
    *,
    root: str | Path,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    source = Path(path)
    if not source.is_absolute():
        source = root_path / source
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or str(payload.get("schema_version")) != REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"factor catalog registry requires schema_version={REGISTRY_SCHEMA_VERSION}")
    if not str(payload.get("catalog_id", "")).strip():
        raise ValueError("factor catalog registry requires catalog_id")
    for key in ("library_sources", "active_model_sources", "evidence_sources"):
        values = payload.get(key)
        if not isinstance(values, list) or not values:
            raise ValueError(f"factor catalog registry requires non-empty {key}")
        normalized = [str(value).strip() for value in values]
        if not all(normalized) or len(normalized) != len(set(normalized)):
            raise ValueError(f"factor catalog registry {key} must be unique non-empty paths")
        for value in normalized:
            _repository_path(root_path, value)
    return payload


def _mechanism_stem(factor_id: str) -> str:
    local = factor_id.split(".", 1)[1] if "." in factor_id else factor_id
    parts = local.split(".")
    leaf = _HORIZON_SUFFIX.sub("", parts[-1]).rstrip("_") or parts[-1]
    if len(parts) == 1:
        return leaf
    return ".".join([*parts[:-1], leaf])


def _library_projection(
    root: Path,
    sources: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, FactorLibrary]]:
    entries: dict[str, dict[str, Any]] = {}
    libraries: dict[str, FactorLibrary] = {}
    for source in sources:
        library = load_factor_library(_repository_path(root, source))
        libraries[source] = library
        memberships: dict[str, list[str]] = {}
        for group in library.groups.values():
            for factor_id in group.factor_ids:
                memberships.setdefault(factor_id, []).append(group.name)
        for definition in library.catalog.definitions:
            if definition.factor_id in entries:
                raise ValueError(f"canonical factor id has multiple registry owners: {definition.factor_id}")
            entries[definition.factor_id] = {
                "factor_id": definition.factor_id,
                "factor_version": definition.factor_version,
                "display_name": definition.display_name,
                "namespace": definition.namespace,
                "category": definition.information_family,
                "mechanism": _mechanism_stem(definition.factor_id),
                "expression": definition.expression,
                "implementation_hash": definition.implementation_hash,
                "definition_status": definition.status,
                "markets": list(definition.markets),
                "required_fields": list(definition.required_fields),
                "minimum_lookback": definition.minimum_lookback,
                "availability_lag_sessions": definition.availability_lag_sessions,
                "source_name": definition.source_name,
                "source_version": definition.source_version,
                "source_reference": definition.source_reference,
                "canonical_source": source,
                "groups": sorted(memberships.get(definition.factor_id, [])),
                "active_models": {"us": [], "cn": []},
                "market_status": {},
                "evidence": {"us": [], "cn": []},
            }
    return entries, libraries


def _model_factor_contract(payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    market = str(payload.get("market", ""))
    if market not in {"us", "cn"}:
        raise ValueError("registered active model must declare market us/cn")
    model_id = str(payload.get("model_id", "")).strip()
    features = payload.get("features")
    if not model_id or not isinstance(features, dict):
        raise ValueError("registered active model requires model_id/features")
    factor_ids = [str(value).strip() for value in features.get("factor_ids") or []]
    if not factor_ids or len(factor_ids) != len(set(factor_ids)):
        raise ValueError(f"active model {model_id} factor_ids must be unique and non-empty")
    sources: list[str] = []
    primary = features.get("library", features.get("primary_library"))
    if primary:
        sources.append(str(primary))
    additional = features.get("additional_library_sources") or []
    if not isinstance(additional, list):
        raise ValueError(f"active model {model_id} additional_library_sources must be a list")
    sources.extend(str(value) for value in additional)
    return market, factor_ids, sources


def _apply_active_models(
    entries: dict[str, dict[str, Any]],
    *,
    root: Path,
    model_sources: list[str],
    registered_libraries: set[str],
) -> None:
    for source in model_sources:
        payload = yaml.safe_load(_repository_path(root, source).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"active model source is not a mapping: {source}")
        market, factor_ids, libraries = _model_factor_contract(payload)
        model_id = str(payload["model_id"])
        missing_libraries = sorted(set(libraries) - registered_libraries)
        if missing_libraries:
            raise ValueError(
                f"active model {model_id} uses unregistered factor libraries: {missing_libraries}"
            )
        for factor_id in factor_ids:
            if factor_id not in entries:
                raise ValueError(f"active model {model_id} references unknown canonical factor: {factor_id}")
            entry = entries[factor_id]
            if market not in entry["markets"]:
                raise ValueError(f"active factor {factor_id} does not support market={market}")
            entry["active_models"][market].append(model_id)
            entry["market_status"][market] = "model_active"


def _validate_evidence_path(root: Path, raw: str) -> None:
    _repository_path(root, raw)


def _apply_evidence(
    entries: dict[str, dict[str, Any]],
    *,
    root: Path,
    evidence_sources: list[str],
) -> list[FactorEvidenceRecord]:
    records: list[FactorEvidenceRecord] = []
    for source in evidence_sources:
        for record in load_factor_evidence(_repository_path(root, source)):
            entry = entries.get(record.factor_id)
            if entry is None:
                raise ValueError(f"factor evidence references unknown canonical factor: {record.factor_id}")
            if record.implementation_hash != entry["implementation_hash"]:
                raise ValueError(
                    "factor evidence implementation hash drifted: "
                    f"{record.factor_id} evidence={record.implementation_hash} "
                    f"canonical={entry['implementation_hash']}"
                )
            if record.market not in entry["markets"]:
                raise ValueError(
                    f"factor evidence market {record.market} unsupported by {record.factor_id}"
                )
            for evidence_path in record.evidence_paths:
                _validate_evidence_path(root, evidence_path)
            entry["evidence"][record.market].append(record.to_dict())
            current = entry["market_status"].get(record.market)
            if current != "model_active":
                if current is None or _STATUS_PRECEDENCE[record.status] > _STATUS_PRECEDENCE.get(current, -1):
                    entry["market_status"][record.market] = record.status
            records.append(record)
    return records


def build_factor_research_index(
    *,
    root: str | Path,
    registry_path: str | Path = "configs/factor_catalog.yaml",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    registry = load_factor_catalog_registry(registry_path, root=root_path)
    library_sources = [str(value) for value in registry["library_sources"]]
    model_sources = [str(value) for value in registry["active_model_sources"]]
    evidence_sources = [str(value) for value in registry["evidence_sources"]]
    entries, libraries = _library_projection(root_path, library_sources)
    _apply_active_models(
        entries,
        root=root_path,
        model_sources=model_sources,
        registered_libraries=set(library_sources),
    )
    evidence = _apply_evidence(entries, root=root_path, evidence_sources=evidence_sources)

    for entry in entries.values():
        for market in entry["markets"]:
            entry["market_status"].setdefault(market, entry["definition_status"])
        entry["active_models"] = {
            market: sorted(models) for market, models in entry["active_models"].items() if models
        }
        entry["evidence"] = {
            market: rows for market, rows in entry["evidence"].items() if rows
        }

    ordered = [entries[factor_id] for factor_id in sorted(entries)]
    status_counts: dict[str, int] = {}
    for entry in ordered:
        for status in entry["market_status"].values():
            status_counts[status] = status_counts.get(status, 0) + 1
    library_manifests = {
        source: {
            "source_sha256": library.source_sha256,
            "catalog_id": library.catalog.catalog_id,
            "catalog_version": library.catalog.catalog_version,
            "catalog_implementation_hash": library.catalog.implementation_hash(),
            "factor_count": len(library.catalog.definitions),
        }
        for source, library in libraries.items()
    }
    registry_source = Path(registry_path)
    if not registry_source.is_absolute():
        registry_source = root_path / registry_source
    registry_sha = hashlib.sha256(registry_source.read_bytes()).hexdigest()
    payload: dict[str, Any] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "catalog_id": str(registry["catalog_id"]),
        "registry_source": str(registry_source.relative_to(root_path)),
        "registry_sha256": registry_sha,
        "library_manifests": library_manifests,
        "active_model_sources": model_sources,
        "evidence_sources": evidence_sources,
        "factor_count": len(ordered),
        "evidence_record_count": len(evidence),
        "market_status_counts": dict(sorted(status_counts.items())),
        "factors": ordered,
        "research_only": True,
        "trade_ready": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload["index_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def query_factor_research_index(
    index: dict[str, Any],
    *,
    category: str | None = None,
    mechanism: str | None = None,
    market: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Filter the derived index by agent-facing discovery fields."""

    if market is not None and market not in {"us", "cn"}:
        raise ValueError("market filter must be us or cn")
    if status is not None and status not in EVIDENCE_STATUSES and status != "unvalidated_formula":
        # Definition-level statuses remain queryable even when they are not evidence statuses.
        known = {
            str(entry.get("definition_status"))
            for entry in index.get("factors", [])
            if isinstance(entry, dict)
        }
        if status not in known:
            raise ValueError(f"unknown factor status filter: {status}")
    result: list[dict[str, Any]] = []
    for raw in index.get("factors", []):
        if not isinstance(raw, dict):
            continue
        if category is not None and str(raw.get("category")) != category:
            continue
        if mechanism is not None and str(raw.get("mechanism")) != mechanism:
            continue
        if market is not None and market not in raw.get("markets", []):
            continue
        if status is not None:
            if market is not None:
                if (raw.get("market_status") or {}).get(market) != status:
                    continue
            elif status not in set((raw.get("market_status") or {}).values()):
                continue
        result.append(dict(raw))
    return result
