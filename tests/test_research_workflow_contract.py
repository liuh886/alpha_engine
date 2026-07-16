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


def _promotion_payload(subject_id, *, status="missing_evidence"):
    return {
        "schema_version": "1.0",
        "subject_id": subject_id,
        "status": status,
        "trade_ready": False,
        "evidence_refs": [],
    }


class RecordingExecutor:
    def __init__(self) -> None:
        self.steps: list[ResearchStep] = []

    def run_step(self, request: ResearchWorkflowRequest, step: ResearchStep) -> StepResult:
        self.steps.append(step)
        now = utc_now()
        output = {"market": request.market, "step": step.value}
        if step is ResearchStep.PROMOTE:
            output = _promotion_payload(request.run_id)
        return StepResult(
            step=step,
            status=WorkflowStatus.COMPLETED,
            output=output,
            started_at=now,
            completed_at=now,
        )


class PromotionOutputExecutor(RecordingExecutor):
    def __init__(self, output):
        super().__init__()
        self.output = output

    def run_step(self, request, step):
        result = super().run_step(request, step)
        if step is ResearchStep.PROMOTE:
            result.output = dict(self.output)
        return result


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


def test_placeholder_workflow_is_skipped_not_completed(tmp_path):
    workflow = ResearchWorkflow(store=ResearchWorkflowStore(artifacts_dir=tmp_path))

    result = workflow.run(ResearchWorkflowRequest(run_id="rw_placeholder"))

    assert result.status == WorkflowStatus.SKIPPED


def test_promotion_subject_may_match_recorded_experiment_id(tmp_path):
    class ExperimentExecutor(RecordingExecutor):
        def run_step(self, request, step):
            result = super().run_step(request, step)
            if step is ResearchStep.PROMOTE:
                result.output = _promotion_payload("declared_experiment")
            else:
                result.output["experiment_id"] = "declared_experiment"
            return result

    workflow = ResearchWorkflow(
        executor=ExperimentExecutor(),
        store=ResearchWorkflowStore(artifacts_dir=tmp_path),
    )
    result = workflow.run(ResearchWorkflowRequest(run_id="rw_experiment_subject"))

    assert result.status == WorkflowStatus.COMPLETED
    assert result.promotion_decision["subject_id"] == "declared_experiment"


def test_unrelated_promotion_subject_fails_closed(tmp_path):
    workflow = ResearchWorkflow(
        executor=PromotionOutputExecutor(_promotion_payload("other_experiment")),
        store=ResearchWorkflowStore(artifacts_dir=tmp_path),
    )

    result = workflow.run(ResearchWorkflowRequest(run_id="rw_subject_mismatch"))

    assert result.status == WorkflowStatus.FAILED
    assert result.promotion_decision is None


# ---------------------------------------------------------------------------
# Slice 1: LegacyResearchPipelineExecutor contract tests
# ---------------------------------------------------------------------------


class TestLegacyPipelineExecutor:
    """Tests that workflow_legacy properly bridges research core → hooks."""

    def test_executor_converts_legacy_steps_to_canonical(self):
        """Injected legacy output is converted once without real model/data code."""
        from types import SimpleNamespace

        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        calls = []

        def training_runner(**kwargs):
            return {}

        def pipeline_runner(**kwargs):
            calls.append(kwargs)
            run = kwargs["existing_run"]
            run.steps = [
                SimpleNamespace(
                    name=name,
                    status=SimpleNamespace(value="completed"),
                    output={"name": name},
                    error=None,
                    started_at="start",
                    completed_at="end",
                )
                for name in (
                    "factor_scan",
                    "compile",
                    "train",
                    "walk_forward",
                    "backtest",
                    "attribution",
                    "promote",
                )
            ]
            return run

        executor = LegacyResearchPipelineExecutor(
            pipeline_runner=pipeline_runner,
            training_runner=training_runner,
        )
        request = ResearchWorkflowRequest(
            market="cn",
            goal="legacy contract",
            model_type="lgbm",
            run_id="legacy_1",
        )

        results = [executor.run_step(request, step) for step in CANONICAL_RESEARCH_STEPS]

        assert [result.step for result in results] == list(CANONICAL_RESEARCH_STEPS)
        assert all(result.status == WorkflowStatus.COMPLETED for result in results)
        assert len(calls) == 1
        assert calls[0]["_train_fn"] is training_runner

    def test_executor_returns_skipped_for_unknown_step(self):
        """Steps not emitted by legacy pipeline should return SKIPPED."""
        from types import SimpleNamespace

        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        def pipeline_runner(**kwargs):
            run = kwargs["existing_run"]
            run.steps = [
                SimpleNamespace(
                    name="factor_scan",
                    status=SimpleNamespace(value="completed"),
                    output={},
                    error=None,
                    started_at=None,
                    completed_at=None,
                )
            ]
            return run

        executor = LegacyResearchPipelineExecutor(
            pipeline_runner=pipeline_runner,
            training_runner=lambda **kwargs: {},
        )
        request = ResearchWorkflowRequest(market="cn", goal="test")

        result = executor.run_step(request, ResearchStep.PROMOTE)
        assert result.step == ResearchStep.PROMOTE
        assert result.status == WorkflowStatus.SKIPPED

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

