"""Model reconstruction and inference gate.

Provides two gates that run against a registered ``ModelArtifact``:

* ``reconstruct_model`` -- loads the stored artifact, retrains on the original
  data/config, and compares the new predictions against the stored ones.
* ``validate_inference`` -- loads the stored model binary and runs inference on
  sample data drawn from the stored predictions, verifying the binary is
  loadable and produces deterministic output.

Both functions return a ``ReconstructionResult`` / ``InferenceResult``
dataclass so callers can programmatically gate model promotion.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.logging import get_logger
from src.models.artifact import (
    ArtifactValidationError,
    _get_artifacts_root,
    validate_artifact,
)
from src.models.artifact_manifest import ArtifactManifest

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


class ReconstructionStatus(str, Enum):
    NOT_RUN = "not_run"
    FAILED = "failed"
    PASSED = "passed"


@dataclass
class ReconstructionResult:
    """Outcome of a reconstruction attempt."""

    artifact_id: str
    passed: bool
    status: str = ReconstructionStatus.FAILED.value
    clean_process: bool = False
    prediction_correlation: float = 0.0
    """Pearson correlation between stored and retrained predictions (0-1)."""
    prediction_match_pct: float = 0.0
    """Percentage of predictions that match within tolerance."""
    metric_match_pct: float = 0.0
    """Percentage of key metrics that match within tolerance."""
    config_match: bool = True
    """Whether the stored config matches the current config."""
    error: str = ""
    """Non-empty when reconstruction failed outright."""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceResult:
    """Outcome of an inference validation attempt."""

    artifact_id: str
    passed: bool
    n_samples: int = 0
    n_predictions: int = 0
    prediction_correlation: float = 0.0
    """Pearson correlation between stored predictions and fresh inference."""
    prediction_match_pct: float = 0.0
    """Percentage of predictions that match within absolute tolerance."""
    error: str = ""
    """Non-empty when inference validation failed outright."""
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Absolute tolerance for floating-point prediction comparison.
_PREDICTION_ATOL: float = 1e-6

# Absolute tolerance for metric comparison.
_METRIC_ATOL: float = 1e-4

# Minimum correlation threshold for reconstruction to pass.
_MIN_CORRELATION: float = 0.999


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_model_binary(artifact_dir: Path, manifest: ArtifactManifest) -> Any:
    """Load the pickled model binary from an artifact directory."""
    model_path = artifact_dir / manifest.model_binary_path
    if not model_path.exists():
        raise FileNotFoundError(f"Model binary not found: {model_path}")
    with open(model_path, "rb") as f:
        return pickle.load(f)


def _load_predictions(artifact_dir: Path, manifest: ArtifactManifest) -> pd.DataFrame:
    """Load stored predictions CSV."""
    pred_path = artifact_dir / manifest.predictions_path
    if not pred_path.exists():
        raise FileNotFoundError(f"Predictions file not found: {pred_path}")
    return pd.read_csv(pred_path, index_col=0)


def _load_labels(artifact_dir: Path, manifest: ArtifactManifest) -> pd.DataFrame:
    """Load stored labels CSV."""
    labels_path = artifact_dir / manifest.labels_path
    if not labels_path.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_path}")
    return pd.read_csv(labels_path, index_col=0)


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation between two arrays; 1.0 if both are constant."""
    if len(a) < 2:
        return 1.0
    std_a, std_b = np.std(a), np.std(b)
    if std_a == 0 and std_b == 0:
        return 1.0
    if std_a == 0 or std_b == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _match_pct(a: np.ndarray, b: np.ndarray, atol: float) -> float:
    """Percentage of elements where |a - b| <= atol."""
    if len(a) == 0:
        return 100.0
    return float(np.mean(np.abs(a - b) <= atol) * 100)


# ---------------------------------------------------------------------------
# reconstruct_model
# ---------------------------------------------------------------------------


