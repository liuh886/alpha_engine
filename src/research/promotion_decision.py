"""Evidence-backed promotion decision for fixed-10D research runs.

This module is intentionally Qlib-free.  It reads durable run artifacts only
after execution has completed and produces the single promotion status that
notebooks, CLI, API, dashboard, registry, and agents should eventually consume.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.research.ten_day_model_gates import GATE_THRESHOLDS

PROMOTION_DECISION_FILENAME = "promotion_decision.json"
REQUIRED_EVIDENCE_FILES: dict[str, str] = {
    "execution_identity": "execution_identity.json",
    "data_readiness": "data_readiness.json",
    "walk_forward_stability": "walk_forward_stability.json",
}


class PromotionStatus(str, Enum):
    """Canonical lifecycle status derived from research evidence."""

    MISSING_EVIDENCE = "missing_evidence"
    REJECTED = "rejected"
    RESEARCH_CANDIDATE = "research_candidate"
    STRONGER_RESEARCH_CANDIDATE = "stronger_research_candidate"
    TRADE_GUIDANCE_CANDIDATE = "trade_guidance_candidate"


@dataclass(frozen=True)
class PromotionThresholds:
    """Thresholds owned by the promotion gate, not by adapters or frontend."""

    min_mean_icir: float = GATE_THRESHOLDS["min_icir"]
    min_mean_rank_ic: float = GATE_THRESHOLDS["min_rank_ic"]
    min_mean_spread: float = GATE_THRESHOLDS["min_spread"]
    max_drawdown_floor: float = GATE_THRESHOLDS["max_drawdown_floor"]
    min_ready_ratio: float = 0.75
    min_positive_icir_ratio: float = 0.60
    min_positive_spread_ratio: float = 0.60
    stronger_research_icir: float = 0.20

    def to_dict(self) -> dict[str, float]:
        return {
            "min_mean_icir": self.min_mean_icir,
            "min_mean_rank_ic": self.min_mean_rank_ic,
            "min_mean_spread": self.min_mean_spread,
            "max_drawdown_floor": self.max_drawdown_floor,
            "min_ready_ratio": self.min_ready_ratio,
            "min_positive_icir_ratio": self.min_positive_icir_ratio,
            "min_positive_spread_ratio": self.min_positive_spread_ratio,
            "stronger_research_icir": self.stronger_research_icir,
        }


@dataclass(frozen=True)
class EvidenceReference:
    """Immutable reference to one artifact used by a promotion decision."""

    name: str
    path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class PromotionDecision:
    """One fail-closed promotion result with durable evidence references."""

    subject_id: str
    status: PromotionStatus
    trade_ready: bool
    candidate: dict[str, Any] | None = None
    failed_gates: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceReference, ...] = ()
    contract_sha256: str = ""
    thresholds: PromotionThresholds = field(default_factory=PromotionThresholds)
    rationale: str = ""

    def __post_init__(self) -> None:
        should_be_ready = self.status is PromotionStatus.TRADE_GUIDANCE_CANDIDATE
        if self.trade_ready != should_be_ready:
            raise ValueError(
                "trade_ready must be true only for trade_guidance_candidate"
            )
        if self.missing_evidence and self.status is not PromotionStatus.MISSING_EVIDENCE:
            raise ValueError("missing evidence requires status='missing_evidence'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "subject_id": self.subject_id,
            "status": self.status.value,
            "trade_ready": self.trade_ready,
            "candidate": dict(self.candidate) if self.candidate is not None else None,
            "failed_gates": list(self.failed_gates),
            "missing_evidence": list(self.missing_evidence),
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "contract_sha256": self.contract_sha256,
            "thresholds": self.thresholds.to_dict(),
            "rationale": self.rationale,
            "research_only_warning": (
                "Promotion status is research evidence, not authorization for live "
                "or automated trading."
            ),
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Evidence artifact must contain a JSON object: {path}")
    return payload


def _evidence_refs(
    run_dir: Path,
    evidence_paths: dict[str, Path],
) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(
            name=name,
            path=str(path.relative_to(run_dir) if path.is_relative_to(run_dir) else path),
            sha256=_sha256(path),
        )
        for name, path in sorted(evidence_paths.items())
    )


def _candidate_rows(stability: dict[str, Any]) -> list[dict[str, Any]]:
    raw = stability.get("candidates", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError("walk_forward_stability.candidates must be a list of objects")
    return [dict(item) for item in raw]


def _select_best_stable_candidate(
    stability: dict[str, Any],
) -> dict[str, Any] | None:
    rows = [
        row
        for row in _candidate_rows(stability)
        if bool(row.get("stable_research_candidate"))
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            float(row.get("mean_icir", 0.0)),
            float(row.get("ready_ratio", 0.0)),
            float(row.get("positive_icir_ratio", 0.0)),
            float(row.get("positive_spread_ratio", 0.0)),
            float(row.get("worst_drawdown", 0.0)),
        ),
    )


def _metric_failures(
    candidate: dict[str, Any],
    thresholds: PromotionThresholds,
) -> tuple[str, ...]:
    failed: list[str] = []
    if float(candidate.get("mean_icir", 0.0)) < thresholds.min_mean_icir:
        failed.append("mean_icir")
    if float(candidate.get("mean_rank_ic", 0.0)) < thresholds.min_mean_rank_ic:
        failed.append("mean_rank_ic")
    if float(candidate.get("mean_spread", 0.0)) <= thresholds.min_mean_spread:
        failed.append("mean_spread")
    if float(candidate.get("worst_drawdown", 0.0)) < thresholds.max_drawdown_floor:
        failed.append("worst_drawdown")
    if float(candidate.get("ready_ratio", 0.0)) < thresholds.min_ready_ratio:
        failed.append("ready_ratio")
    if (
        float(candidate.get("positive_icir_ratio", 0.0))
        < thresholds.min_positive_icir_ratio
    ):
        failed.append("positive_icir_ratio")
    if (
        float(candidate.get("positive_spread_ratio", 0.0))
        < thresholds.min_positive_spread_ratio
    ):
        failed.append("positive_spread_ratio")
    return tuple(failed)


def build_promotion_decision(
    *,
    subject_id: str,
    execution_identity: dict[str, Any],
    data_readiness: dict[str, Any],
    walk_forward_stability: dict[str, Any],
    evidence_refs: tuple[EvidenceReference, ...] = (),
    thresholds: PromotionThresholds | None = None,
) -> PromotionDecision:
    """Build one canonical decision from already-loaded evidence payloads."""
    limits = thresholds or PromotionThresholds()
    contract_sha = str(execution_identity.get("declared_contract_sha256", ""))

    if execution_identity.get("matched") is not True:
        return PromotionDecision(
            subject_id=subject_id,
            status=PromotionStatus.REJECTED,
            trade_ready=False,
            failed_gates=("execution_identity",),
            evidence_refs=evidence_refs,
            contract_sha256=contract_sha,
            thresholds=limits,
            rationale="Declared and effective execution contracts did not match.",
        )

    if data_readiness.get("sufficient") is not True or bool(
        data_readiness.get("skipped")
    ):
        return PromotionDecision(
            subject_id=subject_id,
            status=PromotionStatus.REJECTED,
            trade_ready=False,
            failed_gates=("data_readiness",),
            evidence_refs=evidence_refs,
            contract_sha256=contract_sha,
            thresholds=limits,
            rationale=str(
                data_readiness.get("skip_reason")
                or "Data readiness was insufficient."
            ),
        )

    min_windows = int(walk_forward_stability.get("min_windows", 0))
    n_reports = int(walk_forward_stability.get("n_reports", 0))
    if min_windows < 3 or n_reports < min_windows:
        return PromotionDecision(
            subject_id=subject_id,
            status=PromotionStatus.REJECTED,
            trade_ready=False,
            failed_gates=("walk_forward_coverage",),
            evidence_refs=evidence_refs,
            contract_sha256=contract_sha,
            thresholds=limits,
            rationale=(
                f"Walk-forward evidence has {n_reports} reports but requires "
                f"at least {max(3, min_windows)}."
            ),
        )

    candidate = _select_best_stable_candidate(walk_forward_stability)
    if candidate is None:
        return PromotionDecision(
            subject_id=subject_id,
            status=PromotionStatus.REJECTED,
            trade_ready=False,
            failed_gates=("stable_research_candidate",),
            evidence_refs=evidence_refs,
            contract_sha256=contract_sha,
            thresholds=limits,
            rationale="No candidate satisfied the stable research-candidate gate.",
        )

    failed = _metric_failures(candidate, limits)
    if not failed:
        status = PromotionStatus.TRADE_GUIDANCE_CANDIDATE
        rationale = "All execution, readiness, stability, and promotion gates passed."
    elif (
        float(candidate.get("mean_icir", 0.0)) >= limits.stronger_research_icir
        and float(candidate.get("worst_drawdown", 0.0))
        >= limits.max_drawdown_floor
    ):
        status = PromotionStatus.STRONGER_RESEARCH_CANDIDATE
        rationale = "Candidate is stronger research evidence but failed promotion gates."
    else:
        status = PromotionStatus.RESEARCH_CANDIDATE
        rationale = "Candidate remains research-only and failed promotion gates."

    return PromotionDecision(
        subject_id=subject_id,
        status=status,
        trade_ready=status is PromotionStatus.TRADE_GUIDANCE_CANDIDATE,
        candidate=candidate,
        failed_gates=failed,
        evidence_refs=evidence_refs,
        contract_sha256=contract_sha,
        thresholds=limits,
        rationale=rationale,
    )


def build_promotion_decision_from_run(
    run_dir: str | Path,
    *,
    subject_id: str | None = None,
    thresholds: PromotionThresholds | None = None,
) -> PromotionDecision:
    """Read required run artifacts and fail closed when any evidence is missing."""
    root = Path(run_dir).resolve()
    resolved = {
        name: root / filename for name, filename in REQUIRED_EVIDENCE_FILES.items()
    }
    missing = tuple(name for name, path in resolved.items() if not path.is_file())
    effective_subject = subject_id or root.name
    present = {name: path for name, path in resolved.items() if path.is_file()}
    refs = _evidence_refs(root, present)
    if missing:
        return PromotionDecision(
            subject_id=effective_subject,
            status=PromotionStatus.MISSING_EVIDENCE,
            trade_ready=False,
            missing_evidence=missing,
            evidence_refs=refs,
            thresholds=thresholds or PromotionThresholds(),
            rationale="Required evidence artifacts are missing.",
        )

    try:
        identity = _read_json(resolved["execution_identity"])
        readiness = _read_json(resolved["data_readiness"])
        stability = _read_json(resolved["walk_forward_stability"])
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return PromotionDecision(
            subject_id=effective_subject,
            status=PromotionStatus.MISSING_EVIDENCE,
            trade_ready=False,
            missing_evidence=("invalid_evidence",),
            evidence_refs=refs,
            thresholds=thresholds or PromotionThresholds(),
            rationale=f"Evidence could not be read: {type(exc).__name__}: {exc}",
        )

    return build_promotion_decision(
        subject_id=effective_subject,
        execution_identity=identity,
        data_readiness=readiness,
        walk_forward_stability=stability,
        evidence_refs=refs,
        thresholds=thresholds,
    )


def write_promotion_decision(
    run_dir: str | Path,
    decision: PromotionDecision,
) -> Path:
    """Atomically write the canonical promotion artifact."""
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / PROMOTION_DECISION_FILENAME
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(decision.to_dict(), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def finalize_promotion_decision(
    run_dir: str | Path,
    *,
    subject_id: str | None = None,
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    """Build, persist, and return one canonical promotion decision."""
    decision = build_promotion_decision_from_run(
        run_dir,
        subject_id=subject_id,
        thresholds=thresholds,
    )
    path = write_promotion_decision(run_dir, decision)
    payload = decision.to_dict()
    payload["artifact_path"] = str(path)
    return payload
