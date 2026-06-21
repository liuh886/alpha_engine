"""Legacy execution adapter for the canonical Research Workflow interface.

This adapter preserves existing Qlib-backed behaviour while callers migrate to
``ResearchWorkflow``. It deliberately lives outside ``workflow.py`` so the core
workflow interface stays dependency-light.
"""

from __future__ import annotations

from typing import Any

from src.research.workflow_types import (
    ResearchStep,
    ResearchWorkflowRequest,
    StepResult,
    WorkflowStatus,
    utc_now,
)

_LEGACY_STEP_MAP = {
    "factor_scan": ResearchStep.SCAN,
    "compile": ResearchStep.COMPILE,
    "train": ResearchStep.TRAIN,
    "walk_forward": ResearchStep.WALK_FORWARD,
    "backtest": ResearchStep.BACKTEST,
    "attribution": ResearchStep.ATTRIBUTION,
    "promote": ResearchStep.PROMOTE,
}


class LegacyResearchPipelineExecutor:
    """Run the existing research pipeline behind the new workflow seam."""

    def __init__(self) -> None:
        self._ran = False
        self._step_results: dict[ResearchStep, StepResult] = {}
        self._failure: Exception | None = None

    def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
        if not self._ran:
            self._run_legacy_pipeline(request)
        if self._failure is not None:
            return StepResult(
                step=step,
                status=WorkflowStatus.FAILED,
                error=f"{type(self._failure).__name__}: {self._failure}",
            )
        return self._step_results.get(
            step,
            StepResult(
                step=step,
                status=WorkflowStatus.SKIPPED,
                output={"reason": "Legacy pipeline did not emit this step."},
                started_at=utc_now(),
                completed_at=utc_now(),
            ),
        )

    def _run_legacy_pipeline(self, request: ResearchWorkflowRequest) -> None:
        self._ran = True
        try:
            from src.research.pipeline import ResearchRun, run_research_pipeline
            from src.workflows.hooks import run_training_pipeline

            legacy_run = ResearchRun(
                run_id=request.run_id or "",
                market=request.market,
                goal=request.goal,
                metadata={"requested_by": request.requested_by, **request.metadata},
            )
            result = run_research_pipeline(
                market=request.market,
                goal=request.goal,
                model_type=request.model_type,
                existing_run=legacy_run,
                _train_fn=run_training_pipeline,
            )
            self._step_results = self._convert_legacy_steps(result.steps)
        except Exception as exc:
            self._failure = exc

    @staticmethod
    def _convert_legacy_steps(legacy_steps: list[Any]) -> dict[ResearchStep, StepResult]:
        converted: dict[ResearchStep, StepResult] = {}
        for legacy_step in legacy_steps:
            step_name = getattr(legacy_step, "name", "")
            canonical = _LEGACY_STEP_MAP.get(step_name)
            if canonical is None:
                continue
            status_value = getattr(getattr(legacy_step, "status", None), "value", None)
            status = _convert_status(str(status_value or "pending"))
            converted[canonical] = StepResult(
                step=canonical,
                status=status,
                output=dict(getattr(legacy_step, "output", {}) or {}),
                error=getattr(legacy_step, "error", None),
                started_at=getattr(legacy_step, "started_at", None),
                completed_at=getattr(legacy_step, "completed_at", None),
            )
        return converted


def _convert_status(status: str) -> WorkflowStatus:
    try:
        return WorkflowStatus(status)
    except ValueError:
        return WorkflowStatus.PENDING
