"""Contract tests for SpecBoundResearchWorkflowExecutor — Qlib/data-free."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.common.runtime_settings import PROJECT_ROOT
from src.research.spec_bound_workflow_executor import (
    SpecBoundResearchWorkflowExecutor,
    resolve_spec,
)
from src.research.workflow import ResearchWorkflow
from src.research.workflow_runtime import (
    create_legacy_research_workflow,
    create_research_workflow,
)
from src.research.workflow_store import ResearchWorkflowStore
from src.research.workflow_types import (
    CANONICAL_RESEARCH_STEPS,
    ResearchStep,
    ResearchWorkflowRequest,
    StepResult,
    WorkflowStatus,
    utc_now,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SPEC_DIR = PROJECT_ROOT / "configs" / "research_paradigms"


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _canned_spec_result(
    *,
    status: str = "passed",
    promotion_status: str = "missing_evidence",
    experiment_id: str = "",
    market: str = "cn",
    spec_path: str = "",
) -> dict[str, Any]:
    """Return a minimal valid spec-bound result dict for injection."""
    resolved_experiment_id = experiment_id or {
        "cn": "cn_10d_csi300_baseline",
        "us": "us_10d_qqq_baseline",
    }.get(market, f"{market}_test")
    return {
        "status": status,
        "run_dir": f"artifacts/research_runs/{resolved_experiment_id}",
        "contract_identity_verified": True,
        "declared_contract_sha256": _sha(f"contract-{market}"),
        "effective_contract_sha256": _sha(f"contract-{market}"),
        "runtime_metadata": {},
        "evidence_paths": {
            "execution_identity": "execution_identity.json",
            "data_readiness": "data_readiness.json",
            "walk_forward_stability": "walk_forward_stability.json",
            "metrics_summary": "metrics_summary.json",
            "model_decision_pack": "model_decision_pack.json",
        },
        "promotion_decision": {
            "schema_version": "1.0",
            "subject_id": resolved_experiment_id,
            "status": promotion_status,
            "trade_ready": promotion_status == "trade_guidance_candidate",
            "candidate": None,
            "failed_gates": [],
            "missing_evidence": [],
            "evidence_refs": [],
            "contract_sha256": _sha(f"contract-{market}"),
            "thresholds": {"min_mean_icir": 0.30},
            "rationale": "Contract test.",
            "research_only_warning": (
                "Promotion status is research evidence, not authorization "
                "for live or automated trading."
            ),
        },
    }


class FakeSpecBoundRunner:
    """Records calls and returns a canned spec-bound result."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[Any] = []  # list of ResearchParadigmSpec
        self.result = result or _canned_spec_result()

    def __call__(self, spec: Any) -> dict[str, Any]:
        self.calls.append(spec)
        return dict(self.result)


def _run_workflow(
    tmp_path: Path,
    *,
    market: str = "cn",
    goal: str = "audit only",
    spec_bound_runner: Any = None,
    metadata: dict[str, Any] | None = None,
) -> ResearchWorkflow:
    """Convenience: create and run a workflow in one call."""
    executor = SpecBoundResearchWorkflowExecutor(
        spec_bound_runner=spec_bound_runner
    )
    store = ResearchWorkflowStore(artifacts_dir=tmp_path)
    wf = ResearchWorkflow(executor=executor, store=store)
    wf.run(
        ResearchWorkflowRequest(
            market=market,
            goal=goal,
            model_type="lgbm",
            run_id=f"rw_test_{market}",
            requested_by="test",
            metadata=metadata or {},
        )
    )
    return wf


# ---------------------------------------------------------------------------
# Spec resolution
# ---------------------------------------------------------------------------


