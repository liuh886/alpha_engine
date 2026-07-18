"""Contract tests for the training pipeline orchestration layer.

These two tests were preserved from the retired test_pipeline_contract.py
(ADR-0007). They exercise ``src.workflows.hooks.run_training_pipeline`` and
``src.research.service.ResearchService.run_training_pipeline`` — the
orchestration layer that survives the legacy pipeline retirement, not the
retired ``ResearchRun``/``Step`` dataclasses from ``src/research/pipeline.py``.
"""

import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


def test_market_all_propagates_exact_snapshot_identity_to_each_child(monkeypatch):
    """When market='all', every child environment receives the same snapshot_id."""
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
    """ResearchService.run_training_pipeline must emit exactly one model artifact
    on a successful training + backtest run, with correct snapshot binding."""
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