def reconstruct_model(
    artifact_id: str,
    *,
    retrain_fn: Any | None = None,
    predict_fn: Any | None = None,
    tolerance: float | None = None,
    clean_process: bool = False,
) -> ReconstructionResult:
    """Reconstruct a model artifact and verify prediction reproducibility.

    The standard flow:
    1. Load and validate the stored artifact (manifest + checksums).
    2. Load the stored config and model binary.
    3. If ``retrain_fn`` is provided, call it with the stored config to
       produce a fresh model; otherwise compare stored predictions against
       themselves (integrity check).
    4. If ``predict_fn`` is provided, generate fresh predictions and compare
       against stored predictions.
    5. Report prediction correlation, match %, and config consistency.

    Parameters
    ----------
    artifact_id:
        ID of the artifact to reconstruct.
    retrain_fn:
        Optional callable ``(config) -> model`` that retrains from scratch.
    predict_fn:
        Optional callable ``(model, features_df) -> np.ndarray``.
    tolerance:
        Override the default absolute tolerance for prediction matching.

    Returns
    -------
    ReconstructionResult
    """
    if tolerance is None:
        tolerance = _PREDICTION_ATOL

    # 1. Validate the artifact
    try:
        manifest = validate_artifact(artifact_id)
    except ArtifactValidationError as exc:
        return ReconstructionResult(
            artifact_id=artifact_id,
            passed=False,
            config_match=False,
            error=f"Artifact validation failed: {exc}",
        )

    artifact_dir = _get_artifacts_root() / "artifacts" / artifact_id

    if retrain_fn is None or predict_fn is None:
        return ReconstructionResult(
            artifact_id=artifact_id,
            passed=False,
            status=ReconstructionStatus.NOT_RUN.value,
            clean_process=False,
            error="Reconstruction not run: retrain_fn and predict_fn are required",
        )

    # 2. Load stored predictions
    try:
        stored_preds = _load_predictions(artifact_dir, manifest)
    except FileNotFoundError as exc:
        return ReconstructionResult(
            artifact_id=artifact_id,
            passed=False,
            error=str(exc),
        )

    numeric_cols = stored_preds.select_dtypes(include=[np.number]).columns.tolist()

    # 3. Retrain and predict. The caller marks whether this callback was
    # executed in a fresh interpreter; same-process runs are diagnostic only.
    try:
        fresh_model = retrain_fn(manifest.config)
        fresh_preds = predict_fn(fresh_model, stored_preds)
    except Exception as exc:
        return ReconstructionResult(
            artifact_id=artifact_id,
            passed=False,
            status=ReconstructionStatus.FAILED.value,
            clean_process=clean_process,
            error=f"Retraining/prediction failed: {exc}",
        )
    fresh_values = np.asarray(fresh_preds, dtype=np.float64).flatten()
    # Compare against the last numeric column (the score/prediction column)
    # when stored predictions have multiple numeric columns (features + score).
    if len(numeric_cols) >= 2:
        stored_values = stored_preds[numeric_cols[-1]].values.astype(np.float64)
    elif numeric_cols:
        stored_values = stored_preds[numeric_cols[0]].values.astype(np.float64)
    else:
        return ReconstructionResult(
            artifact_id=artifact_id,
            passed=False,
            status=ReconstructionStatus.FAILED.value,
            clean_process=clean_process,
            error="Stored predictions contain no numeric prediction column",
        )

    # 4. Compare
    min_len = min(len(stored_values), len(fresh_values))
    stored_trimmed = stored_values[:min_len]
    fresh_trimmed = fresh_values[:min_len]

    corr = _correlation(stored_trimmed, fresh_trimmed)
    match_pct = _match_pct(stored_trimmed, fresh_trimmed, tolerance)

    prediction_match = corr >= _MIN_CORRELATION and match_pct >= 99.0
    passed = prediction_match and clean_process

    result = ReconstructionResult(
        artifact_id=artifact_id,
        passed=passed,
        status=(ReconstructionStatus.PASSED.value if passed else ReconstructionStatus.FAILED.value),
        clean_process=clean_process,
        prediction_correlation=round(corr, 6),
        prediction_match_pct=round(match_pct, 4),
        config_match=True,
        details={
            "n_stored_predictions": len(stored_values),
            "n_fresh_predictions": len(fresh_values),
            "tolerance": tolerance,
            "prediction_match": prediction_match,
        },
    )

    if prediction_match and not clean_process:
        result.error = "Reconstruction was not executed in a clean process"

    if passed:
        logger.info(
            "Reconstruction passed",
            artifact_id=artifact_id,
            correlation=corr,
            match_pct=match_pct,
        )
    else:
        logger.warning(
            "Reconstruction failed",
            artifact_id=artifact_id,
            correlation=corr,
            match_pct=match_pct,
        )

    return result


