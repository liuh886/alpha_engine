"""Contract tests for Research Pipeline steps.

Each test verifies a single pipeline step in isolation,
mocking external dependencies (Qlib, MLflow, etc.).
"""

import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


class TestPipelineStepContracts:
    """Test each pipeline step independently."""

    def test_factor_scan_returns_active_factors(self, tmp_path):
        """Step 1: Factor scan should return list of active factors."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test")

        with run.step("factor_scan", {"market": "cn"}) as step:
            from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

            registry = FactorRegistry(db_path=str(tmp_path / "factor_registry.db"))
            active = registry.list_factors(stage=STAGE_ACTIVE)
            step.output = {
                "active_factors": len(active),
                "factor_names": [f["name"] for f in active[:10]],
            }

        assert run.steps[-1].status == StepStatus.COMPLETED
        assert "active_factors" in run.steps[-1].output

    def test_compile_loads_existing_config(self):
        """Step 2: Compile should load existing config without error."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test")

        with run.step("compile", {"market": "cn", "model_type": "lgbm"}) as step:
            config_path = ROOT / "configs" / "cn_lgbm_workflow.yaml"
            assert config_path.exists(), f"Config not found: {config_path}"
            step.output = {"config_path": str(config_path)}

        assert run.steps[-1].status == StepStatus.COMPLETED

    def test_step_failure_records_error(self):
        """Failed steps should record error message."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test")

        with pytest.raises(ValueError, match="test error"):
            with run.step("failing_step"):
                raise ValueError("test error")

        assert run.steps[-1].status == StepStatus.FAILED
        assert "test error" in run.steps[-1].error

    def test_step_timing_is_recorded(self):
        """Steps should record start/end times."""
        from src.research.pipeline import ResearchRun

        run = ResearchRun(market="cn", goal="test")

        with run.step("timed_step") as step:
            step.output = {"result": "ok"}

        assert run.steps[-1].started_at is not None
        assert run.steps[-1].completed_at is not None
        assert run.steps[-1].duration_seconds >= 0

    def test_run_save_and_load_roundtrip(self, tmp_path):
        """Run should be saveable and loadable."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test roundtrip")
        run.start()
        with run.step("step1") as step:
            step.output = {"data": 42}
        run.complete(recommendation="test recommendation")

        # Save
        save_path = tmp_path / "test_run.json"
        run.save(save_path)

        # Load
        loaded = ResearchRun.load(save_path)
        assert loaded.run_id == run.run_id
        assert loaded.market == "cn"
        assert loaded.goal == "test roundtrip"
        assert loaded.status == StepStatus.COMPLETED
        assert loaded.recommendation == "test recommendation"
        assert len(loaded.steps) == 1
        assert loaded.steps[0].output == {"data": 42}

    def test_run_summary_format(self):
        """Run summary should have all required fields."""
        from src.research.pipeline import ResearchRun

        run = ResearchRun(market="cn", goal="test summary")
        run.start()
        with run.step("step1") as step:
            step.output = {}
        run.complete()

        summary = run.get_summary()
        required_fields = [
            "run_id",
            "market",
            "goal",
            "status",
            "recommendation",
            "created_at",
            "completed_at",
            "total_duration_seconds",
            "steps",
            "n_steps",
            "n_completed",
            "n_failed",
        ]
        for field in required_fields:
            assert field in summary, f"Missing field: {field}"

    def test_pipeline_uses_existing_run(self):
        """Pipeline should accept and use existing run."""
        # Verify the function accepts existing_run parameter
        import inspect

        from src.research.pipeline import run_research_pipeline

        sig = inspect.signature(run_research_pipeline)
        assert "existing_run" in sig.parameters, "run_research_pipeline must accept existing_run"
        # Verify it has a default of None (optional)
        assert sig.parameters["existing_run"].default is None

    def test_pipeline_step_sequence(self):
        """Pipeline should execute steps in defined order."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test sequence")
        run.start()

        step_names = [
            "factor_scan",
            "compile",
            "train",
            "validate",
            "backtest",
            "attribution",
            "report",
        ]
        for name in step_names:
            with run.step(name) as step:
                step.output = {"status": "ok"}

        assert len(run.steps) == 7
        for i, name in enumerate(step_names):
            assert run.steps[i].name == name
            assert run.steps[i].status == StepStatus.COMPLETED

    def test_run_complete_sets_timestamps(self):
        """Completing a run should set completed_at and total_duration."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="test timestamps")
        run.start()
        with run.step("step1") as step:
            step.output = {}
        run.complete()

        assert run.completed_at is not None
        assert run.total_duration >= 0
        assert run.status == StepStatus.COMPLETED

    def test_step_output_persists_in_summary(self):
        """Step outputs should be included in run summary."""
        from src.research.pipeline import ResearchRun

        run = ResearchRun(market="cn", goal="test output persistence")
        run.start()
        with run.step("analysis") as step:
            step.output = {"ic": 0.05, "sharpe": 1.2, "n_stocks": 50}
        run.complete()

        summary = run.get_summary()
        assert len(summary["steps"]) == 1
        assert summary["steps"][0]["output"]["ic"] == 0.05
        assert summary["steps"][0]["output"]["sharpe"] == 1.2