class TestSpecResolution:
    def test_cn_maps_to_csi300_baseline(self):
        spec = resolve_spec(ResearchWorkflowRequest(market="cn"))
        assert spec.market == "cn"
        assert spec.experiment_id == "cn_10d_csi300_baseline"
        assert "cn_10d_csi300_baseline.yaml" in spec.spec_path

    def test_us_maps_to_qqq_baseline(self):
        spec = resolve_spec(ResearchWorkflowRequest(market="us"))
        assert spec.market == "us"
        assert spec.experiment_id == "us_10d_qqq_baseline"
        assert "us_10d_qqq_baseline.yaml" in spec.spec_path

    def test_unsupported_market_raises(self):
        with pytest.raises(ValueError, match="Unsupported market"):
            resolve_spec(ResearchWorkflowRequest(market="jp"))

    def test_safe_override_with_valid_spec(self):
        spec = resolve_spec(
            ResearchWorkflowRequest(
                market="cn",
                metadata={
                    "spec_path": str(
                        _SPEC_DIR / "cn_10d_csi300_baseline.yaml"
                    )
                },
            )
        )
        assert spec.market == "cn"
        assert "cn_10d_csi300_baseline.yaml" in spec.spec_path

    def test_override_market_mismatch_raises(self):
        """CN request with US spec override must be rejected."""
        with pytest.raises(ValueError, match="does not match request market"):
            resolve_spec(
                ResearchWorkflowRequest(
                    market="cn",
                    metadata={
                        "spec_path": str(
                            _SPEC_DIR / "us_10d_qqq_baseline.yaml"
                        )
                    },
                )
            )

    def test_override_path_traversal_raises(self):
        with pytest.raises(ValueError, match="outside the safe spec directory"):
            resolve_spec(
                ResearchWorkflowRequest(
                    market="cn",
                    metadata={"spec_path": "../../etc/passwd"},
                )
            )

    def test_override_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            resolve_spec(
                ResearchWorkflowRequest(
                    market="cn",
                    metadata={
                        "spec_path": str(
                            _SPEC_DIR / "nonexistent.yaml"
                        )
                    },
                )
            )


# ---------------------------------------------------------------------------
# Workflow integration (Qlib/data-free via injected runner)
# ---------------------------------------------------------------------------


