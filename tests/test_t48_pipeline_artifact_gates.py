"""Tests for T48.3 -- pipeline artifact gates and mandatory snapshot_id.

Verifies that:
1. create_artifact raises when snapshot_id is empty
2. validate_inference is called after artifact creation
3. Training pipeline return dict includes inference_result
4. register_artifact is called when walk-forward passes
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.artifact import (
    ArtifactValidationError,
    clear_registry,
    create_artifact,
    set_artifacts_root,
)
from src.models.reconstruction import InferenceResult, ReconstructionResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def artifacts_root(tmp_path):
    set_artifacts_root(tmp_path)
    yield tmp_path
    set_artifacts_root(Path("__reset__"))


class _SyntheticModel:
    def __init__(self, weights=None, bias=0.0):
        self.weights = np.asarray(weights if weights is not None else [1.0, 2.0, 3.0])
        self.bias = float(bias)

    def predict(self, X):
        return np.asarray(X, dtype=np.float64) @ self.weights + self.bias


@pytest.fixture
def model_dir(tmp_path):
    d = tmp_path / "model_output"
    d.mkdir()
    model = _SyntheticModel()
    with open(d / "model.pkl", "wb") as f:
        pickle.dump(model, f)
    return d


@pytest.fixture
def sample_config():
    return {
        "market": "us",
        "benchmark": "QQQ",
        "port_analysis_config": {},
        "task": {
            "model": {"class": "LGBModel", "kwargs": {"seed": 42}},
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {
                            "data_loader": {
                                "kwargs": {
                                    "config": {
                                        "feature": ["f0", "f1", "f2"],
                                        "label": ["Ref($close, -5)/$close - 1"],
                                    }
                                }
                            }
                        }
                    },
                    "segments": {
                        "train": ["2021-01-01", "2024-12-31"],
                        "valid": ["2025-01-01", "2025-06-30"],
                        "test": ["2025-07-01", "2026-01-01"],
                    },
                }
            },
        },
    }


@pytest.fixture
def sample_predictions():
    model = _SyntheticModel()
    rng = np.random.RandomState(99)
    X = rng.randn(30, 3)
    preds = model.predict(X)
    dates = pd.date_range("2025-01-02", periods=10, freq="B")
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product([dates, instruments], names=["date", "instrument"])
    feat_df = pd.DataFrame(X, index=idx, columns=["f0", "f1", "f2"])
    feat_df["score"] = preds
    return feat_df


@pytest.fixture
def sample_labels():
    dates = pd.date_range("2025-01-02", periods=10, freq="B")
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product([dates, instruments], names=["date", "instrument"])
    return pd.DataFrame({"label": [0.01] * len(idx)}, index=idx)


# ---------------------------------------------------------------------------
# Test 1: snapshot_id is mandatory
# ---------------------------------------------------------------------------


class TestSnapshotIdMandatory:
    """create_artifact must raise when snapshot_id is empty or None."""

    def test_raises_on_empty_string(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        with pytest.raises(ArtifactValidationError, match="snapshot_id is required"):
            create_artifact(
                model_dir=model_dir,
                config=sample_config,
                predictions=sample_predictions,
                labels=sample_labels,
                snapshot_id="",
            )

    def test_raises_on_none(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        with pytest.raises(ArtifactValidationError, match="snapshot_id is required"):
            create_artifact(
                model_dir=model_dir,
                config=sample_config,
                predictions=sample_predictions,
                labels=sample_labels,
                snapshot_id=None,
            )

    def test_accepts_valid_snapshot_id(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="snap_20260101",
        )
        assert manifest.snapshot_id == "snap_20260101"


# ---------------------------------------------------------------------------
# Test 2: validate_inference is wired after create_artifact
# ---------------------------------------------------------------------------


class TestValidateInferenceInPipeline:
    """validate_inference must be called after create_artifact in service.py."""

    def test_service_calls_validate_inference(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Mock validate_inference and verify it's called with the artifact id."""
        mock_inference_result = InferenceResult(
            artifact_id="test_artifact",
            passed=True,
            n_samples=50,
            n_predictions=50,
        )

        with (
            patch(
                "src.research.service.validate_inference", return_value=mock_inference_result
            ) as mock_vi,
            patch("src.research.service.R") as mock_R,
            patch("src.research.service.train_model") as mock_train,
            patch("src.research.service.run_backtest") as mock_backtest,
            patch("qlib.utils.init_instance_by_config") as mock_init,
        ):
            # Setup mocks
            mock_recorder = MagicMock()
            mock_recorder.id = "test_run_id"
            mock_recorder.list_metrics.return_value = {
                "excess_return_with_cost_120_120-annualized_return": 0.12,
                "excess_return_with_cost_120_120-max_drawdown": -0.08,
                "excess_return_without_cost_120_120-information_ratio": 1.5,
            }
            mock_R.start.return_value.__enter__ = MagicMock(return_value=None)
            mock_R.start.return_value.__exit__ = MagicMock(return_value=False)
            mock_R.get_recorder.return_value = mock_recorder

            mock_train.return_value = (MagicMock(), model_dir)
            mock_backtest.return_value = (sample_predictions, sample_labels)
            mock_init.return_value = MagicMock()

            from src.research.service import ResearchService

            svc = ResearchService(project_root=ROOT)
            svc.run_training_pipeline(
                market="us",
                config=sample_config,
                tag="test",
                snapshot_id="snap_test",
                snapshot_binding={
                    "snapshot_id": "snap_test",
                    "provider_uri": str(artifacts_root),
                },
            )

            # validate_inference must have been called
            mock_vi.assert_called_once()
            call_args = mock_vi.call_args
            # First positional arg is the artifact_id
            assert call_args[0][0]  # artifact_id is non-empty
            assert call_args[1].get("n_samples") == 50 or call_args[0][1] == 50


