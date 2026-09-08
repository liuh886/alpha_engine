"""Fail-closed formal packaging for a prospectively supported CN_27 V1.3."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_v1_3_prospective import (
    load_prospective_contract,
    prospective_gate_failures,
)


@dataclass(frozen=True)
class PassedProspectiveEvidence:
    formalization: dict[str, Any]
    formalization_path: Path
    validation: Any
    manifest: dict[str, Any]
    manifest_path: Path
    decision: dict[str, Any]
    metrics: dict[str, Any]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def load_passed_prospective_evidence(
    formalization_contract_path: str | Path,
    evidence_manifest_path: str | Path,
) -> PassedProspectiveEvidence:
    spec_path = Path(formalization_contract_path).resolve()
    root = spec_path.parents[2]
    spec = _load_yaml(spec_path)
    if spec.get("status") != "frozen_before_prospective_result":
        raise ValueError("V1.3 formalization contract must be frozen before the result")
    boundary = spec.get("formal_boundary", {})
    if boundary.get("research_only") is not True or boundary.get("trade_ready") is not False:
        raise ValueError("V1.3 formalization must remain research-only")
    if boundary.get("automatic_promotion_allowed") is not False:
        raise ValueError("V1.3 formalization cannot automatically promote")

    lineage = spec["lineage"]
    formalization_implementation = (root / str(lineage["implementation"])).resolve()
    if sha256_file(formalization_implementation) != str(lineage["implementation_sha256"]):
        raise ValueError("formalization implementation hash mismatch")
    validation_path = (root / str(lineage["prospective_validation_contract"])).resolve()
    if sha256_file(validation_path) != str(
        lineage["prospective_validation_contract_sha256"]
    ):
        raise ValueError("prospective validation contract hash mismatch")
    implementation_path = (root / str(lineage["prospective_implementation"])).resolve()
    if sha256_file(implementation_path) != str(
        lineage["prospective_implementation_sha256"]
    ):
        raise ValueError("prospective implementation hash mismatch")
    challenger_path = (root / str(lineage["challenger_contract"])).resolve()
    if sha256_file(challenger_path) != str(lineage["challenger_contract_sha256"]):
        raise ValueError("prospective challenger hash mismatch")
    validation = load_prospective_contract(validation_path)

    manifest_path = Path(evidence_manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = dict(manifest)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(body) != identity:
        raise ValueError("prospective evidence manifest identity mismatch")
    for filename, expected in manifest.get("outputs", {}).items():
        if sha256_file(manifest_path.parent / filename) != expected:
            raise ValueError(f"prospective evidence output hash mismatch: {filename}")
    if manifest.get("decision") != spec["required_prospective_decision"]:
        raise ValueError("prospective evidence did not pass the frozen gate")
    if manifest.get("formal_v1_3_packaging_authorized") is not True:
        raise ValueError("prospective evidence does not authorize formal packaging")
    if manifest.get("trade_ready") is not False:
        raise ValueError("prospective evidence cannot be trade-ready")
    identity_block = manifest.get("identity", {})
    if identity_block.get("validation_contract_sha256") != sha256_file(validation_path):
        raise ValueError("prospective evidence validation identity mismatch")
    if identity_block.get("implementation_sha256") != sha256_file(implementation_path):
        raise ValueError("prospective evidence implementation identity mismatch")

    decision = json.loads((manifest_path.parent / "decision.json").read_text(encoding="utf-8"))
    if decision.get("decision") != spec["required_prospective_decision"]:
        raise ValueError("prospective decision output did not pass")
    if decision.get("failed_gates") != []:
        raise ValueError("prospective decision retains failed gates")
    readiness = decision.get("readiness", {})
    if readiness.get("ready") is not True:
        raise ValueError("prospective observation is not ready")
    if int(readiness.get("session_count", 0)) < int(
        validation.spec["observation_contract"]["minimum_sessions"]
    ):
        raise ValueError("prospective observation has insufficient sessions")
    start = pd.Timestamp(readiness["observation_start"])
    end = pd.Timestamp(readiness["observation_end"])
    months = int(validation.spec["observation_contract"]["minimum_calendar_months"])
    if end < start + pd.DateOffset(months=months):
        raise ValueError("prospective observation has insufficient calendar duration")
    observation = manifest.get("observation", {})
    if (
        observation.get("start") != readiness["observation_start"]
        or observation.get("end") != readiness["observation_end"]
        or int(observation.get("sessions", 0)) != int(readiness["session_count"])
    ):
        raise ValueError("prospective manifest and decision observation windows differ")
    chains = manifest.get("source_table_chains")
    expected_files = set(validation.spec["required_input_files"])
    if not isinstance(chains, dict) or set(chains) != expected_files:
        raise ValueError("prospective evidence lacks complete source table chains")
    instrument_count = len(validation.candidate_symbols) + 2
    expected_tradability_rows = int(readiness["session_count"]) * instrument_count
    if int(chains["tradability.csv"]["row_count"]) != expected_tradability_rows:
        raise ValueError("prospective tradability chain does not cover the declared window")

    metrics_document = json.loads(
        (manifest_path.parent / "prospective_metrics.json").read_text(encoding="utf-8")
    )
    metrics = metrics_document.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("prospective metrics are missing")
    failures = prospective_gate_failures(metrics, validation.spec["prospective_gate"])
    if failures:
        raise ValueError(f"prospective metrics fail frozen gates: {failures}")
    return PassedProspectiveEvidence(
        formalization=spec,
        formalization_path=spec_path,
        validation=validation,
        manifest=manifest,
        manifest_path=manifest_path,
        decision=decision,
        metrics=metrics,
    )


def build_formal_v1_3_spec(evidence: PassedProspectiveEvidence) -> dict[str, Any]:
    validation = evidence.validation
    challenger = validation.challenger
    root = evidence.formalization_path.parents[2]
    incumbent_path = (root / challenger["lineage"]["incumbent_model_contract"]).resolve()
    incumbent = _load_yaml(incumbent_path)
    frozen = challenger["frozen_challenger"]
    portfolio = copy.deepcopy(incumbent["portfolio"])
    portfolio.update(
        {
            "weighting": "shrinkage_minimum_variance_projected",
            "covariance_lookback": int(frozen["covariance_lookback"]),
            "covariance_shrinkage": float(frozen["covariance_shrinkage"]),
            "projection_objective": str(frozen["projection"]),
            "maximum_single_equity_sleeve_share": float(
                frozen["maximum_single_equity_sleeve_share"]
            ),
            "maximum_sector_equity_sleeve_share": float(
                frozen["maximum_sector_equity_sleeve_share"]
            ),
            "minimum_effective_names": float(frozen["minimum_effective_names"]),
        }
    )
    observation = evidence.manifest["observation"]
    boundary = evidence.formalization["formal_boundary"]
    return {
        "schema_version": "1.0",
        "model_version_id": "cn_27_v1_3_projected_k2_prospectively_validated",
        "display_name": "CN_27 V1.3",
        "created_at": observation["end"],
        "status": boundary["status"],
        "market": "cn",
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion_allowed": False,
        "promotion_authorized": False,
        "selected_pool_readiness_claim_allowed": False,
        "lineage": {
            "predecessor": incumbent["model_version_id"],
            "challenger_contract": evidence.formalization["lineage"][
                "challenger_contract"
            ],
            "challenger_contract_sha256": evidence.formalization["lineage"][
                "challenger_contract_sha256"
            ],
            "prospective_validation_contract": evidence.formalization["lineage"][
                "prospective_validation_contract"
            ],
            "prospective_validation_contract_sha256": evidence.formalization["lineage"][
                "prospective_validation_contract_sha256"
            ],
            "prospective_evidence_manifest": str(evidence.manifest_path),
            "prospective_evidence_manifest_file_sha256": sha256_file(
                evidence.manifest_path
            ),
            "prospective_evidence_manifest_identity_sha256": evidence.manifest[
                "manifest_identity_sha256"
            ],
            "historical_manifest_identity_sha256": evidence.manifest["identity"][
                "historical_manifest_identity_sha256"
            ],
        },
        "identity": {
            **copy.deepcopy(incumbent["identity"]),
            "prospective_source_manifest_sha256": evidence.manifest["identity"][
                "source_manifest_sha256"
            ],
        },
        "factor_model": copy.deepcopy(incumbent["factor_model"]),
        "portfolio": portfolio,
        "execution": copy.deepcopy(incumbent["execution"]),
        "costs": copy.deepcopy(incumbent["costs"]),
        "prospective_evaluation": {
            "window": observation,
            "all_frozen_gates_passed": True,
            "metrics": copy.deepcopy(evidence.metrics),
        },
        "formal_boundary": copy.deepcopy(boundary),
        "prohibited": [
            "modify V1.1 or V1.2 contracts or evidence",
            "change pool, factors, parameters, costs or execution after validation",
            "automatic model promotion",
            "claim selected-pool readiness",
            "claim trade readiness",
        ],
    }


def formalize_v1_3(
    formalization_contract_path: str | Path,
    evidence_manifest_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    evidence = load_passed_prospective_evidence(
        formalization_contract_path,
        evidence_manifest_path,
    )
    spec = build_formal_v1_3_spec(evidence)
    root = evidence.formalization_path.parents[2]
    destination = (
        root / evidence.formalization["formal_output"]
        if output_path is None
        else Path(output_path).resolve()
    )
    if destination.exists():
        if _load_yaml(destination) != spec:
            raise ValueError("a different formal CN_27 V1.3 contract already exists")
        return spec
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return spec