class TestSpecBoundWorkflowIntegration:
    def test_single_invocation_of_spec_bound_runner(self, tmp_path):
        """The spec-bound runner must be called exactly once for the full
        canonical step sequence."""
        runner = FakeSpecBoundRunner()
        _run_workflow(tmp_path, spec_bound_runner=runner)
        assert len(runner.calls) == 1
        assert runner.calls[0].market == "cn"

    def test_evidence_backed_steps_complete_and_attribution_skips(self, tmp_path):
        """Only stages backed by the fixed-10D execution may complete."""
        runner = FakeSpecBoundRunner(_canned_spec_result(status="passed"))
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        step_statuses = {s.step: s.status for s in result.steps}
        for step in CANONICAL_RESEARCH_STEPS:
            assert step in step_statuses, f"Missing step: {step}"
        for step in CANONICAL_RESEARCH_STEPS:
            expected = (
                WorkflowStatus.SKIPPED
                if step is ResearchStep.ATTRIBUTION
                else WorkflowStatus.COMPLETED
            )
            assert step_statuses[step] == expected

        assert result.status == WorkflowStatus.COMPLETED
        json.dumps(result.to_dict())  # serialisable

    def test_promote_carries_canonical_promotion_decision(self, tmp_path):
        """PROMOTE step output must be the exact promotion_decision dict."""
        canned = _canned_spec_result(
            promotion_status="stronger_research_candidate",
            experiment_id="cn_10d_csi300_baseline",
        )
        runner = FakeSpecBoundRunner(canned)
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        promote_step = result.steps[-1]
        assert promote_step.step == ResearchStep.PROMOTE
        assert promote_step.status == WorkflowStatus.COMPLETED
        assert promote_step.output["status"] == "stronger_research_candidate"
        assert promote_step.output["trade_ready"] is False
        assert promote_step.output["subject_id"] == "cn_10d_csi300_baseline"
        # Must not contain legacy fields
        assert "recommendation" not in promote_step.output

    def test_promotion_decision_persists_in_workflow_result(self, tmp_path):
        """The canonical promotion_decision must appear in the top-level result."""
        canned = _canned_spec_result(
            promotion_status="research_candidate",
            experiment_id="cn_10d_csi300_baseline",
        )
        runner = FakeSpecBoundRunner(canned)
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        assert result.promotion_decision is not None
        assert result.promotion_decision["status"] == "research_candidate"
        assert result.promotion_decision["trade_ready"] is False

    def test_promotion_decision_store_roundtrip(self, tmp_path):
        """promotion_decision must survive store save/load roundtrip."""
        canned = _canned_spec_result(
            promotion_status="trade_guidance_candidate",
            experiment_id="cn_10d_csi300_baseline",
        )
        canned["promotion_decision"]["trade_ready"] = True
        runner = FakeSpecBoundRunner(canned)
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)

        result = wf.load("rw_test_cn")
        assert result.promotion_decision is not None
        assert result.promotion_decision["status"] == "trade_guidance_candidate"
        assert result.promotion_decision["trade_ready"] is True

    def test_execution_failure_stops_at_first_failed_step(self, tmp_path):
        """A runner error fails closed without pretending later stages ran."""
        class FailingRunner:
            def __call__(self, spec):
                raise RuntimeError("adapter exploded")

        executor = SpecBoundResearchWorkflowExecutor(
            spec_bound_runner=FailingRunner()
        )
        store = ResearchWorkflowStore(artifacts_dir=tmp_path)
        wf = ResearchWorkflow(executor=executor, store=store)
        result = wf.run(
            ResearchWorkflowRequest(
                market="cn",
                goal="fail test",
                run_id="rw_fail",
                requested_by="test",
            )
        )

        assert result.status == WorkflowStatus.FAILED
        assert len(result.steps) == 1
        assert result.steps[0].step is ResearchStep.SCAN
        assert result.steps[0].status == WorkflowStatus.FAILED
        assert "adapter exploded" in (result.steps[0].error or "")

    def test_goal_is_audit_metadata_only(self, tmp_path):
        """Goal text must NOT change which spec is executed."""
        runner = FakeSpecBoundRunner()
        _run_workflow(
            tmp_path,
            goal="Find momentum alpha in tech stocks",
            spec_bound_runner=runner,
        )
        # The executed spec must be the fixed CN baseline regardless of goal
        assert runner.calls[0].experiment_id == "cn_10d_csi300_baseline"

        # Step outputs must declare that goal is audit-only
        result = ResearchWorkflowStore(artifacts_dir=tmp_path).load(
            "rw_test_cn"
        )
        for step_result in result.steps:
            if step_result.step is not ResearchStep.PROMOTE:
                assert step_result.output["requested_goal"] == (
                    "Find momentum alpha in tech stocks"
                )
                assert step_result.output["goal_semantics"] == "audit_metadata_only"

    def test_step_outputs_contain_spec_identity(self, tmp_path):
        """Every non-PROMOTE step output must record resolved spec identity."""
        runner = FakeSpecBoundRunner(
            _canned_spec_result(experiment_id="cn_10d_csi300_baseline", market="cn")
        )
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        for step_result in result.steps:
            if step_result.step is ResearchStep.PROMOTE:
                continue
            out = step_result.output
            assert out.get("experiment_id") == "cn_10d_csi300_baseline"
            assert out.get("market") == "cn"
            assert "cn_10d_csi300_baseline.yaml" in str(
                out.get("resolved_spec_path", "")
            )

    def test_step_outputs_reference_evidence_paths(self, tmp_path):
        """Completed evidence stages must reference returned artifacts."""
        runner = FakeSpecBoundRunner()
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        outputs_by_step = {s.step: s.output for s in result.steps}

        train_out = outputs_by_step.get(ResearchStep.TRAIN, {})
        assert train_out.get("execution_identity")

        wf_out = outputs_by_step.get(ResearchStep.WALK_FORWARD, {})
        assert wf_out.get("walk_forward_evidence")

        bt_out = outputs_by_step.get(ResearchStep.BACKTEST, {})
        assert bt_out.get("metrics_summary")

        attribution = next(
            step for step in result.steps if step.step is ResearchStep.ATTRIBUTION
        )
        assert attribution.status == WorkflowStatus.SKIPPED
        assert "does not produce" in attribution.output["reason"]

    def test_skipped_execution_is_not_reported_completed(self, tmp_path):
        canned = _canned_spec_result(status="skipped")
        canned["skip_reason"] = "market data unavailable"
        wf = _run_workflow(
            tmp_path,
            spec_bound_runner=FakeSpecBoundRunner(canned),
        )
        result = wf.load("rw_test_cn")

        assert result.status == WorkflowStatus.SKIPPED
        assert result.promotion_decision is None
        assert all(step.status == WorkflowStatus.SKIPPED for step in result.steps)
        assert all(
            step.output["reason"] == "market data unavailable"
            for step in result.steps
        )

    def test_missing_required_evidence_fails_at_owning_step(self, tmp_path):
        canned = _canned_spec_result()
        canned["evidence_paths"]["walk_forward_stability"] = ""
        wf = _run_workflow(
            tmp_path,
            spec_bound_runner=FakeSpecBoundRunner(canned),
        )
        result = wf.load("rw_test_cn")

        assert result.status == WorkflowStatus.FAILED
        assert result.steps[-1].step is ResearchStep.WALK_FORWARD
        assert "walk_forward_evidence" in (result.steps[-1].error or "")

    def test_unproven_contract_identity_fails_closed(self, tmp_path):
        canned = _canned_spec_result()
        canned["contract_identity_verified"] = False
        wf = _run_workflow(
            tmp_path,
            spec_bound_runner=FakeSpecBoundRunner(canned),
        )
        result = wf.load("rw_test_cn")

        assert result.status == WorkflowStatus.FAILED
        assert result.steps[0].step is ResearchStep.SCAN
        assert "contract identity" in (result.steps[0].error or "")

    def test_same_executor_reexecutes_for_a_new_workflow_run(self, tmp_path):
        runner = FakeSpecBoundRunner()
        executor = SpecBoundResearchWorkflowExecutor(spec_bound_runner=runner)
        workflow = ResearchWorkflow(
            executor=executor,
            store=ResearchWorkflowStore(artifacts_dir=tmp_path),
        )

        for run_id in ("rw_first", "rw_second"):
            result = workflow.run(
                ResearchWorkflowRequest(
                    market="cn",
                    goal=run_id,
                    run_id=run_id,
                    requested_by="test",
                )
            )
            assert result.status == WorkflowStatus.COMPLETED

        assert len(runner.calls) == 2


