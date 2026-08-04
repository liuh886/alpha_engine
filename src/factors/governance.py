"""Machine-readable factor catalog, materialization and evidence governance."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml  # type: ignore[import-untyped]

from src.factors.sets.qlib_alpha158 import load_alpha158_definitions


class FactorGovernanceError(ValueError):
    """Raised when factor identities or readiness evidence are inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FactorGovernanceError(f"YAML must be a mapping: {path}")
    return payload


def build_factor_governance_manifest(
    *,
    root: str | Path,
    market: str,
    pool_id: str,
    evidence_cutoff: str,
    factor_panel_manifest: Mapping[str, Any],
    model_data_manifest: Mapping[str, Any] | None,
    output_path: str | Path,
    historical_cards_path: str | Path = (
        "configs/factor_knowledge/historical_factor_cards_v1.yaml"
    ),
) -> dict[str, Any]:
    """Separate formula availability, panel readiness and effectiveness claims."""

    repo = Path(root).resolve()
    cards_path = Path(historical_cards_path)
    if not cards_path.is_absolute():
        cards_path = repo / cards_path
    cards_payload = _load_yaml(cards_path)
    cards = cards_payload.get("cards")
    if not isinstance(cards, list):
        raise FactorGovernanceError("historical factor cards must be a list")
    keys = [str(row.get("stable_factor_key", "")) for row in cards]
    if not all(keys) or len(keys) != len(set(keys)):
        raise FactorGovernanceError("historical factor keys must be non-empty and unique")
    historical_statuses = Counter(str(row.get("status", "")) for row in cards)

    definitions = load_alpha158_definitions()
    factor_ids = [definition.factor_id for definition in definitions]
    if len(definitions) != 158 or len(factor_ids) != len(set(factor_ids)):
        raise FactorGovernanceError("Alpha158 formula identity is not exact")
    formula_statuses = Counter(definition.status for definition in definitions)
    if formula_statuses != {"unvalidated_formula": 158}:
        raise FactorGovernanceError("Alpha158 formulas must begin unvalidated")

    panel_status = str(factor_panel_manifest.get("status", "blocked"))
    profile_id = f"{market}_selected_alpha158_v1"
    profile_status = "blocked"
    profile_blockers: list[str] = ["model_data_manifest_missing"]
    if model_data_manifest is not None:
        profiles = model_data_manifest.get("training_profiles", [])
        target = next(
            (
                row
                for row in profiles
                if isinstance(row, dict) and row.get("profile_id") == profile_id
            ),
            None,
        )
        if target is None:
            profile_blockers = ["training_profile_missing"]
        else:
            profile_status = str(target.get("status", "blocked"))
            profile_blockers = [str(value) for value in target.get("blockers", [])]

    gate_open = panel_status == "ready" and profile_status == "ready"
    supported_statuses = {"supported", "validated", "promoted"}
    supported_historical = sum(
        count
        for status, count in historical_statuses.items()
        if status in supported_statuses
    )
    manifest = {
        "schema_version": "1.0",
        "manifest_id": f"factor_governance.{market}.{pool_id}.{evidence_cutoff}",
        "market": market,
        "pool_id": pool_id,
        "evidence_cutoff": evidence_cutoff,
        "formula_catalog": {
            "namespace": "qlib_alpha158",
            "status": "ready_unvalidated",
            "factor_count": len(definitions),
            "status_counts": dict(sorted(formula_statuses.items())),
            "implementation_hashes": {
                definition.factor_id: definition.implementation_hash
                for definition in definitions
            },
        },
        "materialized_panel": {
            "component_id": factor_panel_manifest.get("component_id"),
            "status": panel_status,
            "expected_symbol_count": factor_panel_manifest.get(
                "expected_symbol_count", 0
            ),
            "ready_symbol_count": factor_panel_manifest.get("ready_symbol_count", 0),
            "coverage_ratio": factor_panel_manifest.get("coverage_ratio", 0.0),
            "catalog_sha256": factor_panel_manifest.get("catalog_sha256"),
            "invalid_symbols": factor_panel_manifest.get("invalid_symbols", []),
            "not_yet_applicable_symbols": factor_panel_manifest.get(
                "not_yet_applicable_symbols", []
            ),
            "blocker": factor_panel_manifest.get("blocker"),
        },
        "historical_research_memory": {
            "path": str(cards_path),
            "sha256": _sha256(cards_path),
            "factor_count": len(cards),
            "status_counts": dict(sorted(historical_statuses.items())),
            "supported_factor_count": supported_historical,
        },
        "training_gate": {
            "profile_id": profile_id,
            "status": "open_for_frozen_experiment" if gate_open else "blocked",
            "profile_status": profile_status,
            "blockers": profile_blockers,
        },
        "effectiveness_claim": {
            "status": "not_established",
            "alpha158_validated_factor_count": 0,
            "historical_supported_factor_count": supported_historical,
            "formula_presence_implies_alpha": False,
            "panel_readiness_implies_alpha": False,
        },
        "research_only": True,
        "trade_ready": False,
    }
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
