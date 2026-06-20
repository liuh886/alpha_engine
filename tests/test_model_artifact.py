"""Tests for src.models.artifact -- ModelArtifact creation, validation, registration."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.artifact import (
    ArtifactValidationError,
    _sha256_file,
    clear_registry,
    create_artifact,
    get_registry,
    register_artifact,
    set_artifacts_root,
    validate_artifact,
)
from src.models.artifact_manifest import ArtifactManifest
from src.models.reconstruction import InferenceResult, ReconstructionResult


def _eligibility_results(artifact_id: str) -> dict:
    return {
        "inference_result": InferenceResult(
            artifact_id=artifact_id,
            passed=True,
            n_samples=10,
            n_predictions=10,
        ),
        "reconstruction_result": ReconstructionResult(
            artifact_id=artifact_id,
            passed=True,
            status="passed",
            clean_process=True,
        ),
    }

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure a clean in-memory registry for every test."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def artifacts_root(tmp_path):
    """Point the artifact module at a temp directory.

    ``set_artifacts_root`` is the *parent* of the ``artifacts/`` sub-directory
    that ``create_artifact`` builds, so we pass ``tmp_path`` directly.
    """
    set_artifacts_root(tmp_path)
    yield tmp_path
    set_artifacts_root(Path("__reset__"))  # sentinel: no valid dir


@pytest.fixture
def model_dir(tmp_path):
    """Create a fake model directory with a pkl file and a config."""
    d = tmp_path / "model_output"
    d.mkdir()
    # Write a dummy model binary
    (d / "model.pkl").write_bytes(b"fake model binary bytes")
    return d


@pytest.fixture
def sample_config():
    """Minimal qlib-style config with all segments."""
    return {
        "market": "us",
        "benchmark": "QQQ",
        "task": {
            "model": {"class": "LGBModel", "kwargs": {"max_depth": 6}},
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {
                            "data_loader": {
                                "kwargs": {
                                    "config": {
                                        "feature": ["$close/$open", "$high/$low"],
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
    dates = pd.date_range("2025-01-02", periods=10, freq="B")
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product([dates, instruments], names=["date", "instrument"])
    return pd.DataFrame({"score": [0.5] * len(idx)}, index=idx)


@pytest.fixture
def sample_labels():
    dates = pd.date_range("2025-01-02", periods=10, freq="B")
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product([dates, instruments], names=["date", "instrument"])
    return pd.DataFrame({"label": [0.01] * len(idx)}, index=idx)


# ---------------------------------------------------------------------------
# Tests: Artifact creation
# ---------------------------------------------------------------------------


class TestCreateArtifact:
    """Test create_artifact packaging."""

    def test_creates_manifest_with_all_fields(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """create_artifact returns a manifest with every field populated."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="snap_20260101",
            benchmark="QQQ",
            costs={"open_cost": 0.001, "close_cost": 0.001},
            seeds={"numpy": 42, "lightgbm": 123},
        )

        assert manifest.id
        assert manifest.model_binary_path == "model.pkl"
        assert manifest.config == sample_config
        assert len(manifest.features) == 2
        assert manifest.label_schema
        assert manifest.snapshot_id == "snap_20260101"
        assert manifest.benchmark == "QQQ"
        assert manifest.costs == {"open_cost": 0.001, "close_cost": 0.001}
        assert manifest.seeds == {"numpy": 42, "lightgbm": 123}
        assert manifest.train_window == ["2021-01-01", "2024-12-31"]
        assert manifest.valid_window == ["2025-01-01", "2025-06-30"]
        assert manifest.test_window == ["2025-07-01", "2026-01-01"]
        assert manifest.predictions_path == "predictions.csv"
        assert manifest.labels_path == "labels.csv"
        assert manifest.diagnostics_path == "diagnostics.json"
        assert manifest.python_version
        assert manifest.checksums

    def test_complete_artifact_freezes_resolved_training_provenance(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """A successful training artifact contains every reproducibility output."""
        resolved_config = deepcopy(sample_config)
        metrics = {"annualized_return": 0.12, "max_drawdown": -0.08}

        manifest = create_artifact(
            model_dir=model_dir,
            config=resolved_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="snapshot-content-id",
            provider_uri=str(artifacts_root / "snapshots" / "snapshot-content-id"),
            seeds={"python": 7, "numpy": 7, "lightgbm": 7},
            logs=["fit:start", "fit:complete"],
            metrics=metrics,
        )

        resolved_config["task"]["model"]["kwargs"]["max_depth"] = 99
        artifact_dir = artifacts_root / "artifacts" / manifest.id

        assert manifest.config["task"]["model"]["kwargs"]["max_depth"] == 6
        assert manifest.snapshot_id == "snapshot-content-id"
        assert manifest.provider_uri.endswith("snapshot-content-id")
        assert manifest.config_path == "resolved_config.json"
        assert manifest.logs_path == "training.log"
        assert manifest.metrics_path == "metrics.json"
        assert json.loads((artifact_dir / manifest.metrics_path).read_text())["annualized_return"] == 0.12
        assert (artifact_dir / manifest.logs_path).read_text(encoding="utf-8").splitlines() == [
            "fit:start",
            "fit:complete",
        ]
        assert set(manifest.checksums) >= {
            "model.pkl",
            "resolved_config.json",
            "predictions.csv",
            "labels.csv",
            "diagnostics.json",
            "training.log",
            "metrics.json",
        }

    def test_complete_artifact_rejects_missing_standard_metrics(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        with pytest.raises(ArtifactValidationError, match="missing required metrics"):
            create_artifact(
                model_dir=model_dir,
                config=sample_config,
                predictions=sample_predictions,
                labels=sample_labels,
                snapshot_id="snapshot-content-id",
                provider_uri=str(artifacts_root / "snapshots" / "snapshot-content-id"),
                seeds={"numpy": 7},
                logs=["fit:complete"],
                metrics={"annualized_return": 0.12},
            )

    def test_creates_artifact_directory_with_all_files(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """All output files are written to the artifact directory."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        artifact_dir = artifacts_root / "artifacts" / manifest.id
        assert (artifact_dir / "model.pkl").exists()
        assert (artifact_dir / "predictions.csv").exists()
        assert (artifact_dir / "labels.csv").exists()
        assert (artifact_dir / "diagnostics.json").exists()
        assert (artifact_dir / "manifest.json").exists()

    def test_manifest_roundtrips_through_json(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Manifest can be serialised to JSON and loaded back."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        artifact_dir = artifacts_root / "artifacts" / manifest.id
        loaded = ArtifactManifest.from_json_file(artifact_dir / "manifest.json")

        assert loaded.id == manifest.id
        assert loaded.model_binary_path == manifest.model_binary_path
        assert loaded.features == manifest.features
        assert loaded.checksums == manifest.checksums

    def test_create_rejects_missing_model_dir(self, artifacts_root, sample_config, sample_predictions, sample_labels):
        with pytest.raises(FileNotFoundError, match="Model directory not found"):
            create_artifact(
                model_dir="/nonexistent/path",
                config=sample_config,
                predictions=sample_predictions,
                labels=sample_labels,
                snapshot_id="test_snap",
            )

    def test_create_rejects_empty_model_dir(self, artifacts_root, tmp_path, sample_config, sample_predictions, sample_labels):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No .pkl"):
            create_artifact(
                model_dir=empty_dir,
                config=sample_config,
                predictions=sample_predictions,
                labels=sample_labels,
                snapshot_id="test_snap",
            )

    def test_checksums_match_actual_files(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Stored checksums must match the actual file hashes."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        artifact_dir = artifacts_root / "artifacts" / manifest.id
        for fname, expected in manifest.checksums.items():
            actual = _sha256_file(artifact_dir / fname)
            assert actual == expected, f"Checksum mismatch for {fname}"


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------


class TestValidateArtifact:
    """Test validate_artifact checks."""

    def test_valid_artifact_passes(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )
        result = validate_artifact(manifest.id)
        assert result.id == manifest.id

    def test_validation_rejects_unknown_id(self, artifacts_root):
        with pytest.raises(ArtifactValidationError, match="not found"):
            validate_artifact("nonexistent_id_12345")

    def test_validation_rejects_missing_fields(self, artifacts_root):
        """A manifest with empty required fields must fail."""
        bad = ArtifactManifest(id="bad1", model_binary_path="")
        _REGISTRY = get_registry()
        from src.models import artifact as _mod
        _mod._REGISTRY[bad.id] = bad

        with pytest.raises(ArtifactValidationError, match="missing required fields"):
            validate_artifact(bad.id)

    def test_validation_rejects_checksum_mismatch(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Tampering with a file after creation must fail checksum validation."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        # Tamper with the predictions file
        artifact_dir = artifacts_root / "artifacts" / manifest.id
        pred_file = artifact_dir / "predictions.csv"
        pred_file.write_text("TAMPERED", encoding="utf-8")

        with pytest.raises(ArtifactValidationError, match="checksum mismatch"):
            validate_artifact(manifest.id)

    def test_validation_rejects_missing_file(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Deleting a file after creation must fail validation."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        # Delete a checksummed file
        artifact_dir = artifacts_root / "artifacts" / manifest.id
        (artifact_dir / "labels.csv").unlink()

        with pytest.raises(ArtifactValidationError, match="referenced file missing"):
            validate_artifact(manifest.id)


# ---------------------------------------------------------------------------
# Tests: Registration
# ---------------------------------------------------------------------------


class TestRegisterArtifact:
    """Test register_artifact gating."""

    def test_register_requires_valid_artifact(self, artifacts_root):
        """Registering an unknown artifact must raise."""
        with pytest.raises(ArtifactValidationError, match="not found"):
            register_artifact("nonexistent_id_99999")

    def test_register_creates_marker_file(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Successful registration creates a .registered marker."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )
        register_artifact(manifest.id, **_eligibility_results(manifest.id))

        marker = artifacts_root / "artifacts" / manifest.id / ".registered"
        assert marker.exists()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["artifact_id"] == manifest.id
        assert "registered_at" in data

    def test_register_rejects_artifact_with_bad_checksum(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """Registration must fail if checksums are tampered."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )

        # Tamper
        artifact_dir = artifacts_root / "artifacts" / manifest.id
        (artifact_dir / "predictions.csv").write_text("TAMPERED", encoding="utf-8")

        with pytest.raises(ArtifactValidationError, match="checksum mismatch"):
            register_artifact(manifest.id, **_eligibility_results(manifest.id))

    def test_registered_artifact_appears_in_registry(
        self, artifacts_root, model_dir, sample_config, sample_predictions, sample_labels
    ):
        """After registration, the artifact is in the in-memory registry."""
        manifest = create_artifact(
            model_dir=model_dir,
            config=sample_config,
            predictions=sample_predictions,
            labels=sample_labels,
            snapshot_id="test_snap",
        )
        register_artifact(manifest.id, **_eligibility_results(manifest.id))

        reg = get_registry()
        assert manifest.id in reg
        assert reg[manifest.id].benchmark == "QQQ"


# ---------------------------------------------------------------------------
# Tests: ArtifactManifest dataclass
# ---------------------------------------------------------------------------


class TestArtifactManifest:
    """Test the manifest dataclass directly."""

    def test_frozen(self):
        m = ArtifactManifest(id="x", model_binary_path="m.pkl")
        with pytest.raises(AttributeError):
            m.id = "y"  # type: ignore[misc]

    def test_to_dict_roundtrip(self):
        m = ArtifactManifest(
            id="test123",
            model_binary_path="model.pkl",
            config={"a": 1},
            features=["f1", "f2"],
            snapshot_id="snap",
            train_window=["2020-01-01", "2024-01-01"],
            valid_window=["2024-01-01", "2024-06-01"],
            test_window=["2024-06-01", "2025-01-01"],
            benchmark="QQQ",
            costs={"open": 0.001},
            code_revision="abc123",
            uv_lock_hash="def456",
            python_version="3.12.0",
            seeds={"numpy": 42},
            predictions_path="p.csv",
            labels_path="l.csv",
            diagnostics_path="d.json",
            checksums={"model.pkl": "aabb"},
        )
        d = m.to_dict()
        assert d["id"] == "test123"
        assert d["benchmark"] == "QQQ"

        loaded = ArtifactManifest(**d)
        assert loaded.id == m.id
        assert loaded.checksums == m.checksums

    def test_missing_required_catches_empties(self):
        m = ArtifactManifest(id="x", model_binary_path="")
        missing = m.missing_required()
        assert "model_binary_path" in missing
        assert "id" not in missing

    def test_save_and_load(self, tmp_path):
        m = ArtifactManifest(
            id="roundtrip",
            model_binary_path="m.pkl",
            config={"k": "v"},
            snapshot_id="s1",
            train_window=["a", "b"],
            valid_window=["c", "d"],
            test_window=["e", "f"],
            benchmark="SPY",
            code_revision="rev",
            uv_lock_hash="hash",
            python_version="3.12",
            predictions_path="p.csv",
            labels_path="l.csv",
            diagnostics_path="d.json",
            checksums={"m.pkl": "aaa"},
        )
        p = tmp_path / "manifest.json"
        m.save(p)
        loaded = ArtifactManifest.from_json_file(p)
        assert loaded.id == "roundtrip"
        assert loaded.benchmark == "SPY"