# ---------------------------------------------------------------------------
# Test 3: Training pipeline return dict includes inference_result
# ---------------------------------------------------------------------------


class TestPipelineReturnDict:
    """The training pipeline must include inference_result in its return dict."""

    def test_return_dict_has_inference_result(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        mock_inference_result = InferenceResult(
            artifact_id="test_artifact",
            passed=True,
            n_samples=50,
            n_predictions=50,
        )

        with (
            patch("src.research.service.validate_inference", return_value=mock_inference_result),
            patch("src.research.service.R") as mock_R,
            patch("src.research.service.train_model") as mock_train,
            patch("src.research.service.run_backtest") as mock_backtest,
            patch("qlib.utils.init_instance_by_config") as mock_init,
        ):
            mock_recorder = MagicMock()
            mock_recorder.id = "test_run_id"
            mock_recorder.list_metrics.return_value = {
                "excess_return_with_cost_120_120-annualized_return": 0.12,
                "excess_return_with_cost_120_120-max_drawdown": -0.08,
                "excess_return_without_cost_120_120-information_ratio": 1.5,
            }
            mock_R.start.return_value.__enter__ = MagicMock(return_value=None)
            mock_R.start.return_value.__exit__ = MagicMock(return_value=False)
            mock_R.get_recorder.return_value = mock_recorder

            mock_train.return_value = (MagicMock(), model_dir)
            mock_backtest.return_value = (sample_predictions, sample_labels)
            mock_init.return_value = MagicMock()

            from src.research.service import ResearchService

            svc = ResearchService(project_root=ROOT)
            result = svc.run_training_pipeline(
                market="us",
                config=sample_config,
                tag="test",
                snapshot_id="snap_test",
                snapshot_binding={
                    "snapshot_id": "snap_test",
                    "provider_uri": str(artifacts_root),
                },
            )

            assert "inference_result" in result
            assert result["inference_result"].passed is True
            assert result["inference_result"].n_samples == 50


# ---------------------------------------------------------------------------
# Test 4: register_artifact is called when walk-forward passes
# ---------------------------------------------------------------------------


class TestRegisterArtifactInHooks:
    """register_artifact must be called when walk-forward validation passes."""

    def test_register_artifact_called_on_wf_pass(self, tmp_path, monkeypatch):
        """When walk-forward passes, hooks should call register_artifact."""
        from dataclasses import dataclass

        @dataclass
        class FakeWfResult:
            mean_ic: float = 0.05
            std_ic: float = 0.02
            ic_ir: float = 0.5
            consistency_score: float = 0.7
            n_splits: int = 3
            splits: list = None

            def __post_init__(self):
                if self.splits is None:
                    self.splits = [1, 2, 3]

        mock_wf_result = FakeWfResult()

        mock_inference = InferenceResult(
            artifact_id="abc", passed=True, n_samples=50, n_predictions=50
        )
        mock_reconstruction = ReconstructionResult(
            artifact_id="abc", passed=True, status="passed", clean_process=True
        )

        monkeypatch.setattr("src.workflows.hooks.ARTIFACTS_DIR", tmp_path)

        with (
            patch("src.workflows.hooks.walk_forward_validate", return_value=mock_wf_result),
            patch("src.workflows.hooks.register_model"),
            patch("src.workflows.hooks.register_artifact") as mock_ra,
            patch("src.workflows.hooks.validate_inference", return_value=mock_inference),
            patch(
                "src.workflows.hooks._run_clean_reconstruction", return_value=mock_reconstruction
            ),
            patch("src.workflows.hooks.ResearchService") as mock_rs_cls,
            patch("src.workflows.hooks.GovernanceService"),
            patch("src.workflows.hooks.EnvironmentManager"),
            patch("src.workflows.hooks.ArtifactRefreshService"),
            patch("src.workflows.hooks.compile_strategy_profile"),
            patch("src.workflows.hooks.generate_quality_report"),
            patch("src.workflows.hooks._publish_pipeline_result", side_effect=lambda x: x),
        ):
            mock_rs = MagicMock()
            mock_rs_cls.return_value = mock_rs
            mock_rs.resolve_snapshot_binding.return_value = {
                "snapshot_id": "snap_123",
                "provider_uri": "/tmp/data",
            }
            mock_rs.bind_config_to_snapshot.return_value = {
                "task": {
                    "model": {},
                    "dataset": {
                        "kwargs": {
                            "handler": {"kwargs": {"start_time": "2021-01-01"}},
                            "segments": {
                                "train": ["2021-01-01", "2024-12-31"],
                            },
                        }
                    },
                },
                "port_analysis_config": {},
                "qlib_init": {},
            }
            mock_rs.prepare_experiment.return_value = mock_rs.bind_config_to_snapshot.return_value

            manifest = MagicMock()
            manifest.id = "abc"
            manifest.config = {"market": "us"}

            mock_rs.run_training_pipeline.return_value = {
                "model_path": Path("/tmp/model.pkl"),
                "run_id": "run_123",
                "model": MagicMock(),
                "dataset": MagicMock(),
                "pred": pd.DataFrame(),
                "label": pd.DataFrame(),
                "metrics": {},
                "artifact_id": "abc",
                "artifact": manifest,
                "inference_result": mock_inference,
                "snapshot_id": "snap_123",
                "provider_uri": "/tmp/data",
            }

            from src.workflows.hooks import run_training_pipeline

            run_training_pipeline(
                market="us",
                model_type="lgbm",
                tag="test_v1",
                snapshot_id="snap_123",
            )

            # register_artifact should have been called
            mock_ra.assert_called_once()
            ra_kwargs = mock_ra.call_args
            assert ra_kwargs[0][0] == "abc"  # artifact_id
            assert ra_kwargs[1]["inference_result"].passed is True
            assert ra_kwargs[1]["reconstruction_result"].passed is True

    def test_register_artifact_not_called_on_wf_fail(self, tmp_path):
        """When walk-forward fails, register_artifact should NOT be called."""
        from dataclasses import dataclass

        @dataclass
        class FakeWfResult:
            mean_ic: float = -0.01
            std_ic: float = 0.02
            ic_ir: float = 0.1
            consistency_score: float = 0.3
            n_splits: int = 3
            splits: list = None

            def __post_init__(self):
                if self.splits is None:
                    self.splits = [1, 2, 3]

        mock_wf_result = FakeWfResult()

        mock_inference = InferenceResult(
            artifact_id="abc", passed=True, n_samples=50, n_predictions=50
        )
        mock_reconstruction = ReconstructionResult(
            artifact_id="abc", passed=False, status="not_run", clean_process=True
        )

        with (
            patch("src.workflows.hooks.walk_forward_validate", return_value=mock_wf_result),
            patch("src.workflows.hooks.register_model"),
            patch("src.workflows.hooks.register_artifact") as mock_ra,
            patch("src.workflows.hooks.validate_inference", return_value=mock_inference),
            patch(
                "src.workflows.hooks._run_clean_reconstruction", return_value=mock_reconstruction
            ),
            patch("src.workflows.hooks.ResearchService") as mock_rs_cls,
            patch("src.workflows.hooks.GovernanceService"),
            patch("src.workflows.hooks.EnvironmentManager"),
            patch("src.workflows.hooks.ArtifactRefreshService"),
            patch("src.workflows.hooks.compile_strategy_profile"),
            patch("src.workflows.hooks.generate_quality_report"),
            patch("src.workflows.hooks._publish_pipeline_result", side_effect=lambda x: x),
        ):
            mock_rs = MagicMock()
            mock_rs_cls.return_value = mock_rs
            mock_rs.resolve_snapshot_binding.return_value = {
                "snapshot_id": "snap_123",
                "provider_uri": "/tmp/data",
            }
            mock_rs.bind_config_to_snapshot.return_value = {
                "task": {
                    "model": {},
                    "dataset": {
                        "kwargs": {
                            "handler": {"kwargs": {"start_time": "2021-01-01"}},
                            "segments": {
                                "train": ["2021-01-01", "2024-12-31"],
                            },
                        }
                    },
                },
                "port_analysis_config": {},
                "qlib_init": {},
            }
            mock_rs.prepare_experiment.return_value = mock_rs.bind_config_to_snapshot.return_value

            manifest = MagicMock()
            manifest.id = "abc"
            manifest.config = {"market": "us"}

            mock_rs.run_training_pipeline.return_value = {
                "model_path": Path("/tmp/model.pkl"),
                "run_id": "run_123",
                "model": MagicMock(),
                "dataset": MagicMock(),
                "pred": pd.DataFrame(),
                "label": pd.DataFrame(),
                "metrics": {},
                "artifact_id": "abc",
                "artifact": manifest,
                "inference_result": mock_inference,
                "snapshot_id": "snap_123",
                "provider_uri": "/tmp/data",
            }

            from src.workflows.hooks import run_training_pipeline

            run_training_pipeline(
                market="us",
                model_type="lgbm",
                tag="test_v1",
                snapshot_id="snap_123",
            )

            # register_artifact should NOT have been called (WF gate failed)
            mock_ra.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5: Frozen config is stored, not the mutable original
# ---------------------------------------------------------------------------


class TestFrozenConfig:
    """The artifact must store a frozen copy of the config, not the original."""

    def test_artifact_config_is_detached_from_original(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        original_seed = sample_config["task"]["model"]["kwargs"]["seed"]
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="snap_test",
        )

        # Mutate original config after artifact creation
        sample_config["task"]["model"]["kwargs"]["seed"] = 99999

        # The artifact's config must still have the original value
        assert manifest.config["task"]["model"]["kwargs"]["seed"] == original_seed

        # The persisted config file must also have the original value
        artifact_dir = artifacts_root / "artifacts" / manifest.id
        persisted = json.loads((artifact_dir / "resolved_config.json").read_text())
        assert persisted["task"]["model"]["kwargs"]["seed"] == original_seed


# ---------------------------------------------------------------------------
# Test 6: market=all propagates snapshot_id
# ---------------------------------------------------------------------------


class TestMarketAllSnapshotPropagation:
    """market=all must propagate the resolved snapshot_id to child runs."""

    def test_snapshot_id_in_aggregate_result(self, tmp_path):
        """When market=all, the aggregate result includes the snapshot_id."""
        with (
            patch("src.workflows.hooks.ResearchService") as mock_rs_cls,
            patch("src.workflows.hooks.GovernanceService"),
            patch("src.workflows.hooks.EnvironmentManager") as mock_env_cls,
            patch("src.workflows.hooks.ArtifactRefreshService"),
            patch("src.workflows.hooks.compile_strategy_profile"),
            patch("src.workflows.hooks._publish_pipeline_result", side_effect=lambda x: x),
        ):
            mock_rs = MagicMock()
            mock_rs_cls.return_value = mock_rs
            mock_rs.resolve_snapshot_binding.return_value = {
                "snapshot_id": "snap_all_123",
                "provider_uri": "/tmp/data",
            }

            mock_env = MagicMock()
            mock_env_cls.return_value = mock_env
            mock_env.run_in_isolation.return_value = MagicMock()

            from src.workflows.hooks import run_training_pipeline

            result = run_training_pipeline(
                market="all",
                model_type="lgbm",
                tag="test_v1",
                snapshot_id="snap_all_123",
            )

            # The aggregate result should contain the resolved snapshot_id
            assert result["snapshot_id"] == "snap_all_123"
            assert result["market"] == "all"


# ---------------------------------------------------------------------------
# Test 7: Reconstruction without retrain is NOT_RUN
# ---------------------------------------------------------------------------


class TestReconstructionNotRun:
    """reconstruct_model without retrain_fn must return NOT_RUN, never PASS."""

    def test_not_run_without_retrain_fn(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        from src.models.reconstruction import reconstruct_model

        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="snap_test",
        )

        result = reconstruct_model(manifest.id)
        assert result.passed is False
        assert result.status == "not_run"
        assert result.clean_process is False
