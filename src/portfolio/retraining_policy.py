"""Evidence-driven retraining policy (T47.7).

Decides whether an operational Champion should spawn a Challenger retraining
run from explicit triggers: schedule, accumulated new data, drift, performance
decay or policy change.

Invariants:

- repeated alerts cannot create a training storm (cooldown plus a daily
  resource budget bound how often retraining may start);
- unchanged data and configuration cannot create a duplicate candidate;
- every evaluation records why retraining was or was not started;
- a concurrency lock and resource budget prevent concurrent heavy workflows
  from exhausting the reference machine;
- evaluations are idempotent and auditable through an append-only JSONL trail.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "RetrainingPolicyError",
    "RetrainingTrigger",
    "RetrainingPolicyConfig",
    "RetrainingState",
    "RetrainingDecision",
    "RetrainingPolicyEngine",
]

SCHEMA_VERSION = "retraining_policy_v1"


class RetrainingPolicyError(Exception):
    """Raised when the policy configuration or inputs are invalid."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class RetrainingTrigger:
    """One evidence-backed reason to consider retraining."""

    kind: str  # schedule | new_data | drift | performance_decay | policy_change
    detail: str
    source_ref: str = ""

    def canonical(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "source_ref": self.source_ref}


ALLOWED_TRIGGERS = {"schedule", "new_data", "drift", "performance_decay", "policy_change"}


@dataclass(frozen=True)
class RetrainingPolicyConfig:
    """Versioned retraining resource and cadence limits."""

    policy_version: str = "retraining_policy_v1"
    cooldown_hours: float = 24.0
    min_new_observations: int = 60
    max_concurrent_heavy_workflows: int = 1
    active_heavy_workflows: int = 0
    max_retrains_per_day: int = 1
    schedule_days: float = 0.0  # 0 disables the automatic schedule trigger

    def validate(self) -> None:
        reasons: list[str] = []
        if not self.policy_version.strip():
            reasons.append("policy_version is required")
        if self.cooldown_hours < 0:
            reasons.append("cooldown_hours must be non-negative")
        if self.min_new_observations < 0:
            reasons.append("min_new_observations must be non-negative")
        if self.max_concurrent_heavy_workflows < 1:
            reasons.append("max_concurrent_heavy_workflows must be at least 1")
        if self.active_heavy_workflows < 0:
            reasons.append("active_heavy_workflows must be non-negative")
        if self.max_retrains_per_day < 1:
            reasons.append("max_retrains_per_day must be at least 1")
        if self.schedule_days < 0:
            reasons.append("schedule_days must be non-negative")
        if reasons:
            raise RetrainingPolicyError(reasons)

    def canonical(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "cooldown_hours": self.cooldown_hours,
            "min_new_observations": self.min_new_observations,
            "max_concurrent_heavy_workflows": self.max_concurrent_heavy_workflows,
            "active_heavy_workflows": self.active_heavy_workflows,
            "max_retrains_per_day": self.max_retrains_per_day,
            "schedule_days": self.schedule_days,
        }


@dataclass(frozen=True)
class RetrainingState:
    """Persisted facts about the previous retraining run."""

    last_retrain_completed_at: str | None = None
    last_snapshot_id: str | None = None
    last_config_digest: str | None = None
    observations_at_last_retrain: int | None = None

    def canonical(self) -> dict[str, Any]:
        return {
            "last_retrain_completed_at": self.last_retrain_completed_at,
            "last_snapshot_id": self.last_snapshot_id,
            "last_config_digest": self.last_config_digest,
            "observations_at_last_retrain": self.observations_at_last_retrain,
        }


@dataclass(frozen=True)
class RetrainingDecision:
    """Why retraining did or did not start; never silent."""

    evaluation_id: str
    outcome: str  # "start_retraining" | "no_change"
    model_version_id: str
    proposed_challenger_id: str | None
    triggers_considered: tuple[dict[str, Any], ...]
    reasons_started: tuple[str, ...]
    reasons_blocked: tuple[str, ...]
    decided_at: str
    research_only: bool = True
    trade_ready: bool = False

    @property
    def started(self) -> bool:
        return self.outcome == "start_retraining"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "evaluation_id": self.evaluation_id,
            "outcome": self.outcome,
            "model_version_id": self.model_version_id,
            "proposed_challenger_id": self.proposed_challenger_id,
            "triggers_considered": [dict(t) for t in self.triggers_considered],
            "reasons_started": list(self.reasons_started),
            "reasons_blocked": list(self.reasons_blocked),
            "decided_at": self.decided_at,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
        }


