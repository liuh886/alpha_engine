"""Thin consumer views for one canonical PromotionDecision artifact.

These helpers never recompute promotion gates.  They load or receive the durable
``promotion_decision.json`` payload and render compatibility surfaces for the
legacy model-decision report, frontend/API payloads, registry persistence, and
agent/notebook summaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.research.promotion_decision import PROMOTION_DECISION_FILENAME
from src.research.research_artifacts import build_frontend_payload

_ALLOWED_STATUSES = frozenset(
    {
        "missing_evidence",
        "rejected",
        "research_candidate",
        "stronger_research_candidate",
        "trade_guidance_candidate",
    }
)


def validate_promotion_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a serialized PromotionDecision without re-running its gates."""
    if payload.get("schema_version") != "1.0":
        raise ValueError("promotion decision schema_version must be '1.0'")
    status = str(payload.get("status", ""))
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"unsupported promotion status: {status!r}")
    trade_ready = bool(payload.get("trade_ready", False))
    expected = status == "trade_guidance_candidate"
    if trade_ready != expected:
        raise ValueError(
            "promotion trade_ready must be true only for trade_guidance_candidate"
        )
    subject_id = str(payload.get("subject_id", "")).strip()
    if not subject_id:
        raise ValueError("promotion decision subject_id must be non-empty")
    evidence_refs = payload.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        raise ValueError("promotion decision evidence_refs must be a list")
    for index, item in enumerate(evidence_refs):
        if not isinstance(item, dict):
            raise ValueError(f"evidence_refs[{index}] must be an object")
        if not str(item.get("name", "")).strip():
            raise ValueError(f"evidence_refs[{index}].name must be non-empty")
        sha = str(item.get("sha256", ""))
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise ValueError(f"evidence_refs[{index}].sha256 must be lowercase SHA-256")
    return dict(payload)


def load_promotion_payload(path_or_run_dir: str | Path) -> dict[str, Any]:
    """Load and validate a promotion artifact from a file or research-run dir."""
    path = Path(path_or_run_dir)
    if path.is_dir():
        path = path / PROMOTION_DECISION_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("promotion decision artifact must contain a JSON object")
    validated = validate_promotion_payload(payload)
    validated["artifact_path"] = str(path.resolve())
    return validated


def build_model_decision_pack_view(
    promotion: dict[str, Any],
) -> dict[str, Any]:
    """Render the legacy ModelDecisionPack schema from PromotionDecision only."""
    decision = validate_promotion_payload(promotion)
    candidate = decision.get("candidate")
    if candidate is not None and not isinstance(candidate, dict):
        raise ValueError("promotion candidate must be an object or null")
    status = str(decision["status"])
    failed = list(decision.get("failed_gates", []) or [])
    return {
        "schema_version": "1.1",
        "source": "promotion_decision",
        "promotion_decision": decision,
        "current_best_candidate": dict(candidate) if isinstance(candidate, dict) else None,
        "decision": {
            "status": status,
            "trade_ready": bool(decision["trade_ready"]),
            "failed_trade_gates": failed,
            "thresholds": dict(decision.get("thresholds", {}) or {}),
        },
        "stable_candidate_count": 1 if candidate else 0,
        "stable_candidates_top5": [dict(candidate)] if isinstance(candidate, dict) else [],
        "non_trade_ready_warning": str(
            decision.get(
                "research_only_warning",
                "Promotion status is research evidence, not trade authorization.",
            )
        ),
        "recommended_next_step": _recommended_next_step(status, failed),
        "evidence_refs": list(decision.get("evidence_refs", []) or []),
        "contract_sha256": str(decision.get("contract_sha256", "")),
    }


def build_frontend_promotion_view(
    promotion: dict[str, Any],
    *,
    market: str,
    benchmark: str,
    run_status: str,
    metrics: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
    artifact_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the existing research frontend schema from the canonical decision."""
    decision = validate_promotion_payload(promotion)
    return build_frontend_payload(
        str(decision["subject_id"]),
        market=market,
        benchmark=benchmark,
        run_status=run_status,
        decision={
            "status": str(decision["status"]),
            "trade_ready": bool(decision["trade_ready"]),
        },
        metrics=metrics,
        readiness=readiness,
        artifact_paths=artifact_paths,
        metadata={
            "decision_source": "promotion_decision",
            "contract_sha256": str(decision.get("contract_sha256", "")),
            "evidence_refs": list(decision.get("evidence_refs", []) or []),
        },
    )


def build_registry_decision_record(promotion: dict[str, Any]) -> dict[str, Any]:
    """Return persistence fields; registry records but never interprets them."""
    decision = validate_promotion_payload(promotion)
    return {
        "promotion_status": str(decision["status"]),
        "trade_ready": bool(decision["trade_ready"]),
        "promotion_contract_sha256": str(decision.get("contract_sha256", "")),
        "promotion_evidence_refs": list(decision.get("evidence_refs", []) or []),
        "promotion_artifact_path": str(decision.get("artifact_path", "")),
    }


def build_agent_decision_summary(promotion: dict[str, Any]) -> dict[str, Any]:
    """Return a compact read-only summary for agents and notebooks."""
    decision = validate_promotion_payload(promotion)
    candidate = decision.get("candidate") or {}
    return {
        "subject_id": str(decision["subject_id"]),
        "status": str(decision["status"]),
        "trade_ready": bool(decision["trade_ready"]),
        "candidate": candidate.get("candidate") if isinstance(candidate, dict) else None,
        "failed_gates": list(decision.get("failed_gates", []) or []),
        "missing_evidence": list(decision.get("missing_evidence", []) or []),
        "rationale": str(decision.get("rationale", "")),
        "contract_sha256": str(decision.get("contract_sha256", "")),
        "evidence_count": len(decision.get("evidence_refs", []) or []),
        "may_recompute_decision": False,
    }


def _recommended_next_step(status: str, failed: list[Any]) -> str:
    if status == "missing_evidence":
        return "Complete the required evidence bundle before evaluating promotion."
    if status == "rejected":
        return "Resolve failed evidence or stability gates before further promotion."
    if status == "trade_guidance_candidate":
        return (
            "Run independent robustness review before any operational use; "
            "this status is not live-trading authorization."
        )
    if status == "stronger_research_candidate":
        return "Address the remaining promotion gates and expand robustness evidence."
    suffix = f" Failed gates: {', '.join(str(item) for item in failed)}." if failed else ""
    return "Keep the candidate research-only and improve evidence quality." + suffix
