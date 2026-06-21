"""ModelArtifact -- immutable, self-contained bundle for a trained model.

A ``ModelArtifact`` packages the model binary, config snapshot, feature list,
predictions, labels, diagnostics, and a full provenance manifest into a single
directory that can be validated and registered.

Usage::

    from src.models.artifact import create_artifact, validate_artifact, register_artifact

    artifact = create_artifact(model_dir, config, predictions_df, labels_df)
    validate_artifact(artifact.id)
    register_artifact(artifact.id)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.logging import get_logger
from src.models.artifact_manifest import ArtifactManifest
from src.models.metric_contract import normalize_metrics, validate_metrics

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level registry (artifact_id -> ArtifactManifest)
# In production this would be backed by SQLite; the in-memory dict suffices
# for validation gating and keeps the module dependency-light.
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, ArtifactManifest] = {}

# Default artifact root -- callers can override via ``ARTIFACTS_DIR`` env.
_ARTIFACTS_ROOT: Path | None = None


def _get_artifacts_root() -> Path:
    global _ARTIFACTS_ROOT
    if _ARTIFACTS_ROOT is not None:
        return _ARTIFACTS_ROOT
    try:
        from src.common.paths import get_artifacts_dir

        return get_artifacts_dir()
    except Exception:
        return Path("artifacts")


def set_artifacts_root(path: Path) -> None:
    """Override the artifacts root (useful in tests)."""
    global _ARTIFACTS_ROOT
    _ARTIFACTS_ROOT = path


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_revision() -> str:
    """Return the current git HEAD hash, or empty string if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _uv_lock_hash() -> str:
    """Return sha256 of uv.lock if it exists, else empty string."""
    lock_path = Path(__file__).resolve().parents[2] / "uv.lock"
    if lock_path.exists():
        return _sha256_file(lock_path)
    return ""


# ---------------------------------------------------------------------------
# create_artifact
# ---------------------------------------------------------------------------