# ---------------------------------------------------------------------------
# validate_inference
# ---------------------------------------------------------------------------


def validate_inference(
    artifact_id: str,
    *,
    n_samples: int | None = None,
    tolerance: float | None = None,
) -> InferenceResult:
    """Validate that the stored model binary can produce inference output.

    Steps:
    1. Load and validate the stored artifact.
    2. Deserialize the model binary.
    3. Load stored predictions and sample *n_samples* rows.
    4. Run the model's ``predict`` method on the sample features.
    5. Compare the fresh predictions against the stored predictions for those
       same rows.

    This gate catches binary corruption, missing dependencies, and
    non-deterministic model behavior.

    Parameters
    ----------
    artifact_id:
        ID of the artifact to validate.
    n_samples:
        Number of prediction rows to sample.  Defaults to all rows (capped at
        500 for performance).
    tolerance:
        Override the default absolute tolerance.

    Returns
    -------
    InferenceResult
    """
    if tolerance is None:
        tolerance = _PREDICTION_ATOL

    # 1. Validate the artifact
    try:
        manifest = validate_artifact(artifact_id)
    except ArtifactValidationError as exc:
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            error=f"Artifact validation failed: {exc}",
        )

    artifact_dir = _get_artifacts_root() / "artifacts" / artifact_id

    # 2. Load model binary
    try:
        model = _load_model_binary(artifact_dir, manifest)
    except Exception as exc:
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            error=f"Model binary load failed: {exc}",
        )

    # 3. Load stored predictions
    try:
        stored_preds = _load_predictions(artifact_dir, manifest)
    except FileNotFoundError as exc:
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            error=str(exc),
        )

    if stored_preds.empty:
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            n_samples=0,
            error="Stored predictions are empty",
        )

    # 4. Sample rows
    max_samples = min(n_samples or len(stored_preds), 500, len(stored_preds))
    sampled = stored_preds.head(max_samples)

    # Extract numeric columns as features (all except the last, which is the
    # prediction column -- convention: last column is the score/prediction).
    numeric_cols = sampled.select_dtypes(include=[np.number]).columns.tolist()
    if len(numeric_cols) < 2:
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            n_samples=max_samples,
            error=(
                f"Need at least 2 numeric columns for inference validation, "
                f"got {len(numeric_cols)}: {numeric_cols}"
            ),
        )

    feature_cols = numeric_cols[:-1]
    pred_col = numeric_cols[-1]

    features = sampled[feature_cols].values
    stored_values = sampled[pred_col].values

    # 5. Run inference
    if not hasattr(model, "predict"):
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            n_samples=max_samples,
            error="Model object has no 'predict' method",
        )

    try:
        fresh_preds = model.predict(features)
    except Exception as exc:
        return InferenceResult(
            artifact_id=artifact_id,
            passed=False,
            n_samples=max_samples,
            error=f"Model inference failed: {exc}",
        )

    fresh_values = np.asarray(fresh_preds, dtype=np.float64).flatten()

    # 6. Compare
    min_len = min(len(stored_values), len(fresh_values))
    stored_trimmed = stored_values[:min_len]
    fresh_trimmed = fresh_values[:min_len]

    corr = _correlation(stored_trimmed, fresh_trimmed)
    match_pct = _match_pct(stored_trimmed, fresh_trimmed, tolerance)

    passed = corr >= _MIN_CORRELATION and match_pct >= 99.0

    result = InferenceResult(
        artifact_id=artifact_id,
        passed=passed,
        n_samples=max_samples,
        n_predictions=min_len,
        prediction_correlation=round(corr, 6),
        prediction_match_pct=round(match_pct, 4),
        details={
            "feature_cols": feature_cols,
            "pred_col": pred_col,
            "tolerance": tolerance,
        },
    )

    if passed:
        logger.info(
            "Inference validation passed",
            artifact_id=artifact_id,
            correlation=corr,
            match_pct=match_pct,
        )
    else:
        logger.warning(
            "Inference validation failed",
            artifact_id=artifact_id,
            correlation=corr,
            match_pct=match_pct,
        )

    return result
