"""Deterministic importer for the first historical factor-card batch."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.research.factor_knowledge_registry import (
    FactorCardInput,
    FactorKnowledgeRegistry,
)

FAILURE_CLASS_BY_STATUS = {
    "legacy_unverified": "legacy_evidence_incomplete",
    "data_blocked": "point_in_time_data_missing",
    "rejected": "observed_hypothesis_failed",
    "market_specific_clue": "scope_limited_evidence",
    "candidate": "standalone_evidence_incomplete",
    "redundant": "no_independent_combination_value",
    "independent_validation_required": "reserved_evidence_required",
    "retired": "family_level_stop",
}

FAILED_GATE_BY_STATUS = {
    "legacy_unverified": "CURRENT_CONTRACT_EVIDENCE_MISSING",
    "data_blocked": "POINT_IN_TIME_DATA_MISSING",
    "rejected": "DECLARED_EVIDENCE_GATE_FAILED",
    "market_specific_clue": "BROAD_SUPPORT_NOT_ESTABLISHED",
    "candidate": "INDEPENDENT_VALIDATION_INCOMPLETE",
    "redundant": "MARGINAL_CONTRIBUTION_NOT_ESTABLISHED",
    "independent_validation_required": "RESERVED_EVIDENCE_UNOPENED",
    "retired": "FAMILY_STOP_APPLIED",
}


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _entry_hash(entry: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(entry).encode("utf-8")).hexdigest()


def load_history_cards(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("historical factor card inventory must be a YAML mapping")
    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError("historical factor card inventory must contain cards")
    keys = [str(card.get("stable_factor_key", "")) for card in cards]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("historical factor keys must be non-empty and unique")
    return payload


def backfill_history_batch(
    registry: FactorKnowledgeRegistry,
    inventory_path: str | Path,
) -> dict[str, Any]:
    payload = load_history_cards(inventory_path)
    defaults = dict(payload.get("defaults", {}))
    status_counts: Counter[str] = Counter()
    imported: list[dict[str, str]] = []

    for raw in payload["cards"]:
        entry = {**defaults, **dict(raw)}
        key = str(entry["stable_factor_key"])
        version = str(entry["factor_version"])
        status = str(entry["status"])
        source_kind = str(entry.get("source_kind", "historical_backfill_batch_1"))
        source_report_path = str(entry.get("source_report_path", ""))
        card_source_ref = f"{source_kind}:card:{key}:{version}"
        evidence_source_ref = f"{source_kind}:evidence:{key}:{version}"

        card_id = registry.register_card(
            FactorCardInput(
                stable_factor_key=key,
                factor_version=version,
                name=str(entry["name"]),
                canonical_definition=str(entry["canonical_definition"]),
                information_family=str(entry["information_family"]),
                update_frequency=str(entry["update_frequency"]),
                availability_lag_days=int(entry["availability_lag_days"]),
                transformation=str(entry["transformation"]),
                orientation=str(entry.get("orientation", "higher_is_better")),
                neutralization=str(entry.get("neutralization", "none")),
                thesis=str(entry["thesis"]),
                code_identity=str(entry["code_identity"]),
                status=status,
                spec_path=str(entry.get("spec_path", "")),
                source_report_path=source_report_path,
                source_kind=source_kind,
                source_ref=card_source_ref,
            )
        )

        manifest_hash = _entry_hash(entry)
        evidence_id = registry.record_evidence(
            card_id,
            {
                "market": str(entry.get("market", "historical_mixed_or_unknown")),
                "universe_version": str(
                    entry.get("universe_version", "historical_mixed_or_unknown")
                ),
                "benchmark": str(entry.get("benchmark", "historical_mixed_or_unknown")),
                "horizon_sessions": int(entry.get("horizon_sessions", 0)),
                "provider_identity": str(entry.get("provider_identity", "historical_unknown")),
                "data_validity_level": str(
                    entry.get("data_validity_level", "historical_incomplete")
                ),
                "development_start": str(entry.get("development_start", "")),
                "development_end": str(entry.get("development_end", "")),
                "falsification_start": str(entry.get("falsification_start", "")),
                "falsification_end": str(entry.get("falsification_end", "")),
                "reserved_start": str(entry.get("reserved_start", "")),
                "reserved_end": str(entry.get("reserved_end", "")),
                "cost_bps": entry.get("cost_bps"),
                "execution_contract": str(entry.get("execution_contract", "historical_unknown")),
                "evidence_manifest_hash": manifest_hash,
                "authoritative": False,
                "decision_status": status,
                "failure_class": FAILURE_CLASS_BY_STATUS[status],
                "lessons_learned": str(entry["lesson"]),
                "source_kind": source_kind,
                "source_ref": evidence_source_ref,
            },
        )
        evaluation_id = registry.record_evaluation(
            evidence_id,
            {
                "failed_gates": [FAILED_GATE_BY_STATUS[status]],
                "historical_classification": status,
                "historical_lesson": str(entry["lesson"]),
                "standalone_support_implied": False,
                "source_report_path": source_report_path,
            },
        )
        status_counts[status] += 1
        imported.append(
            {
                "stable_factor_key": key,
                "card_id": card_id,
                "evidence_id": evidence_id,
                "evaluation_id": evaluation_id,
                "status": status,
            }
        )

    completeness = registry.evidence_completeness_report()
    return {
        "schema_version": "1.0",
        "batch_status": str(payload.get("status", "historical_backfill")),
        "inventory_sha256": hashlib.sha256(Path(inventory_path).read_bytes()).hexdigest(),
        "card_count": len(imported),
        "status_counts": dict(sorted(status_counts.items())),
        "authoritative_evidence_created": 0,
        "reserved_performance_opened": False,
        "trade_ready": False,
        "imported": imported,
        "completeness": completeness,
    }
