"""Product-facing wrapper for the frozen low-turnover multifactor candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.research.factor_knowledge_registry import FactorCardInput, FactorKnowledgeRegistry
from src.research.low_turnover_multifactor import run_low_turnover_multifactor


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _verify_relationship_manifest(relationship_path: Path) -> tuple[str, str | None]:
    manifest_path = relationship_path.parent / "evidence_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("relationship map requires a sibling evidence_manifest.json")
    manifest = _load_json(manifest_path)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("relationship evidence manifest is missing outputs")
    if outputs.get(relationship_path.name) != _sha256_file(relationship_path):
        raise ValueError("relationship map hash differs from its evidence manifest")
    return _sha256_file(manifest_path), manifest.get("manifest_identity_sha256")


def _register_composite_card(
    registry_db: str | Path,
    contract: Mapping[str, Any],
) -> str:
    registry = FactorKnowledgeRegistry(registry_db)
    combination_id = str(contract["combination_id"])
    version = str(contract["combination_version"])
    card = FactorCardInput(
        stable_factor_key=combination_id,
        factor_version=version,
        name="US low-turnover four-family composite",
        canonical_definition=(
            "Equal-weight percentile composite of revenue-growth acceleration, "
            "gross-margin improvement, basket relative momentum, and basket drawdown resilience"
        ),
        information_family="composite",
        update_frequency="every_20_sessions",
        availability_lag_days=0,
        transformation="equal_weight_cross_family_composite_then_within_basket_rank",
        orientation="higher_is_better",
        neutralization="within_primary_basket",
        thesis=(
            "A slow fundamental signal confirmed by basket trend and downside resilience "
            "may improve durability while keeping turnover bounded."
        ),
        code_identity="src/research/low_turnover_multifactor_pipeline.py",
        status="data_blocked",
        spec_path="configs/factors/us_low_turnover_multifactor_v1.yaml",
        source_kind="native_v2",
        source_ref=f"{combination_id}:{version}",
    )
    return registry.register_card(card)


def _make_decision_desk_compatible(scores_path: Path) -> int:
    payload = _load_json(scores_path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("multifactor score artifact must contain rows")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("multifactor score rows must be objects")
        row["score"] = row.get("composite_score")
        row["percentile"] = row.get("selection_percentile")
        row["eligible"] = bool(row.get("component_complete", False))
        row.setdefault("reason_codes", [])
        if not row["eligible"]:
            row["reason_codes"].append("MULTIFACTOR_COMPONENT_INCOMPLETE")
        if row.get("selected"):
            row["reason_codes"].append("MULTIFACTOR_LOW_TURNOVER_SELECTED")
    _write_json(scores_path, payload)
    return len(rows)


def run_low_turnover_multifactor_pipeline(
    *,
    contract_path: str | Path,
    fundamental_scores_path: str | Path,
    basket_scores_path: str | Path,
    relationship_map_path: str | Path,
    prices_csv: str | Path,
    registry_db: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run the core composer, then bind its composite card and product output."""

    resolved_contract = Path(contract_path).resolve()
    contract = yaml.safe_load(resolved_contract.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or not contract.get("combination_version"):
        raise ValueError("multifactor contract requires combination_version")
    relationship_path = Path(relationship_map_path).resolve()
    relationship_manifest_hash, relationship_manifest_identity = (
        _verify_relationship_manifest(relationship_path)
    )
    run_low_turnover_multifactor(
        contract_path=resolved_contract,
        fundamental_scores_path=fundamental_scores_path,
        basket_scores_path=basket_scores_path,
        relationship_map_path=relationship_path,
        prices_csv=prices_csv,
        registry_db=registry_db,
        output_dir=output_dir,
    )
    output = Path(output_dir).resolve()
    score_rows = _make_decision_desk_compatible(output / "multifactor_scores.json")
    composite_card_id = _register_composite_card(registry_db, contract)

    decision_path = output / "decision.json"
    decision_payload = _load_json(decision_path)
    decision_payload["composite_card_id"] = composite_card_id
    decision_payload["decision_desk_factor_score_artifact"] = "multifactor_scores.json"
    decision_payload["score_row_count"] = score_rows
    decision_payload["relationship_manifest_sha256"] = relationship_manifest_hash
    decision_payload["relationship_manifest_identity_sha256"] = (
        relationship_manifest_identity
    )
    _write_json(decision_path, decision_payload)

    manifest_path = output / "evidence_manifest.json"
    manifest = _load_json(manifest_path)
    manifest.setdefault("inputs", {})["relationship_evidence_manifest"] = (
        relationship_manifest_hash
    )
    manifest["inputs"]["relationship_evidence_manifest_identity"] = (
        relationship_manifest_identity
    )
    manifest["outputs"] = {
        name: _sha256_file(output / name)
        for name in (
            "multifactor_scores.json",
            "portfolio_history.json",
            "decision.json",
        )
    }
    manifest.pop("manifest_identity_sha256", None)
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(manifest_path, manifest)
    return decision_payload
