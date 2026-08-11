"""Evidence binding for governed BYD v1.3 signal publications.

The final V1.3 prospective observation is the sole model-decision input to the
formal signal layer. Prospective eligibility remains a forward-research label;
it is not reused as a close-data freshness gate after explicit formal promotion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from src.research.byd_v1_3_low_vol_recovery import MODEL_ID


class BYDSignalEvidenceError(ValueError):
    """Raised when a BYD signal cannot be bound to current governed evidence."""


LEGACY_PRELAUNCH_SEED_DATE = "2026-08-10"


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BYDSignalEvidenceError(f"{label} must be an object")
    return value


def observation_has_governed_model_identity(observation: Mapping[str, Any]) -> bool:
    """Validate the model identity, including the one immutable legacy seed.

    The 2026-08-10 low-vol seed was committed before ``candidate_model_id`` was
    added to newly generated observations.  It is append-only, so its identity
    must be proven from the exact schema, launch boundary and target key rather
    than by rewriting history.  Every other observation still requires the
    explicit identity field and fails closed when it is missing or incorrect.
    """

    if "candidate_model_id" in observation:
        return observation.get("candidate_model_id") == MODEL_ID
    targets = observation.get("targets")
    return bool(
        observation.get("schema_version") == "byd_v1_3_low_vol_prospective_v1"
        and observation.get("kind") == "v1_3_low_vol_recovery_observation"
        and observation.get("prelaunch_seed") is True
        and observation.get("signal_date") == LEGACY_PRELAUNCH_SEED_DATE
        and observation.get("launch_after") == LEGACY_PRELAUNCH_SEED_DATE
        and isinstance(targets, Mapping)
        and MODEL_ID in targets
    )


def close_evidence_is_current(observation: Mapping[str, Any]) -> bool:
    """Return whether the final governed V1.3 close-time decision is materialized."""

    if observation.get("schema_version") != "byd_v1_3_low_vol_prospective_v1":
        return False
    if not observation_has_governed_model_identity(observation):
        return False
    if not str(observation.get("signal_date") or ""):
        return False
    if not str(observation.get("data_version") or ""):
        return False
    if not isinstance(observation.get("common_open_eligible"), bool):
        return False
    source = observation.get("source")
    targets = observation.get("targets")
    factors = observation.get("factors")
    champion = observation.get("champion")
    if not all(isinstance(value, Mapping) for value in (source, targets, factors, champion)):
        return False
    required_factors = {"market_state", "vol_state", "mom_20", "mom_60", "drawdown_252"}
    if not required_factors.issubset(factors):
        return False
    if MODEL_ID not in targets:
        return False
    recovery_sha = str(source.get("recovery_event_observation_sha256") or "")
    return len(recovery_sha) == 64


def bind_final_signal_identity(alert: dict[str, Any]) -> dict[str, Any]:
    """Bind the signal fingerprint to decision, source and canonical factor identity."""

    decision_fingerprint = str(alert.get("fingerprint") or "").strip()
    if not decision_fingerprint:
        raise BYDSignalEvidenceError("signal decision fingerprint is missing")
    provenance = _mapping(alert.get("data_provenance"), label="signal.data_provenance")
    factor_evidence = _mapping(alert.get("factor_evidence"), label="signal.factor_evidence")
    catalog_hash = str(factor_evidence.get("catalog_implementation_hash") or "").strip()
    source_sha256 = str(factor_evidence.get("source_sha256") or "").strip()
    if len(catalog_hash) != 64 or len(source_sha256) != 64:
        raise BYDSignalEvidenceError("canonical factor identity is incomplete")

    identity = {
        "decision_fingerprint": decision_fingerprint,
        "source_manifests": dict(
            sorted((str(k), str(v)) for k, v in provenance.items() if k.endswith("_sha256"))
        ),
        "factor_catalog_implementation_hash": catalog_hash,
        "factor_source_sha256": source_sha256,
    }
    final_fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:20]

    alert["decision_fingerprint"] = decision_fingerprint
    alert["fingerprint"] = final_fingerprint
    alert["evidence_identity"] = identity
    markdown = alert.get("markdown")
    if isinstance(markdown, str):
        alert["markdown"] = markdown.replace(
            f"signal-fingerprint:{decision_fingerprint}",
            f"signal-fingerprint:{final_fingerprint}",
        )
    return alert
