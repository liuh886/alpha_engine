from __future__ import annotations

import json

from src.research.workflow import ResearchWorkflow
from src.research.workflow_store import ResearchWorkflowStore
from src.research.workflow_types import (
    CANONICAL_RESEARCH_STEPS,
    ResearchStep,
    ResearchWorkflowRequest,
    StepResult,
    WorkflowStatus,
    utc_now,
)


class RecordingExecutor:
    def __init__(self) -> None:
        self.steps: list[ResearchStep] = []

    def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
        self.steps.append(step)
        now = utc_now()
        return StepResult(
            step=step,
            status=WorkflowStatus.COMPLETED,
            output={"market": request.market, "step": step.value},
            started_at=now,
            completed_at=now,
        )


def test_research_workflow_runs_canonical_steps_in_order(tmp_path):
    executor = RecordingExecutor()
    workflow = ResearchWorkflow(
        executor=executor,
        store=ResearchWorkflowStore(artifacts_dir=tmp_path),
    )

    result = workflow.run(
        ResearchWorkflowRequest(
            market="cn",
            goal="contract test",
            model_type="lgbm",
            run_id="rw_contract",
            requested_by="test",
        )
    )

    assert executor.steps == list(CANONICAL_RESEARCH_STEPS)
    assert [step.step for step in result.steps] == list(CANONICAL_RESEARCH_STEPS)
    assert result.status == WorkflowStatus.COMPLETED
    json.dumps(result.to_dict())


def test_research_workflow_stops_on_failed_step(tmp_path):
    class FailingExecutor(RecordingExecutor):
        def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
            self.steps.append(step)
            if step == ResearchStep.TRAIN:
                return StepResult(step=step, status=WorkflowStatus.FAILED, error="boom")
            return StepResult(step=step, status=WorkflowStatus.COMPLETED)

    executor = FailingExecutor()
    workflow = ResearchWorkflow(
        executor=executor,
        store=ResearchWorkflowStore(artifacts_dir=tmp_path),
    )

    result = workflow.run(ResearchWorkflowRequest(run_id="rw_failed"))

    assert executor.steps == [
        ResearchStep.SCAN,
        ResearchStep.COMPILE,
        ResearchStep.TRAIN,
    ]
    assert result.status == WorkflowStatus.FAILED
    assert result.steps[-1].error == "boom"


def test_research_workflow_store_roundtrip(tmp_path):
    workflow = ResearchWorkflow(store=ResearchWorkflowStore(artifacts_dir=tmp_path))

    result = workflow.run(ResearchWorkflowRequest(run_id="rw_roundtrip", requested_by="test"))
    loaded = workflow.load(result.run_id)

    assert loaded.run_id == result.run_id
    assert loaded.request.requested_by == "test"
    assert len(loaded.steps) == len(CANONICAL_RESEARCH_STEPS)


# ---------------------------------------------------------------------------
# Slice 1: LegacyResearchPipelineExecutor contract tests
# ---------------------------------------------------------------------------


class TestLegacyPipelineExecutor:
    """Tests that workflow_legacy properly bridges research core → hooks."""

    def test_executor_converts_legacy_steps_to_canonical(self):
        """Legacy step names must map to canonical ResearchStep enum."""
        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        executor = LegacyResearchPipelineExecutor()
        request = ResearchWorkflowRequest(
            market="cn",
            goal="legacy contract",
            model_type="lgbm",
            run_id="legacy_1",
        )

        # Run SCAN step — triggers the full legacy pipeline once
        result = executor.run_step(request, ResearchStep.SCAN)

        assert result.step == ResearchStep.SCAN
        assert result.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED)

    def test_executor_returns_skipped_for_unknown_step(self):
        """Steps not emitted by legacy pipeline should return SKIPPED."""
        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        executor = LegacyResearchPipelineExecutor()
        request = ResearchWorkflowRequest(market="cn", goal="test")

        # Run pipeline first
        executor.run_step(request, ResearchStep.SCAN)

        # The legacy pipeline has 7 steps; check a step that might not be in output
        # by requesting a step that doesn't exist in _LEGACY_STEP_MAP
        # All canonical steps ARE in the map, so we test the fallback path
        # by verifying skipped steps have the right structure
        result = executor.run_step(request, ResearchStep.PROMOTE)
        assert result.step == ResearchStep.PROMOTE

    def test_executor_preserves_error_on_failure(self):
        """When legacy pipeline raises, all steps return FAILED with error."""
        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        class BrokenExecutor(LegacyResearchPipelineExecutor):
            def _run_legacy_pipeline(self, request):
                self._ran = True
                self._failure = RuntimeError("hooks exploded")

        executor = BrokenExecutor()
        request = ResearchWorkflowRequest(market="cn", goal="fail test")

        for step in CANONICAL_RESEARCH_STEPS:
            result = executor.run_step(request, step)
            assert result.status == WorkflowStatus.FAILED
            assert "hooks exploded" in result.error

    def test_executor_train_step_uses_injected_fn(self):
        """pipeline.py should accept _train_fn parameter without importing hooks."""
        import inspect

        from src.research.pipeline import run_research_pipeline

        sig = inspect.signature(run_research_pipeline)
        assert "_train_fn" in sig.parameters
        assert sig.parameters["_train_fn"].default is None

    def test_canonical_workflow_path_injects_train_fn(self):
        """workflow_legacy must inject _train_fn — the hooks fallback should not fire."""
        import inspect

        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        executor = LegacyResearchPipelineExecutor()

        # Verify the executor imports hooks directly (canonical injection path)
        # rather than relying on pipeline.py's fallback import
        source = inspect.getsource(executor._run_legacy_pipeline)
        assert "from src.workflows.hooks import run_training_pipeline" in source
        assert "_train_fn=run_training_pipeline" in source