@dataclass
class _Audit:
    path: Path | None = None

    def find(self, evaluation_id: str) -> RetrainingDecision | None:
        if self.path is None or not self.path.exists():
            return None
        for line in self._read_lines(self.path):
            payload = json.loads(line)
            if payload.get("evaluation_id") != evaluation_id:
                continue
            return RetrainingDecision(
                evaluation_id=payload["evaluation_id"],
                outcome=payload["outcome"],
                model_version_id=payload["model_version_id"],
                proposed_challenger_id=payload.get("proposed_challenger_id"),
                triggers_considered=tuple(payload["triggers_considered"]),
                reasons_started=tuple(payload["reasons_started"]),
                reasons_blocked=tuple(payload["reasons_blocked"]),
                decided_at=payload["decided_at"],
                research_only=bool(payload.get("research_only", True)),
                trade_ready=bool(payload.get("trade_ready", False)),
            )
        return None

    def retrains_today(self, day: str) -> int:
        if self.path is None or not self.path.exists():
            return 0
        count = 0
        for line in self._read_lines(self.path):
            payload = json.loads(line)
            if (
                payload.get("outcome") == "start_retraining"
                and str(payload.get("decided_at", "")).startswith(day)
            ):
                count += 1
        return count

    def append(self, decision: RetrainingDecision) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        if self.path.exists():
            for line in self._read_lines(self.path):
                seen.add(json.loads(line)["evaluation_id"])
        if decision.evaluation_id in seen:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(decision.to_dict()) + "\n")
            handle.flush()

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RetrainingPolicyEngine:
    """Idempotent, auditable retraining decisions under resource limits."""

    def __init__(
        self,
        config: RetrainingPolicyConfig | None = None,
        *,
        audit_path: str | Path | None = None,
    ) -> None:
        self._config = config or RetrainingPolicyConfig()
        self._config.validate()
        self._audit = _Audit(Path(audit_path) if audit_path else None)

    @property
    def config(self) -> RetrainingPolicyConfig:
        return self._config

    def evaluate(
        self,
        *,
        model_version_id: str,
        now_iso: str,
        snapshot_id: str,
        observation_count: int,
        config_digest: str,
        triggers: list[RetrainingTrigger] | None = None,
        state: RetrainingState | None = None,
    ) -> RetrainingDecision:
        triggers = list(triggers or [])
        state = state or RetrainingState()
        reasons_missing = [
            name
            for name, value in (
                ("model_version_id", model_version_id),
                ("now_iso", now_iso),
                ("snapshot_id", snapshot_id),
                ("config_digest", config_digest),
            )
            if not value
        ]
        if reasons_missing:
            raise RetrainingPolicyError([f"{name} is required" for name in reasons_missing])
        try:
            now = datetime.fromisoformat(now_iso)
        except ValueError as exc:
            raise RetrainingPolicyError([f"now_iso is not ISO-8601: {exc}"]) from exc
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        considered = [dict(t.canonical()) for t in triggers]
        unknown = sorted({t["kind"] for t in considered} - ALLOWED_TRIGGERS)
        if unknown:
            raise RetrainingPolicyError([f"unknown trigger kinds: {unknown}"])

        effective_triggers = list(triggers)
        auto_schedule = self._auto_schedule_trigger(now, state)
        if auto_schedule is not None:
            effective_triggers.append(auto_schedule)
            considered.append(dict(auto_schedule.canonical()))

        evaluation_id = self._evaluation_id(
            model_version_id=model_version_id,
            now_iso=now_iso,
            snapshot_id=snapshot_id,
            observation_count=observation_count,
            config_digest=config_digest,
            triggers=effective_triggers,
            state=state,
        )
        existing = self._audit.find(evaluation_id)
        if existing is not None:
            return existing

        started_reasons: list[str] = []
        blocked_reasons: list[str] = []

        has_policy_change = any(t.kind == "policy_change" for t in effective_triggers)

        unchanged_identity = (
            state.last_snapshot_id == snapshot_id
            and state.last_config_digest == config_digest
            and not has_policy_change
        )
        if unchanged_identity:
            if has_policy_change:
                started_reasons.append("policy_change overrides duplicate guard")
            else:
                blocked_reasons.append(
                    "duplicate_guard: unchanged snapshot and config cannot create a duplicate candidate"
                )

        last_done = state.last_retrain_completed_at
        if last_done:
            try:
                completed = datetime.fromisoformat(last_done)
                if completed.tzinfo is None:
                    completed = completed.replace(tzinfo=timezone.utc)
                elapsed = now - completed
                if elapsed < timedelta(hours=self._config.cooldown_hours):
                    blocked_reasons.append(
                        f"cooldown: {elapsed.total_seconds()/3600:.2f}h since last completion "
                        f"is below {self._config.cooldown_hours}h"
                    )
            except ValueError:
                blocked_reasons.append(f"unparseable last_retrain_completed_at: {last_done}")

        new_observations = observation_count - (state.observations_at_last_retrain or 0)
        needs_new_data = any(t.kind in {"schedule", "drift", "performance_decay"} for t in effective_triggers)
        if needs_new_data and new_observations < self._config.min_new_observations:
            blocked_reasons.append(
                f"insufficient_new_observations: {new_observations} below minimum "
                f"{self._config.min_new_observations}"
            )

        if self._config.active_heavy_workflows >= self._config.max_concurrent_heavy_workflows:
            blocked_reasons.append(
                "concurrency_lock: "
                f"{self._config.active_heavy_workflows} heavy workflow(s) already running "
                f"(limit {self._config.max_concurrent_heavy_workflows})"
            )

        day = now.date().isoformat()
        used_today = self._audit.retrains_today(day)
        if used_today >= self._config.max_retrains_per_day:
            blocked_reasons.append(
                f"daily_budget_exhausted: {used_today} retrain(s) already started on {day}"
            )

        if blocked_reasons:
            outcome = "no_change"
            proposed = None
        elif effective_triggers:
            outcome = "start_retraining"
            digest_short = hashlib.sha256(config_digest.encode()).hexdigest()[:8]
            proposed = f"{model_version_id}-challenger-{snapshot_id}-{digest_short}"
            started_reasons.extend(
                f"trigger:{t.kind}:{t.source_ref or t.detail}" for t in effective_triggers
            )
        else:
            outcome = "no_change"
            proposed = None
            blocked_reasons.append(
                "no_qualifying_trigger: supplied triggers do not require retraining"
            )

        decision = RetrainingDecision(
            evaluation_id=evaluation_id,
            outcome=outcome,
            model_version_id=model_version_id,
            proposed_challenger_id=proposed,
            triggers_considered=tuple(considered),
            reasons_started=tuple(started_reasons),
            reasons_blocked=tuple(blocked_reasons),
            decided_at=now.isoformat(),
        )
        self._audit.append(decision)
        return decision

    # ------------------------------------------------------------------

    def _auto_schedule_trigger(
        self, now: datetime, state: RetrainingState
    ) -> RetrainingTrigger | None:
        if self._config.schedule_days <= 0 or not state.last_retrain_completed_at:
            return None
        try:
            completed = datetime.fromisoformat(state.last_retrain_completed_at)
        except ValueError:
            return None
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        elapsed_days = (now - completed).total_seconds() / 86_400.0
        if elapsed_days >= self._config.schedule_days:
            return RetrainingTrigger(
                kind="schedule",
                detail=f"{elapsed_days:.1f} days since last retraining",
                source_ref=f"schedule_days={self._config.schedule_days}",
            )
        return None

    def _evaluation_id(
        self,
        *,
        model_version_id: str,
        now_iso: str,
        snapshot_id: str,
        observation_count: int,
        config_digest: str,
        triggers: list[RetrainingTrigger],
        state: RetrainingState,
    ) -> str:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "policy": self._config.canonical(),
            "model_version_id": model_version_id,
            "now_iso": now_iso,
            "snapshot_id": snapshot_id,
            "observation_count": observation_count,
            "config_digest": config_digest,
            "triggers": [t.canonical() for t in sorted(triggers, key=lambda x: (x.kind, x.detail))],
            "state": state.canonical(),
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
