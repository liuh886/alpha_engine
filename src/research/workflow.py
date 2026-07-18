"""Canonical Research Workflow module.

Adapters should submit research intent here instead of owning scan/compile/
train/backtest/promote semantics themselves. The default implementation is a
small orchestrator around an injected executor, which keeps heavy Qlib work
behind a testable seam.
"""

from __future__ import annotations

from typing import Protocol

from src.research.workflow_store import ResearchWorkflowStore
from src.research.workflow_types import (
    CANONICAL_RESEARCH_STEPS,
    ResearchStep,
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
    StepResult,
    WorkflowStatus,
    utc_now,
)


class ResearchWorkflowExecutor(Protocol):
    """Executor seam used by the canonical Research Workflow module."""

    def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
        """Run one canonical workflow step."""


class PlaceholderResearchExecutor:
    """Safe executor used until adapters are migrated to concrete implementations."""

    def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
        now = utc_now()
        return StepResult(
            step=step,
            status=WorkflowStatus.SKIPPED,
            output={
                "market": request.market,
                "model_type": request.model_type,
                "reason": "No concrete ResearchWorkflowExecutor configured.",
            },
            started_at=now,
            completed_at=now,
        )


class ResearchWorkflow:
    """Run the canonical research workflow through a single interface."""

    def __init__(
        self,
        executor: ResearchWorkflowExecutor | None = None,
        store: ResearchWorkflowStore | None = None,
    ) -> None:
        self.executor = executor or PlaceholderResearchExecutor()
        self.store = store or ResearchWorkflowStore()

    def run(self, request: ResearchWorkflowRequest) -> ResearchWorkflowResult:
        """Execute every canonical step in order and persist the summary."""
        run_id = request.run_id or f"rw_{utc_now().replace(':', '').replace('-', '')}"
        request = ResearchWorkflowRequest(
            market=request.market,
            goal=request.goal,
            model_type=request.model_type,
            run_id=run_id,
            requested_by=request.requested_by,
            metadata=request.metadata,
        )
        result = ResearchWorkflowResult(
            run_id=run_id,
            request=request,
            status=WorkflowStatus.RUNNING,
            started_at=utc_now(),
        )
        self.store.save(result)

        for step in CANONICAL_RESEARCH_STEPS:
            step_result = self.run_step(request, step)
            result.steps.append(step_result)
            # Capture canonical promotion decision from the PROMOTE step
            if step is ResearchStep.PROMOTE and step_result.status == WorkflowStatus.COMPLETED:
                self._set_promotion_decision(result, step_result)
            self.store.save(result)
            if step_result.status == WorkflowStatus.FAILED:
                result.status = WorkflowStatus.FAILED
                result.completed_at = utc_now()
                self.store.save(result)
                return result

        non_promotion_steps = [
            step for step in result.steps if step.step is not ResearchStep.PROMOTE
        ]
        if non_promotion_steps and all(
            step.status == WorkflowStatus.SKIPPED for step in non_promotion_steps
        ):
            result.status = WorkflowStatus.SKIPPED
        else:
            result.status = WorkflowStatus.COMPLETED
        result.completed_at = utc_now()
        self.store.save(result)
        return result

    def _set_promotion_decision(
        self, result: ResearchWorkflowResult, step_result: StepResult
    ) -> None:
        """Validate and store a canonical promotion decision from the PROMOTE step.

        Invalid legacy payloads (e.g. {recommendation: DEPLOY}) fail closed:
        they are rejected and the workflow result is NOT marked as promoted.
        """
        raw = step_result.output
        try:
            from src.research.promotion_consumers import validate_promotion_payload

            if not isinstance(raw, dict):
                raise TypeError("PROMOTE step output must be an object")
            validated = validate_promotion_payload(raw)
            allowed_subject_ids = {result.run_id}
            allowed_subject_ids.update(
                str(step.output["experiment_id"])
                for step in result.steps
                if isinstance(step.output, dict) and step.output.get("experiment_id")
            )
            if validated["subject_id"] not in allowed_subject_ids:
                raise ValueError(
                    "promotion subject_id does not match the workflow run_id "
                    "or a recorded experiment_id"
                )
        except (ValueError, KeyError, TypeError) as exc:
            warning = (
                f"PROMOTE output failed validation: {exc}. "
                "Legacy payloads (e.g. {recommendation: DEPLOY}) are not canonical PromotionDecisions."
            )
            result.warnings.append(warning)
            step_result.status = WorkflowStatus.FAILED
            step_result.error = warning
            return
        result.promotion_decision = validated

    def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
        """Run one step while converting unexpected exceptions into failed results."""
        started_at = utc_now()
        try:
            step_result = self.executor.run_step(request, step)
        except Exception as exc:
            return StepResult(
                step=step,
                status=WorkflowStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                started_at=started_at,
                completed_at=utc_now(),
            )
        if step_result.started_at is None:
            step_result.started_at = started_at
        if step_result.completed_at is None:
            step_result.completed_at = utc_now()
        return step_result

    def load(self, run_id: str) -> ResearchWorkflowResult:
        return self.store.load(run_id)

    def list_runs(self, limit: int = 20) -> list[dict]:
        return self.store.list(limit=limit)