# ---------------------------------------------------------------------------
# Default factory
# ---------------------------------------------------------------------------


class TestDefaultFactory:
    def test_default_factory_uses_spec_bound_executor(self):
        """create_research_workflow() must NOT use LegacyResearchPipelineExecutor."""
        from src.research.spec_bound_workflow_executor import (
            SpecBoundResearchWorkflowExecutor,
        )

        wf = create_research_workflow()
        assert isinstance(wf.executor, SpecBoundResearchWorkflowExecutor)

    def test_legacy_factory_still_available(self):
        """create_legacy_research_workflow() must return a workflow backed
        by LegacyResearchPipelineExecutor."""
        from src.research.workflow_legacy import LegacyResearchPipelineExecutor

        wf = create_legacy_research_workflow()
        assert isinstance(wf.executor, LegacyResearchPipelineExecutor)

# ---------------------------------------------------------------------------
# CN vs US adapter routing (unit — no Qlib)
# ---------------------------------------------------------------------------


class TestMarketAdapterRouting:
    def test_cn_request_uses_cn_spec(self, tmp_path):
        runner = FakeSpecBoundRunner()
        _run_workflow(tmp_path, market="cn", spec_bound_runner=runner)
        assert runner.calls[0].market == "cn"
        assert runner.calls[0].experiment_id == "cn_10d_csi300_baseline"

    def test_us_request_uses_us_spec(self, tmp_path):
        runner = FakeSpecBoundRunner()
        _run_workflow(tmp_path, market="us", spec_bound_runner=runner)
        assert runner.calls[0].market == "us"
        assert runner.calls[0].experiment_id == "us_10d_qqq_baseline"

    def test_unsupported_market_fails_before_execution(self, tmp_path):
        """An unsupported market must fail in resolve_spec, never reaching
        the spec-bound runner."""
        runner = FakeSpecBoundRunner()
        executor = SpecBoundResearchWorkflowExecutor(
            spec_bound_runner=runner
        )
        store = ResearchWorkflowStore(artifacts_dir=tmp_path)
        wf = ResearchWorkflow(executor=executor, store=store)
        result = wf.run(
            ResearchWorkflowRequest(
                market="eu",
                goal="test",
                run_id="rw_eu",
                requested_by="test",
            )
        )

        assert result.status == WorkflowStatus.FAILED
        assert len(runner.calls) == 0  # never reached execution