def test_market_all_propagates_exact_snapshot_identity_to_each_child(monkeypatch):
    import src.workflows.hooks as hooks

    child_snapshots = []

    class FakeEnvironment:
        def __init__(self, project_root):
            pass

        def run_in_isolation(self, module, args):
            child_snapshots.append(os.environ.get("ALPHA_DATA_SNAPSHOT_ID"))

    monkeypatch.setattr(hooks, "GovernanceService", lambda root: object())
    monkeypatch.setattr(hooks, "ResearchService", lambda root: object())
    monkeypatch.setattr(hooks, "EnvironmentManager", FakeEnvironment)
    monkeypatch.setattr(hooks, "ArtifactRefreshService", lambda **kwargs: object())
    monkeypatch.setattr(hooks, "on_pipeline_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(hooks, "on_pipeline_success", lambda *args, **kwargs: None)

    result = hooks.run_training_pipeline(
        market="all",
        model_type="lgbm",
        tag="snapshot-propagation",
        snapshot_id="content-addressed-snapshot",
        max_retries=0,
    )

    assert child_snapshots == ["content-addressed-snapshot", "content-addressed-snapshot"]
    assert result["snapshot_id"] == "content-addressed-snapshot"


def test_research_service_success_emits_exactly_one_model_artifact(tmp_path, monkeypatch):
    import qlib.utils

    import src.research.service as service_module

    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"model")
    predictions = pd.DataFrame({"f0": [1.0], "score": [0.5]})
    labels = pd.DataFrame({"label": [0.1]})
    recorder = SimpleNamespace(
        id="run-1",
        list_metrics=lambda: {"annualized_return": 0.12, "max_drawdown": -0.08},
    )
    fake_r = SimpleNamespace(
        start=lambda **kwargs: nullcontext(),
        get_recorder=lambda: recorder,
    )
    created = []

    def fake_create_artifact(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="artifact-1", config=kwargs["config"])

    monkeypatch.setattr(service_module, "R", fake_r)
    monkeypatch.setattr(
        service_module,
        "train_model",
        lambda *args, **kwargs: (SimpleNamespace(), model_path),
    )
    monkeypatch.setattr(qlib.utils, "init_instance_by_config", lambda config: object())
    monkeypatch.setattr(
        service_module,
        "run_backtest",
        lambda *args, **kwargs: (predictions, labels),
    )
    monkeypatch.setattr(service_module, "create_artifact", fake_create_artifact, raising=False)

    # Mock validate_inference since we patched create_artifact
    from src.models.reconstruction import InferenceResult

    def fake_validate_inference(artifact_id, **kwargs):
        return InferenceResult(artifact_id=artifact_id, passed=True, n_samples=50, n_predictions=50)

    monkeypatch.setattr(
        service_module, "validate_inference", fake_validate_inference, raising=False
    )

    config = {
        "market": "us",
        "benchmark": "QQQ",
        "task": {
            "model": {"class": "LGBModel", "kwargs": {"seed": 7}},
            "dataset": {
                "kwargs": {
                    "segments": {
                        "train": ["2021-01-01", "2024-12-31"],
                        "valid": ["2025-01-01", "2025-06-30"],
                        "test": ["2025-07-01", "2026-01-01"],
                    }
                }
            },
        },
        "port_analysis_config": {},
    }
    binding = {
        "snapshot_id": "snapshot-1",
        "provider_uri": str(tmp_path / "snapshots" / "snapshot-1"),
    }

    result = service_module.ResearchService(project_root=tmp_path).run_training_pipeline(
        "us",
        config,
        "artifact-test",
        snapshot_id="snapshot-1",
        snapshot_binding=binding,
    )

    assert len(created) == 1
    assert created[0]["snapshot_id"] == "snapshot-1"
    assert created[0]["provider_uri"] == binding["provider_uri"]
    assert created[0]["predictions"] is predictions
    assert created[0]["labels"] is labels
    assert result["artifact_id"] == "artifact-1"
    assert "inference_result" in result
    assert result["inference_result"].passed is True


def test_failed_model_gates_are_research_candidates_not_operational_success():
    from src.workflows.hooks import _pipeline_gate_outcome

    outcome = _pipeline_gate_outcome(
        {
            "gate_passed": False,
            "gate_failures": ["ICIR below threshold"],
        }
    )

    assert outcome["status"] == "RESEARCH_CANDIDATE"
    assert outcome["operational_success"] is False
    assert outcome["promoted"] is False
