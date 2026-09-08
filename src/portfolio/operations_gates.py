"""Automated continue/retrain/demote/stop/rollback decisions (T47.6).

A versioned operational gate policy combines data freshness, artifact health,
risk state, signal evaluation, drift severity and paper performance into one
auditable lifecycle decision per evaluation.

Invariants:

- failed freshness, artifact or risk hard gates set ``plan_eligible=False`` so
  no new advisory ExecutionPlan may be produced;
- degradation never silently retains Champion status: every non-continue
  decision names the gate that triggered it and the required recovery;
- automatic actions are idempotent (identical facts produce an identical
  record id and a single audit entry) and auditable (append-only JSONL trail);
- a ``retrain`` decision creates a Challenger; it never overwrites the current
  Champion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "OperationsGateError",
    "OperationalGatePolicy",
    "GateFacts",
    "GateResult",
    "DecisionRecord",
    "OperationsGateEngine",
]

SCHEMA_VERSION = "operations_gate_v1"
_DECISION_PRECEDENCE = ["stop", "rollback", "demote", "retrain", "continue"]


class OperationsGateError(Exception):
    """Raised when the gate policy or inputs are invalid; fails closed."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class OperationalGatePolicy:
    """Versioned thresholds for automated operational decisions."""

    policy_version: str = "ops_gate_policy_v1"
    max_data_age_days: float = 3.0
    stale_escalation_age_days: float = 10.0
    drawdown_stop_threshold: float = -0.25
    drawdown_demote_threshold: float = -0.20
    min_signal_sample_count: int = 30
    paper_excess_retrain_floor: float = -0.02
    paper_excess_stop_floor: float = -0.10
    require_artifact_verified: bool = True

    def validate(self) -> None:
        reasons: list[str] = []
        if not self.policy_version.strip():
            reasons.append("policy_version is required")
        if self.max_data_age_days <= 0:
            reasons.append("max_data_age_days must be positive")
        if self.stale_escalation_age_days < self.max_data_age_days:
            reasons.append("stale_escalation_age_days must be >= max_data_age_days")
        if not (-1.0 < self.drawdown_stop_threshold < self.drawdown_demote_threshold < 0.0):
            reasons.append("drawdown thresholds must satisfy stop < demote < 0")
        if self.min_signal_sample_count < 1:
            reasons.append("min_signal_sample_count must be at least 1")
        if self.paper_excess_stop_floor >= self.paper_excess_retrain_floor:
            reasons.append("paper_excess_stop_floor must be below paper_excess_retrain_floor")
        if reasons:
            raise OperationsGateError(reasons)

    def canonical(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "max_data_age_days": self.max_data_age_days,
            "stale_escalation_age_days": self.stale_escalation_age_days,
            "drawdown_stop_threshold": self.drawdown_stop_threshold,
            "drawdown_demote_threshold": self.drawdown_demote_threshold,
            "min_signal_sample_count": self.min_signal_sample_count,
            "paper_excess_retrain_floor": self.paper_excess_retrain_floor,
            "paper_excess_stop_floor": self.paper_excess_stop_floor,
            "require_artifact_verified": self.require_artifact_verified,
        }


@dataclass(frozen=True)
class GateFacts:
    """Observed operational facts feeding one gate evaluation.

    Any fact left as ``None`` is inconclusive and fails closed to a hard block.
    """

    data_freshness_status: str | None  # "current" | "stale" | "missing"
    data_age_days: float | None
    artifact_status: str | None  # "verified" | "damaged" | "missing"
    previous_verified_champion_id: str | None
    current_drawdown: float | None
    risk_limit_breached: bool
    signal_qualified: bool | None
    signal_sample_count: int | None
    drift_severity: str | None  # ok | watch | warning | critical
    paper_excess_return: float | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def canonical(self) -> dict[str, Any]:
        return {
            "data_freshness_status": self.data_freshness_status,
            "data_age_days": self.data_age_days,
            "artifact_status": self.artifact_status,
            "previous_verified_champion_id": self.previous_verified_champion_id,
            "current_drawdown": self.current_drawdown,
            "risk_limit_breached": self.risk_limit_breached,
            "signal_qualified": self.signal_qualified,
            "signal_sample_count": self.signal_sample_count,
            "drift_severity": self.drift_severity,
            "paper_excess_return": self.paper_excess_return,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str  # "pass" | "fail" | "inconclusive"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class DecisionRecord:
    """One auditable, idempotent operational decision."""

    record_id: str
    policy_version: str
    decided_at: str
    market: str
    model_version_id: str
    champion_id: str | None
    decision: str
    plan_eligible: bool
    gates: tuple[GateResult, ...]
    hard_blocks: tuple[str, ...]
    recovery_conditions: tuple[str, ...]
    challenger_created: bool
    champion_unchanged: bool
    research_only: bool = True
    trade_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "record_id": self.record_id,
            "policy_version": self.policy_version,
            "decided_at": self.decided_at,
            "market": self.market,
            "model_version_id": self.model_version_id,
            "champion_id": self.champion_id,
            "decision": self.decision,
            "plan_eligible": self.plan_eligible,
            "gates": [g.to_dict() for g in self.gates],
            "hard_blocks": list(self.hard_blocks),
            "recovery_conditions": list(self.recovery_conditions),
            "challenger_created": self.challenger_created,
            "champion_unchanged": self.champion_unchanged,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
        }


