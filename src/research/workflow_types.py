"""Typed interface for the canonical research workflow.

This module defines the small interface adapters should use when they need to
start or inspect research work. Heavy Qlib/MLflow execution stays behind the
workflow executor seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ResearchStep(str, Enum):
    """Canonical research workflow step order."""

    SCAN = "scan"
    COMPILE = "compile"
    TRAIN = "train"
    WALK_FORWARD = "walk_forward"
    BACKTEST = "backtest"
    ATTRIBUTION = "attribution"
    PROMOTE = "promote"


CANONICAL_RESEARCH_STEPS: tuple[ResearchStep, ...] = (
    ResearchStep.SCAN,
    ResearchStep.COMPILE,
    ResearchStep.TRAIN,
    ResearchStep.WALK_FORWARD,
    ResearchStep.BACKTEST,
    ResearchStep.ATTRIBUTION,
    ResearchStep.PROMOTE,
)


class WorkflowStatus(str, Enum):
    """Lifecycle status for a workflow run or step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


def utc_now() -> str:
    """Return an ISO timestamp with explicit UTC timezone."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ResearchWorkflowRequest:
    """Intent-shaped request accepted by the Research Workflow module."""

    market: str = "cn"
    goal: str = "Find alpha factors"
    model_type: str = "lgbm"
    run_id: str | None = None
    requested_by: str = "adapter"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "goal": self.goal,
            "model_type": self.model_type,
            "run_id": self.run_id,
            "requested_by": self.requested_by,
            "metadata": dict(self.metadata),
        }


@dataclass
class StepResult:
    """Result emitted by a single canonical workflow step."""

    step: ResearchStep
    status: WorkflowStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step.value,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class ResearchWorkflowResult:
    """Durable summary of a canonical research workflow run."""

    run_id: str
    request: ResearchWorkflowRequest
    status: WorkflowStatus = WorkflowStatus.PENDING
    steps: list[StepResult] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    evidence_bundle_id: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "evidence_bundle_id": self.evidence_bundle_id,
            "warnings": list(self.warnings),
        }