# ---------------------------------------------------------------------------
# Promotion decision integration tests
# ---------------------------------------------------------------------------


def test_invalid_legacy_payload_fails_closed_in_workflow(tmp_path):
    """A PROMOTE step output like {recommendation: DEPLOY} must not be stored
    as promotion_decision — it fails validation and the result stays None."""
    workflow = ResearchWorkflow(
        executor=PromotionOutputExecutor({"recommendation": "DEPLOY"}),
        store=ResearchWorkflowStore(artifacts_dir=tmp_path),
    )
    result = workflow.run(
        ResearchWorkflowRequest(run_id="rw_legacy_payload", requested_by="test")
    )

    assert result.status == WorkflowStatus.FAILED
    assert result.promotion_decision is None
    assert result.steps[-1].status == WorkflowStatus.FAILED
    assert any("DEPLOY" in w for w in result.warnings)


def test_canonical_decision_persists_through_store_serialization(tmp_path):
    """A valid PromotionDecision payload must survive store save/load roundtrip."""
    import hashlib

    def sha(v: str) -> str:
        return hashlib.sha256(v.encode()).hexdigest()

    canonical = _promotion_payload(
        "rw_persist", status="stronger_research_candidate"
    )
    canonical.update({
        "candidate": {"candidate": "lgbm:test", "mean_icir": 0.25},
        "failed_gates": ["mean_icir"],
        "missing_evidence": [],
        "evidence_refs": [
            {"name": "execution_identity", "path": "execution_identity.json", "sha256": sha("id")},
            {"name": "data_readiness", "path": "data_readiness.json", "sha256": sha("dr")},
            {"name": "walk_forward_stability", "path": "walk_forward_stability.json", "sha256": sha("wf")},
        ],
        "contract_sha256": sha("contract"),
        "thresholds": {"min_mean_icir": 0.30},
        "rationale": "Persist test.",
    })

    store = ResearchWorkflowStore(artifacts_dir=tmp_path)
    workflow = ResearchWorkflow(executor=PromotionOutputExecutor(canonical), store=store)
    result = workflow.run(
        ResearchWorkflowRequest(run_id="rw_persist", requested_by="test")
    )

    assert result.promotion_decision is not None
    assert result.promotion_decision["status"] == "stronger_research_candidate"
    assert result.promotion_decision["trade_ready"] is False

    # Save/load roundtrip
    loaded = workflow.load("rw_persist")
    assert loaded.promotion_decision is not None
    assert loaded.promotion_decision["status"] == "stronger_research_candidate"
    assert loaded.promotion_decision["evidence_refs"] == canonical["evidence_refs"]


def test_backward_compatible_loading_without_promotion_decision(tmp_path):
    """Loading an older stored result without promotion_decision must return None."""
    store = ResearchWorkflowStore(artifacts_dir=tmp_path)
    store.runs_dir.mkdir(parents=True, exist_ok=True)

    old_data = {
        "run_id": "rw_old",
        "request": {
            "market": "cn",
            "goal": "old run",
            "model_type": "lgbm",
            "run_id": "rw_old",
            "requested_by": "test",
            "metadata": {},
        },
        "status": "completed",
        "steps": [],
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:01:00+00:00",
        "evidence_bundle_id": None,
        "warnings": [],
    }
    (store.runs_dir / "rw_old.json").write_text(json.dumps(old_data), encoding="utf-8")

    loaded = store.load("rw_old")
    assert loaded.run_id == "rw_old"
    assert loaded.promotion_decision is None
