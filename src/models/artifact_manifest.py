"""Immutable manifest describing every file and provenance detail of a trained model.

The manifest is the single source of truth for a ModelArtifact.  All paths are
relative to the artifact directory so that an artifact bundle is portable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactManifest:
    """Provenance manifest attached to every ModelArtifact.

    All fields are required at creation time (``None`` means "not yet set"
    and will fail validation).
    """

    # -- identity --
    id: str
    """Globally unique artifact id (e.g. ``uuid4`` hex)."""

    # -- model binary --
    model_binary_path: str
    """Relative path to the serialised model file (e.g. ``model.pkl``)."""

    # -- training config --
    config: dict[str, Any] = field(default_factory=dict)
    """Full training config snapshot (model class, hyper-params, dataset)."""

    config_path: str = ""
    """Relative path to the canonical resolved config JSON."""

    features: list[str] = field(default_factory=list)
    """Ordered list of feature names used during training."""

    label_schema: dict[str, Any] = field(default_factory=dict)
    """Label definition (column, transform, horizon)."""

    # -- data provenance --
    snapshot_id: str = ""
    """Data snapshot identifier that produced the training dataset."""

    provider_uri: str = ""
    """Resolved immutable provider path used by the training process."""

    # -- time windows --
    train_window: list[str] = field(default_factory=list)
    """[start, end] for training period."""

    valid_window: list[str] = field(default_factory=list)
    """[start, end] for validation period."""

    test_window: list[str] = field(default_factory=list)
    """[start, end] for test / holdout period."""

    # -- evaluation --
    benchmark: str = ""
    """Benchmark instrument ticker (e.g. ``QQQ``, ``000300``)."""

    costs: dict[str, float] = field(default_factory=dict)
    """Transaction cost assumptions (open_cost, close_cost, min_cost, etc.)."""

    # -- reproducibility --
    code_revision: str = ""
    """Git commit hash at time of training."""

    uv_lock_hash: str = ""
    """Hash of uv.lock for deterministic dependency resolution."""

    python_version: str = ""
    """Python interpreter version string."""

    seeds: dict[str, int] = field(default_factory=dict)
    """Random seeds used (numpy, torch, lightgbm, xgboost, etc.)."""

    # -- output artefacts --
    predictions_path: str = ""
    """Relative path to predictions CSV/parquet."""

    labels_path: str = ""
    """Relative path to labels CSV/parquet."""

    diagnostics_path: str = ""
    """Relative path to diagnostics JSON (metrics, feature importance, etc.)."""

    logs_path: str = ""
    """Relative path to the captured training log."""

    metrics_path: str = ""
    """Relative path to metrics normalized to the standard contract."""

    metric_contract_version: str = "v1"
    """Version of the standard metric contract used by ``metrics_path``."""

    # -- integrity --
    checksums: dict[str, str] = field(default_factory=dict)
    """Mapping of relative-path -> sha256 hex digest for every file in the bundle."""

    # -- serialisation helpers ------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict (JSON-serialisable)."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: Path) -> None:
        """Write manifest JSON to *path*."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_json_file(cls, path: Path) -> ArtifactManifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    # -- validation helpers ---------------------------------------------------

    # All manifest fields (for documentation / completeness checks).
    REQUIRED_FIELDS: tuple[str, ...] = (
        "id",
        "model_binary_path",
        "config",
        "config_path",
        "features",
        "label_schema",
        "snapshot_id",
        "provider_uri",
        "train_window",
        "valid_window",
        "test_window",
        "benchmark",
        "costs",
        "code_revision",
        "uv_lock_hash",
        "python_version",
        "seeds",
        "predictions_path",
        "labels_path",
        "diagnostics_path",
        "logs_path",
        "metrics_path",
        "metric_contract_version",
        "checksums",
    )

    # Fields that MUST be non-empty for an artifact to be considered valid.
    # Provenance metadata (snapshot_id, benchmark, code_revision, etc.) is
    # recorded even when empty -- the absence of a value is itself meaningful.
    STRUCTURAL_REQUIRED: tuple[str, ...] = (
        "id",
        "model_binary_path",
        "config",
        "config_path",
        "predictions_path",
        "labels_path",
        "diagnostics_path",
        "checksums",
    )

    def missing_required(self) -> list[str]:
        """Return list of structural fields that are empty / None.

        Only ``STRUCTURAL_REQUIRED`` fields are checked.  Provenance metadata
        (snapshot_id, benchmark, code_revision, ...) is allowed to be empty.
        """
        missing: list[str] = []
        for fname in self.STRUCTURAL_REQUIRED:
            val = getattr(self, fname, None)
            if val is None:
                missing.append(fname)
            elif isinstance(val, str) and not val.strip():
                missing.append(fname)
            elif isinstance(val, dict) and len(val) == 0:
                missing.append(fname)
        return missing

    def missing_complete(self) -> list[str]:
        """Return provenance fields required for a promotion-eligible artifact."""
        complete_required = (
            "config_path",
            "features",
            "label_schema",
            "snapshot_id",
            "provider_uri",
            "code_revision",
            "uv_lock_hash",
            "seeds",
            "logs_path",
            "metrics_path",
        )
        missing: list[str] = []
        for fname in complete_required:
            value = getattr(self, fname, None)
            if value is None or value == "" or value == [] or value == {}:
                missing.append(fname)
        return missing