class OperationsGateEngine:
    """Evaluates versioned operational gates into auditable decisions."""

    def __init__(
        self,
        policy: OperationalGatePolicy | None = None,
        *,
        audit_path: str | Path | None = None,
    ) -> None:
        self._policy = policy or OperationalGatePolicy()
        self._policy.validate()
        self._audit_path = Path(audit_path) if audit_path else None

    @property
    def policy(self) -> OperationalGatePolicy:
        return self._policy

    def evaluate(
        self,
        *,
        market: str,
        model_version_id: str,
        champion_id: str | None = None,
        decided_at: str | None = None,
        facts: GateFacts,
    ) -> DecisionRecord:
        if not market or not model_version_id:
            raise OperationsGateError(["market and model_version_id are required"])

        gates: list[GateResult] = []
        hard_blocks: list[str] = []
        recoveries: list[str] = []
        triggered: dict[str, list[str]] = {}

        # --- data freshness -------------------------------------------------
        freshness = facts.data_freshness_status
        age = facts.data_age_days
        if freshness is None or freshness == "missing":
            gates.append(GateResult("data_freshness", "inconclusive", "freshness fact missing"))
            hard_blocks.append("data_freshness_inconclusive_or_missing")
            recoveries.append("republish a verified data snapshot before new plans")
        elif freshness == "current":
            gates.append(GateResult("data_freshness", "pass", f"age={age}d"))
        else:
            limit = self._policy.max_data_age_days
            escalate = age is not None and age > self._policy.stale_escalation_age_days
            gates.append(
                GateResult(
                    "data_freshness",
                    "fail",
                    f"status=stale age={age}d limit={limit}d escalate={escalate}",
                )
            )
            hard_blocks.append("data_stale_beyond_limit")
            recoveries.append("refresh provider data and republish snapshot")
            if escalate:
                triggered.setdefault("retrain", []).append(
                    f"data staleness {age}d exceeds escalation {self._policy.stale_escalation_age_days}d"
                )

        # --- artifact health ------------------------------------------------
        artifact = facts.artifact_status
        if artifact is None:
            gates.append(GateResult("artifact_health", "inconclusive", "artifact fact missing"))
            hard_blocks.append("artifact_health_inconclusive")
            recoveries.append("verify the ModelArtifact checksums")
        elif artifact == "verified" or not self._policy.require_artifact_verified:
            gates.append(GateResult("artifact_health", "pass", f"status={artifact}"))
        elif artifact == "damaged":
            if facts.previous_verified_champion_id:
                gates.append(GateResult("artifact_health", "fail", "artifact damaged; verified predecessor exists"))
                triggered.setdefault("rollback", []).append("artifact damaged")
                recoveries.append(f"roll back to verified champion {facts.previous_verified_champion_id}")
            else:
                gates.append(GateResult("artifact_health", "fail", "artifact damaged; no verified predecessor"))
                triggered.setdefault("stop", []).append("artifact damaged without predecessor")
                recoveries.append("rebuild and re-verify the artifact before any plan")
            hard_blocks.append("artifact_not_verified")
        else:
            gates.append(GateResult("artifact_health", "fail", f"status={artifact}"))
            hard_blocks.append("artifact_missing")
            recoveries.append("restore artifact from immutable store")

        # --- risk state -----------------------------------------------------
        dd = facts.current_drawdown
        if dd is None:
            gates.append(GateResult("risk_state", "inconclusive", "drawdown fact missing"))
            hard_blocks.append("risk_state_inconclusive")
            recoveries.append("publish a current PortfolioRiskState")
        else:
            if facts.risk_limit_breached or dd <= self._policy.drawdown_stop_threshold:
                gates.append(
                    GateResult("risk_state", "fail", f"drawdown={dd:.4f} stop<={self._policy.drawdown_stop_threshold:.4f}")
                )
                triggered.setdefault("stop", []).append(f"drawdown {dd:.4f} breached stop threshold")
                hard_blocks.append("risk_hard_gate_failed")
                recoveries.append("reduce exposure; re-enter only after risk state recovers")
            elif dd <= self._policy.drawdown_demote_threshold:
                gates.append(
                    GateResult(
                        "risk_state",
                        "fail",
                        f"soft gate: drawdown={dd:.4f} beyond demote threshold {self._policy.drawdown_demote_threshold:.4f}",
                    )
                )
                triggered.setdefault("demote", []).append(f"drawdown {dd:.4f} beyond demote threshold")
                hard_blocks.append("risk_soft_gate_failed")
                recoveries.append("demote champion pending improved risk state")
            else:
                gates.append(GateResult("risk_state", "pass", f"drawdown={dd:.4f}"))

        # --- signal evaluation ----------------------------------------------
        qualified = facts.signal_qualified
        sample = facts.signal_sample_count
        if qualified is None:
            gates.append(GateResult("signal_evaluation", "inconclusive", "qualification fact missing"))
            hard_blocks.append("signal_evaluation_inconclusive")
            recoveries.append("run SignalEvaluation with sufficient observations")
        elif qualified is False:
            if sample is not None and sample < self._policy.min_signal_sample_count:
                gates.append(
                    GateResult(
                        "signal_evaluation",
                        "inconclusive",
                        f"unqualified but sample {sample} below minimum {self._policy.min_signal_sample_count}; insufficient evidence",
                    )
                )
            else:
                gates.append(GateResult("signal_evaluation", "fail", f"qualified=False sample={sample}"))
                triggered.setdefault("retrain", []).append("signal evaluation unqualified with sufficient evidence")
                recoveries.append("retrain a Challenger on refreshed data")

        # --- drift ------------------------------------------------------------
        severity = facts.drift_severity
        mapping = {
            "ok": ("pass", None),
            "watch": ("pass", None),
            "warning": ("fail", "retrain"),
            "critical": ("fail", "stop"),
        }
        if severity is None:
            gates.append(GateResult("drift_monitoring", "inconclusive", "drift report missing"))
            hard_blocks.append("drift_inconclusive")
            recoveries.append("produce a current DriftReport")
        else:
            status, action = mapping.get(severity, ("inconclusive", None))
            gates.append(GateResult("drift_monitoring", status, f"severity={severity}"))
            if action:
                triggered.setdefault(action, []).append(f"drift severity {severity}")
                if action == "stop":
                    hard_blocks.append("drift_critical")
                    recoveries.append("halt plans until drift investigation completes")
                else:
                    recoveries.append("retrain a Challenger to absorb detected drift")

        # --- paper performance -------------------------------------------------
        excess = facts.paper_excess_return
        if excess is None:
            gates.append(GateResult("paper_performance", "inconclusive", "paper performance missing"))
            hard_blocks.append("paper_performance_inconclusive")
            recoveries.append("attribute the latest paper window")
        elif excess <= self._policy.paper_excess_stop_floor:
            gates.append(GateResult("paper_performance", "fail", f"excess={excess:.4f} <= stop floor {self._policy.paper_excess_stop_floor:.4f}"))
            triggered.setdefault("stop", []).append(f"paper excess {excess:.4f} at/below stop floor")
            hard_blocks.append("paper_performance_hard_gate_failed")
            recoveries.append("stop operations pending root-cause review")
        elif excess < self._policy.paper_excess_retrain_floor:
            gates.append(GateResult("paper_performance", "fail", f"excess={excess:.4f} < retrain floor {self._policy.paper_excess_retrain_floor:.4f}"))
            triggered.setdefault("retrain", []).append(f"paper excess {excess:.4f} below retrain floor")
            recoveries.append("retrain a Challenger on accumulated new evidence")
        else:
            gates.append(GateResult("paper_performance", "pass", f"excess={excess:.4f}"))

        # --- precedence -----------------------------------------------------
        decision = "continue"
        for candidate in _DECISION_PRECEDENCE:
            if candidate in triggered:
                decision = candidate
                break
        if decision != "continue" and champion_id is None:
            decision = "stop" if decision in {"rollback", "demote"} else decision
            recoveries.append("no Champion is declared; lifecycle action applied as stop-equivalent hold")

        plan_eligible = not hard_blocks and decision == "continue"
        record = DecisionRecord(
            record_id=self._record_id(market, model_version_id, champion_id, facts),
            policy_version=self._policy.policy_version,
            decided_at=decided_at or datetime.now(timezone.utc).isoformat(),
            market=market,
            model_version_id=model_version_id,
            champion_id=champion_id,
            decision=decision,
            plan_eligible=plan_eligible,
            gates=tuple(gates),
            hard_blocks=tuple(sorted(set(hard_blocks))),
            recovery_conditions=tuple(dict.fromkeys(recoveries)),
            challenger_created=decision == "retrain",
            champion_unchanged=decision != "promote",
        )
        self._audit(record)
        return record

    def _record_id(
        self, market: str, model_version_id: str, champion_id: str | None, facts: GateFacts
    ) -> str:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "policy": self._policy.canonical(),
            "market": market,
            "model_version_id": model_version_id,
            "champion_id": champion_id,
            "facts": facts.canonical(),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def _audit(self, record: DecisionRecord) -> None:
        if self._audit_path is None:
            return
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        existing: set[str] = set()
        if self._audit_path.exists():
            for line in self._audit_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    existing.add(json.loads(line)["record_id"])
        if record.record_id in existing:
            return
        with self._audit_path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(record.to_dict()) + "\n")
            handle.flush()