def create_artifact(
    model_dir: Path | str,
    config: dict[str, Any],
    predictions: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    features: list[str] | None = None,
    label_schema: dict[str, Any] | None = None,
    snapshot_id: str = "",
    provider_uri: str = "",
    benchmark: str = "",
    costs: dict[str, float] | None = None,
    seeds: dict[str, int] | None = None,
    logs: str | list[str] | dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> ArtifactManifest:
    """Package a trained model and its outputs into an immutable ``ModelArtifact``.

    Parameters
    ----------
    model_dir:
        Directory containing the trained model binary (``*.pkl``).
    config:
        Full training config dict.
    predictions:
        DataFrame of model predictions (saved as CSV).
    labels:
        DataFrame of ground-truth labels (saved as CSV).
    features:
        Ordered feature name list.  Extracted from ``config`` when omitted.
    label_schema:
        Label definition dict.  Extracted from ``config`` when omitted.
    snapshot_id:
        Data snapshot identifier.
    benchmark:
        Benchmark ticker.
    costs:
        Transaction cost assumptions.
    seeds:
        Random seeds for reproducibility.

    Returns
    -------
    ArtifactManifest
        The fully-populated manifest (also persisted to disk).
    """
    if not snapshot_id:
        raise ArtifactValidationError("snapshot_id is required")

    model_dir = Path(model_dir)
    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    # Locate model binary
    if model_dir.is_file():
        if model_dir.suffix.lower() != ".pkl":
            raise FileNotFoundError(f"No .pkl model binary found in {model_dir}")
        model_binary = model_dir
    else:
        pkl_files = sorted(model_dir.glob("*.pkl"))
        if not pkl_files:
            raise FileNotFoundError(f"No .pkl model binary found in {model_dir}")
        model_binary = pkl_files[0]

    normalized_metrics: dict[str, Any] | None = None
    if metrics is not None:
        normalized_metrics = normalize_metrics(metrics)
        metric_validation = validate_metrics(normalized_metrics)
        if not metric_validation.ok:
            raise ArtifactValidationError(
                f"ModelArtifact has missing required metrics: {metric_validation.missing_required}"
            )

    # A JSON round-trip detaches all nested config objects from mutable caller state.
    frozen_config = json.loads(json.dumps(deepcopy(config), ensure_ascii=False, default=str))

    # Derive artifact id
    artifact_id = uuid.uuid4().hex
    artifact_dir = _get_artifacts_root() / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Copy / write outputs
    import shutil

    bin_dest = artifact_dir / model_binary.name
    shutil.copy2(model_binary, bin_dest)

    config_path = artifact_dir / "resolved_config.json"
    config_path.write_text(
        json.dumps(frozen_config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    pred_path = artifact_dir / "predictions.csv"
    predictions.to_csv(pred_path, index=True)

    labels_path = artifact_dir / "labels.csv"
    labels.to_csv(labels_path, index=True)

    # Extract features / label_schema from config if not supplied
    if features is None:
        features = _extract_features(frozen_config)
    if label_schema is None:
        label_schema = _extract_label_schema(frozen_config)

    # Auto-fill benchmark from config when not explicitly provided
    if not benchmark:
        benchmark = frozen_config.get("benchmark", "")

    # Time windows from config
    segments = (
        frozen_config.get("task", {}).get("dataset", {}).get("kwargs", {}).get("segments", {})
    )
    train_window = segments.get("train", [])
    valid_window = segments.get("valid", [])
    test_window = segments.get("test", [])

    # Build diagnostics
    diagnostics = {
        "created_at": datetime.now().isoformat(),
        "n_predictions": len(predictions),
        "n_labels": len(labels),
        "metrics": normalized_metrics or {},
    }
    diag_path = artifact_dir / "diagnostics.json"
    diag_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    logs_path = ""
    if logs is not None:
        logs_path = "training.log"
        if isinstance(logs, str):
            log_text = logs
        elif isinstance(logs, list):
            log_text = "\n".join(str(line) for line in logs)
        else:
            log_text = json.dumps(logs, ensure_ascii=False, sort_keys=True)
        (artifact_dir / logs_path).write_text(log_text.rstrip("\n") + "\n", encoding="utf-8")

    metrics_path = ""
    if normalized_metrics is not None:
        metrics_path = "metrics.json"
        (artifact_dir / metrics_path).write_text(
            json.dumps(normalized_metrics, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # Compute checksums for all files in the bundle
    checksums: dict[str, str] = {}
    for f in sorted(artifact_dir.iterdir()):
        if f.is_file():
            checksums[f.name] = _sha256_file(f)

    # Build manifest
    manifest = ArtifactManifest(
        id=artifact_id,
        model_binary_path=model_binary.name,
        config=frozen_config,
        config_path="resolved_config.json",
        features=list(features),
        label_schema=deepcopy(label_schema or {}),
        snapshot_id=snapshot_id,
        provider_uri=str(provider_uri),
        train_window=[str(w) for w in train_window],
        valid_window=[str(w) for w in valid_window],
        test_window=[str(w) for w in test_window],
        benchmark=benchmark,
        costs=costs or {},
        code_revision=_git_revision(),
        uv_lock_hash=_uv_lock_hash(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        seeds=seeds or {},
        predictions_path="predictions.csv",
        labels_path="labels.csv",
        diagnostics_path="diagnostics.json",
        logs_path=logs_path,
        metrics_path=metrics_path,
        metric_contract_version="v1",
        checksums=checksums,
    )

    if normalized_metrics is not None:
        missing_complete = manifest.missing_complete()
        if missing_complete:
            shutil.rmtree(artifact_dir, ignore_errors=True)
            raise ArtifactValidationError(f"ModelArtifact is incomplete: {missing_complete}")

    # Persist manifest
    manifest_path = artifact_dir / "manifest.json"
    manifest.save(manifest_path)

    # Register in memory
    _REGISTRY[artifact_id] = manifest

    logger.info(
        "ModelArtifact created",
        artifact_id=artifact_id,
        model_binary=str(model_binary.name),
        n_features=len(features),
    )
    return manifest


# ---------------------------------------------------------------------------
# validate_artifact
# ---------------------------------------------------------------------------


class ArtifactValidationError(Exception):
    """Raised when an artifact fails validation."""


def validate_artifact(artifact_id: str) -> ArtifactManifest:
    """Validate an artifact by id.

    Checks:
    1. Manifest exists in registry or on disk.
    2. All required manifest fields are populated.
    3. All referenced files exist in the artifact directory.
    4. SHA-256 checksums match.

    Returns the validated manifest.

    Raises
    ------
    ArtifactValidationError
        If any check fails.
    """
    manifest = _REGISTRY.get(artifact_id)
    if manifest is None:
        # Try loading from disk
        artifact_dir = _get_artifacts_root() / "artifacts" / artifact_id
        manifest_path = artifact_dir / "manifest.json"
        if not manifest_path.exists():
            raise ArtifactValidationError(
                f"Artifact {artifact_id!r} not found in registry or on disk."
            )
        manifest = ArtifactManifest.from_json_file(manifest_path)

    # 1. Required fields
    missing = manifest.missing_required()
    if missing:
        raise ArtifactValidationError(
            f"Artifact {artifact_id!r} has missing required fields: {missing}"
        )

    # 2. Files exist
    artifact_dir = _get_artifacts_root() / "artifacts" / artifact_id
    for rel_path in [
        manifest.model_binary_path,
        manifest.config_path,
        manifest.predictions_path,
        manifest.labels_path,
        manifest.diagnostics_path,
        manifest.logs_path,
        manifest.metrics_path,
    ]:
        if not rel_path:
            continue
        full = artifact_dir / rel_path
        if not full.exists():
            raise ArtifactValidationError(
                f"Artifact {artifact_id!r}: referenced file missing: {rel_path}"
            )

    # 3. Checksum integrity
    for fname, expected_hash in manifest.checksums.items():
        fpath = artifact_dir / fname
        if not fpath.exists():
            raise ArtifactValidationError(
                f"Artifact {artifact_id!r}: checksummed file missing: {fname}"
            )
        actual = _sha256_file(fpath)
        if actual != expected_hash:
            raise ArtifactValidationError(
                f"Artifact {artifact_id!r}: checksum mismatch for {fname}: "
                f"expected {expected_hash[:16]}..., got {actual[:16]}..."
            )

    logger.info("Artifact validated", artifact_id=artifact_id)
    return manifest


# ---------------------------------------------------------------------------
# register_artifact
# ---------------------------------------------------------------------------


def register_artifact(
    artifact_id: str,
    *,
    inference_result: Any | None = None,
    reconstruction_result: Any | None = None,
) -> ArtifactManifest:
    """Register a validated artifact.

    Validates first, then promotes to "registered" status in the in-memory
    registry.  In production this would also upsert into the model registry
    SQLite database.

    Returns the registered manifest.
    """
    manifest = validate_artifact(artifact_id)

    if (
        inference_result is None
        or inference_result.artifact_id != artifact_id
        or not inference_result.passed
        or inference_result.n_samples <= 0
    ):
        raise ArtifactValidationError(
            "Artifact registry eligibility requires fresh inference for this artifact"
        )
    if (
        reconstruction_result is None
        or reconstruction_result.artifact_id != artifact_id
        or not reconstruction_result.passed
        or getattr(reconstruction_result, "status", "") != "passed"
        or not getattr(reconstruction_result, "clean_process", False)
    ):
        raise ArtifactValidationError(
            "Artifact registry eligibility requires a passed clean-process reconstruction"
        )

    # Ensure it is in the in-memory registry
    _REGISTRY[artifact_id] = manifest

    # Persist a registration marker
    artifact_dir = _get_artifacts_root() / "artifacts" / artifact_id
    reg_marker = artifact_dir / ".registered"
    reg_marker.write_text(
        json.dumps(
            {
                "artifact_id": artifact_id,
                "registered_at": datetime.now().isoformat(),
                "inference_gate": inference_result.__dict__,
                "reconstruction_gate": reconstruction_result.__dict__,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Upsert into the model registry SQLite DB
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex
        from src.common import paths

        db_path = resolve_metadata_db_path(paths.get_artifacts_dir())
        index = ModelRegistryIndex(db_path=db_path)
        index.upsert_entry(
            {
                "id": artifact_id,
                "tag": f"artifact_{artifact_id[:8]}",
                "path": str(artifact_dir / manifest.model_binary_path),
                "type": manifest.config.get("task", {}).get("model", {}).get("class", "Unknown"),
                "market": manifest.config.get("market", ""),
                "created_at": datetime.now().isoformat(),
                "run_id": artifact_id,
                "artifact_id": artifact_id,
                "artifact_config": manifest.config,
                "inference_gate": inference_result.__dict__,
                "reconstruction_gate": reconstruction_result.__dict__,
                "backtest": {"metrics": {}},
            }
        )
    except Exception as exc:
        logger.debug("Could not upsert to model registry DB", error=str(exc))

    logger.info("Artifact registered", artifact_id=artifact_id)
    return manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_features(config: dict[str, Any]) -> list[str]:
    """Try to extract feature list from a qlib-style config."""
    try:
        loader_cfg = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"][
            "kwargs"
        ]["config"]
        feature_exprs = loader_cfg.get("feature", [])
        return [str(f) for f in feature_exprs]
    except (KeyError, TypeError):
        return []


def _extract_label_schema(config: dict[str, Any]) -> dict[str, Any]:
    """Try to extract label schema from a qlib-style config."""
    try:
        loader_cfg = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"][
            "kwargs"
        ]["config"]
        label_exprs = loader_cfg.get("label", [])
        return {"expressions": [str(expr) for expr in label_exprs]}
    except (KeyError, TypeError):
        return {}


def get_registry() -> dict[str, ArtifactManifest]:
    """Return a copy of the in-memory artifact registry."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Clear the in-memory registry (for testing)."""
    _REGISTRY.clear()