# ---------------------------------------------------------------------------
# No-synthesis guard
# ---------------------------------------------------------------------------


class TestNoPromotionSynthesis:
    def test_promote_never_synthesized(self, tmp_path):
        """If spec-bound result lacks promotion_decision, PROMOTE must FAIL,
        not synthesise one from metric hints."""
        canned = _canned_spec_result()
        del canned["promotion_decision"]  # simulate missing decision
        runner = FakeSpecBoundRunner(canned)
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        promote = [s for s in result.steps if s.step == ResearchStep.PROMOTE][0]
        assert promote.status == WorkflowStatus.FAILED
        assert "did not produce" in (promote.error or "")
        assert result.promotion_decision is None

    def test_promote_output_is_exact_promotion_decision(self, tmp_path):
        """PROMOTE output must be the exact dict, not a wrapper."""
        canned = _canned_spec_result(
            promotion_status="rejected",
            experiment_id="cn_10d_csi300_baseline",
        )
        runner = FakeSpecBoundRunner(canned)
        wf = _run_workflow(tmp_path, spec_bound_runner=runner)
        result = wf.load("rw_test_cn")

        promote = [s for s in result.steps if s.step == ResearchStep.PROMOTE][0]
        expected = canned["promotion_decision"]
        assert promote.output == expected
        # Verify exact keys
        assert set(promote.output.keys()) == set(expected.keys())


# ---------------------------------------------------------------------------
# Explicit override workflow integration
# ---------------------------------------------------------------------------


class TestExplicitOverride:
    def test_valid_override_runs_with_correct_spec(self, tmp_path):
        """An explicit safe spec_path override must be used."""
        runner = FakeSpecBoundRunner(_canned_spec_result(market="us"))
        wf = _run_workflow(
            tmp_path,
            market="us",
            spec_bound_runner=runner,
            metadata={
                "spec_path": str(_SPEC_DIR / "us_10d_qqq_baseline.yaml")
            },
        )
        result = wf.load("rw_test_us")
        assert result.status == WorkflowStatus.COMPLETED
        assert runner.calls[0].experiment_id == "us_10d_qqq_baseline"

    def test_override_market_mismatch_fails_workflow(self, tmp_path):
        """Override with a spec whose market != request.market must fail."""
        runner = FakeSpecBoundRunner()
        executor = SpecBoundResearchWorkflowExecutor(
            spec_bound_runner=runner
        )
        store = ResearchWorkflowStore(artifacts_dir=tmp_path)
        wf = ResearchWorkflow(executor=executor, store=store)
        result = wf.run(
            ResearchWorkflowRequest(
                market="cn",
                goal="mismatch test",
                run_id="rw_mismatch",
                requested_by="test",
                metadata={
                    "spec_path": str(_SPEC_DIR / "us_10d_qqq_baseline.yaml")
                },
            )
        )

        assert result.status == WorkflowStatus.FAILED
        assert len(runner.calls) == 0
