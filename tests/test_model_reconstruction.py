"""Tests for src.models.reconstruction -- reconstruction and inference gates.

All tests use synthetic data and a trivial deterministic model so that results
are fully reproducible without external dependencies.
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.artifact import (
    ArtifactValidationError,
    clear_registry,
    create_artifact,
    register_artifact,
    set_artifacts_root,
)
from src.models.reconstruction import (
    InferenceResult,
    ReconstructionResult,
    reconstruct_model,
    validate_inference,
)

# ---------------------------------------------------------------------------
# Deterministic synthetic model
# ---------------------------------------------------------------------------


class _SyntheticModel:
    """Trivial linear model: y = X @ weights + bias.

    Fully deterministic and trivially pickle-serialisable.
    """

    def __init__(self, weights: np.ndarray, bias: float = 0.0):
        self.weights = np.asarray(weights, dtype=np.float64)
        self.bias = float(bias)

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        return X @ self.weights + self.bias


def _make_synthetic_model(n_features: int = 3, seed: int = 42) -> _SyntheticModel:
    rng = np.random.RandomState(seed)
    weights = rng.randn(n_features)
    bias = rng.randn()
    return _SyntheticModel(weights, bias)


def _make_synthetic_data(
    model: _SyntheticModel,
    n_rows: int = 100,
    n_features: int = 3,
    seed: int = 99,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate features and predictions using *model*.

    Returns ``(features_df, predictions_df)`` where predictions_df has a
    ``score`` column with model outputs and features are ``f0, f1, ...``.
    """
    rng = np.random.RandomState(seed)
    X = rng.randn(n_rows, n_features)
    preds = model.predict(X)

    dates = pd.date_range("2025-01-02", periods=n_rows, freq="B")
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product(
        [dates[: n_rows // len(instruments) + 1], instruments],
        names=["date", "instrument"],
    )
    idx = idx[:n_rows]

    feat_df = pd.DataFrame(X, index=idx, columns=[f"f{i}" for i in range(n_features)])
    pred_df = pd.DataFrame({"score": preds}, index=idx)
    return feat_df, pred_df


def _make_labels(n_rows: int = 100, seed: int = 7) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-02", periods=n_rows, freq="B")
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product(
        [dates[: n_rows // len(instruments) + 1], instruments],
        names=["date", "instrument"],
    )
    idx = idx[:n_rows]
    return pd.DataFrame({"label": rng.randn(n_rows)}, index=idx)


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


@pytest.fixture
def synthetic_model():
    return _make_synthetic_model(n_features=3, seed=42)


@pytest.fixture
def synthetic_model_dir(tmp_path, synthetic_model):
    """Create a directory with a pickled synthetic model."""
    d = tmp_path / "model_output"
    d.mkdir()
    with open(d / "model.pkl", "wb") as f:
        pickle.dump(synthetic_model, f)
    return d


@pytest.fixture
def sample_config():
    return {
        "market": "us",
        "benchmark": "QQQ",
        "task": {
            "model": {"class": "SyntheticModel", "kwargs": {"seed": 42}},
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
def sample_predictions(synthetic_model):
    _, pred_df = _make_synthetic_data(synthetic_model, n_rows=60, n_features=3, seed=99)
    return pred_df


@pytest.fixture
def sample_labels():
    return _make_labels(n_rows=60, seed=7)


@pytest.fixture
def created_artifact(
    artifacts_root, synthetic_model_dir, sample_config, sample_predictions, sample_labels
):
    """Create and return a manifest for a valid artifact."""
    return create_artifact(
        model_dir=synthetic_model_dir,
        config=sample_config,
        predictions=sample_predictions,
        labels=sample_labels,
        snapshot_id="test_snap",
    )


# ---------------------------------------------------------------------------
# Test: Reconstruction result dataclass
# ---------------------------------------------------------------------------


class TestReconstructionResult:
    def test_passed_result(self):
        r = ReconstructionResult(artifact_id="abc", passed=True, prediction_correlation=1.0)
        assert r.passed
        assert r.error == ""

    def test_failed_result(self):
        r = ReconstructionResult(artifact_id="abc", passed=False, error="boom")
        assert not r.passed
        assert r.error == "boom"


# ---------------------------------------------------------------------------
# Test: reconstruct_model
# ---------------------------------------------------------------------------


class TestReconstructModel:
    """Test the reconstruction gate."""

    def test_reconstruction_without_retraining_is_not_run(self, created_artifact):
        """Stored-vs-stored comparison is not reconstruction and can never pass."""
        result = reconstruct_model(created_artifact.id)
        assert isinstance(result, ReconstructionResult)
        assert result.passed is False
        assert result.status == "not_run"
        assert result.config_match is True
        assert "retrain" in result.error.lower()

    def test_reconstruction_with_matching_retrain(
        self, artifacts_root, synthetic_model_dir, sample_config, sample_labels, synthetic_model
    ):
        """Retrain with the same deterministic model must produce matching predictions."""
        feat_df, score_df = _make_synthetic_data(synthetic_model, n_rows=60, n_features=3, seed=99)
        combined = feat_df.copy()
        combined["score"] = score_df["score"]

        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=combined,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        def retrain_fn(config):
            return synthetic_model

        def predict_fn(model, features_df):
            # Use all numeric columns except the last (which is the score)
            numeric_cols = features_df.select_dtypes(include=[np.number]).columns.tolist()
            feature_cols = numeric_cols[:-1]
            return model.predict(features_df[feature_cols].values)

        result = reconstruct_model(
            manifest.id,
            retrain_fn=retrain_fn,
            predict_fn=predict_fn,
            clean_process=True,
        )
        assert result.passed is True
        assert result.status == "passed"
        assert result.clean_process is True
        assert result.prediction_correlation == pytest.approx(1.0, abs=1e-6)

    def test_reconstruction_detects_config_drift(
        self, artifacts_root, synthetic_model_dir, sample_config, sample_labels, synthetic_model
    ):
        """Different config (model) produces different predictions, failing reconstruction."""
        feat_df, score_df = _make_synthetic_data(synthetic_model, n_rows=60, n_features=3, seed=99)
        combined = feat_df.copy()
        combined["score"] = score_df["score"]

        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=combined,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        # Simulate config drift: reconstruction uses a model with different weights
        drifted_model = _make_synthetic_model(n_features=3, seed=999)

        def retrain_fn(config):
            return drifted_model

        def predict_fn(model, features_df):
            numeric_cols = features_df.select_dtypes(include=[np.number]).columns.tolist()
            feature_cols = numeric_cols[:-1]
            return model.predict(features_df[feature_cols].values)

        result = reconstruct_model(
            manifest.id,
            retrain_fn=retrain_fn,
            predict_fn=predict_fn,
            clean_process=True,
        )
        # Different model -> different predictions -> reconstruction fails
        assert result.passed is False
        assert result.prediction_correlation < 0.999

    def test_reconstruction_fails_on_corrupted_predictions(self, created_artifact, artifacts_root):
        """Corrupted predictions file causes reconstruction to fail."""
        artifact_dir = artifacts_root / "artifacts" / created_artifact.id
        pred_file = artifact_dir / "predictions.csv"
        pred_file.write_text("TAMPERED_DATA", encoding="utf-8")

        # Tampering breaks checksum, so validation fails first
        result = reconstruct_model(created_artifact.id)
        assert result.passed is False
        assert "validation failed" in result.error.lower() or "checksum" in result.error.lower()

    def test_reconstruction_fails_on_missing_artifact(self, artifacts_root):
        """Non-existent artifact ID returns a failed result."""
        result = reconstruct_model("nonexistent_id_12345")
        assert result.passed is False
        assert result.error

    def test_reconstruction_with_custom_tolerance(self, created_artifact):
        """Tolerance cannot turn a not-run reconstruction into a pass."""
        result = reconstruct_model(created_artifact.id, tolerance=1e-10)
        assert result.passed is False
        assert result.status == "not_run"

    def test_reconstruction_handles_retrain_exception(self, created_artifact):
        """Exception in retrain_fn is caught and reported."""

        def bad_retrain(config):
            raise RuntimeError("training exploded")

        def predict_fn(model, features_df):
            return np.zeros(len(features_df))

        result = reconstruct_model(
            created_artifact.id,
            retrain_fn=bad_retrain,
            predict_fn=predict_fn,
        )
        assert result.passed is False
        assert "training exploded" in result.error


# ---------------------------------------------------------------------------
# Test: validate_inference
# ---------------------------------------------------------------------------


class TestValidateInference:
    """Test the inference validation gate."""

    def test_inference_with_multi_column_predictions(
        self, artifacts_root, synthetic_model_dir, sample_config, synthetic_model
    ):
        """validate_inference works when predictions has feature + score columns."""
        feat_df, score_df = _make_synthetic_data(synthetic_model, n_rows=60, n_features=3, seed=99)
        combined = feat_df.copy()
        combined["score"] = score_df["score"]
        labels = _make_labels(n_rows=60, seed=7)

        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=combined,
            labels=labels,
            snapshot_id="test_snap",
        )

        result = validate_inference(manifest.id)
        assert isinstance(result, InferenceResult)
        assert result.passed is True
        assert result.n_samples > 0
        assert result.n_predictions > 0
        assert result.prediction_correlation == pytest.approx(1.0, abs=1e-6)

    def test_inference_rejects_corrupted_binary(
        self, artifacts_root, synthetic_model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Corrupted model binary causes inference validation to fail."""
        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        # Corrupt the model binary
        artifact_dir = artifacts_root / "artifacts" / manifest.id
        model_file = artifact_dir / manifest.model_binary_path
        model_file.write_bytes(b"GARBAGE_NOT_A_PICKLE")

        # Need to also update checksums so validation still passes
        # (or we test the full chain -- validation will catch it)
        result = validate_inference(manifest.id)
        assert result.passed is False

    def test_inference_rejects_nonexistent_artifact(self, artifacts_root):
        """Non-existent artifact ID returns a failed result."""
        result = validate_inference("nonexistent_id_99999")
        assert result.passed is False
        assert result.error

    def test_inference_with_sample_size_limit(
        self, artifacts_root, synthetic_model_dir, sample_config, synthetic_model
    ):
        """n_samples parameter limits the number of rows used for inference."""
        feat_df, score_df = _make_synthetic_data(synthetic_model, n_rows=200, n_features=3, seed=99)
        combined = feat_df.copy()
        combined["score"] = score_df["score"]
        labels = _make_labels(n_rows=200, seed=7)

        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=combined,
            labels=labels,
            snapshot_id="test_snap",
        )

        result = validate_inference(manifest.id, n_samples=10)
        assert result.passed is True
        assert result.n_samples == 10

    def test_inference_with_empty_predictions(
        self, artifacts_root, synthetic_model_dir, sample_config, synthetic_model, sample_labels
    ):
        """Empty predictions DataFrame causes failure."""
        empty_preds = pd.DataFrame(columns=["score"])
        empty_preds.index = pd.MultiIndex.from_tuples([], names=["date", "instrument"])

        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=empty_preds,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        result = validate_inference(manifest.id)
        assert result.passed is False
        assert "empty" in result.error.lower()

    def test_inference_result_details(
        self, artifacts_root, synthetic_model_dir, sample_config, synthetic_model
    ):
        """InferenceResult.details contains useful metadata."""
        feat_df, score_df = _make_synthetic_data(synthetic_model, n_rows=30, n_features=3, seed=99)
        combined = feat_df.copy()
        combined["score"] = score_df["score"]
        labels = _make_labels(n_rows=30, seed=7)

        manifest = create_artifact(
            model_dir=synthetic_model_dir,
            config=sample_config,
            predictions=combined,
            labels=labels,
            snapshot_id="test_snap",
        )

        result = validate_inference(manifest.id)
        assert result.passed is True
        assert "feature_cols" in result.details
        assert "pred_col" in result.details
        assert "tolerance" in result.details


class TestRegistryEligibility:
    def test_registration_requires_fresh_inference_and_clean_reconstruction(self, created_artifact):
        inference = InferenceResult(artifact_id=created_artifact.id, passed=True, n_samples=10)
        same_process = ReconstructionResult(
            artifact_id=created_artifact.id,
            passed=True,
            status="passed",
            clean_process=False,
        )

        with pytest.raises(ArtifactValidationError, match="clean-process reconstruction"):
            register_artifact(
                created_artifact.id,
                inference_result=inference,
                reconstruction_result=same_process,
            )

        clean_process = ReconstructionResult(
            artifact_id=created_artifact.id,
            passed=True,
            status="passed",
            clean_process=True,
        )
        registered = register_artifact(
            created_artifact.id,
            inference_result=inference,
            reconstruction_result=clean_process,
        )
        assert registered.id == created_artifact.id
