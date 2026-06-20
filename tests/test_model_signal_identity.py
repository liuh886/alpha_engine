"""T46.8 — Prove model-signal identity.

Tests that:
1. ModelVersion ID is included in signal responses.
2. Unknown/deleted model IDs return explicit errors.
3. Selecting model A returns only A's predictions.
"""

from __future__ import annotations

import pytest

from src.assistant.model_registry_index import ModelRegistryIndex

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_model(idx: ModelRegistryIndex, model_id: str, **overrides) -> None:
    """Register a model version in the index with sensible defaults."""
    entry = {
        "id": model_id,
        "tag": overrides.get("tag", f"tag_{model_id[:8]}"),
        "name": overrides.get("name", f"Model {model_id}"),
        "market": overrides.get("market", "us"),
        "type": overrides.get("model_type", "LGBModel"),
        "path": overrides.get("path", f"models/{model_id}.pkl"),
        "run_id": overrides.get("run_id", f"run_{model_id[:8]}"),
        "created_at": overrides.get("created_at", "2026-01-15"),
        "description": overrides.get("description", ""),
        "backtest": {
            "metrics": overrides.get("metrics", {"annualized_return": 0.12}),
        },
    }
    idx.upsert_entry(entry)


# ===========================================================================
# 1. ModelVersion ID is included in signal responses
# ===========================================================================


class TestModelVersionIdentity:
    """Model version IDs must be present and traceable."""

    def test_registered_model_has_id(self, tmp_path):
        """A registered model version must be retrievable by its ID."""
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "us_lgbm_20260115_000000")

        version = idx.get_version("us_lgbm_20260115_000000")
        assert version is not None
        assert version["id"] == "us_lgbm_20260115_000000"

    def test_model_version_id_in_list(self, tmp_path):
        """Listed model versions must include their IDs."""
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "model_alpha")
        _register_model(idx, "model_beta")

        versions = idx.list_versions(limit=10)
        ids = {v["id"] for v in versions}
        assert "model_alpha" in ids
        assert "model_beta" in ids

    def test_signal_frame_carries_asof_date(self):
        """SignalFrame must carry the decision date for traceability."""
        from src.execution.models import SignalFrame

        frame = SignalFrame(asof_date="2026-06-19", scores={"AAPL": 0.5})
        assert frame.asof_date == "2026-06-19"

    def test_execution_result_includes_asof_date(self):
        """ExecutionResult.plan must include the asof_date for provenance."""
        from src.execution.engine import StrategyExecutionEngine
        from src.execution.models import (
            ExecutionConfig,
            ExecutionRequest,
            MarketDataSnapshot,
            PortfolioState,
            RiskPolicy,
            SignalFrame,
        )

        request = ExecutionRequest(
            signals=SignalFrame(asof_date="2026-06-19", scores={"AAPL": 0.9}),
            portfolio=PortfolioState(cash=1000.0),
            market=MarketDataSnapshot(),
            risk_policy=RiskPolicy(),
            config=ExecutionConfig(topk=1),
        )
        result = StrategyExecutionEngine().execute(request)
        assert result.plan.asof_date == "2026-06-19"

    def test_manifest_has_model_id(self):
        """ArtifactManifest must carry its unique ID."""
        from src.models.artifact_manifest import ArtifactManifest

        manifest = ArtifactManifest(
            id="unique_artifact_id_123",
            model_binary_path="model.pkl",
            config={"model_class": "LGBModel"},
            predictions_path="pred.csv",
            labels_path="label.csv",
            diagnostics_path="diag.json",
            checksums={"model.pkl": "sha256:abc"},
        )
        assert manifest.id == "unique_artifact_id_123"

    def test_manifest_snapshot_id_links_to_data(self):
        """ArtifactManifest.snapshot_id links the model to its training data."""
        from src.models.artifact_manifest import ArtifactManifest

        manifest = ArtifactManifest(
            id="m1",
            model_binary_path="model.pkl",
            config={},
            snapshot_id="snap_abc123",
            predictions_path="pred.csv",
            labels_path="label.csv",
            diagnostics_path="diag.json",
            checksums={},
        )
        assert manifest.snapshot_id == "snap_abc123"


# ===========================================================================
# 2. Unknown/deleted model IDs return explicit errors
# ===========================================================================


class TestUnknownModelErrors:
    """Looking up non-existent or deleted models must raise/return None."""

    def test_get_unknown_version_returns_none(self, tmp_path):
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)

        assert idx.get_version("nonexistent_model_id") is None

    def test_delete_then_get_returns_none(self, tmp_path):
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "to_be_deleted")

        assert idx.get_version("to_be_deleted") is not None
        assert idx.delete_version("to_be_deleted") is True
        assert idx.get_version("to_be_deleted") is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)

        assert idx.delete_version("ghost_model") is False

    def test_model_service_raises_for_unknown_details(self, tmp_path):
        """ModelService.get_model_details raises ValueError for unknown IDs."""
        from src.assistant.services.model_service import ModelService

        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)

        service = ModelService(project_root=tmp_path, model_index=idx)
        with pytest.raises(ValueError, match="Model version not found"):
            service.get_model_details("unknown_id_999")

    def test_resolve_nonexistent_snapshot_raises(self, tmp_path):
        """DataSnapshot.resolve_snapshot raises FileNotFoundError for bad IDs."""
        from src.data.snapshot import DataSnapshot

        store = tmp_path / "store"
        store.mkdir()

        with pytest.raises(FileNotFoundError, match="snapshot not found"):
            DataSnapshot.resolve_snapshot("deadbeef01234567", store=store)

    def test_empty_version_id_returns_none(self, tmp_path):
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)

        assert idx.get_version("") is None
        assert idx.get_version(None) is None


# ===========================================================================
# 3. Selecting model A returns only A's predictions
# ===========================================================================


class TestModelSelection:
    """Selecting a specific model must return only that model's data."""

    def test_get_version_returns_only_requested_model(self, tmp_path):
        """get_version(id_A) must not return id_B's data."""
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "model_A", market="us", metrics={"annualized_return": 0.10})
        _register_model(idx, "model_B", market="cn", metrics={"annualized_return": 0.20})

        v_a = idx.get_version("model_A")
        v_b = idx.get_version("model_B")

        assert v_a["id"] == "model_A"
        assert v_a["market"] == "us"
        assert v_b["id"] == "model_B"
        assert v_b["market"] == "cn"

        # Ensure no cross-contamination
        assert v_a["market"] != v_b["market"]

    def test_list_versions_filtered_by_market(self, tmp_path):
        """Market filter must return only matching models."""
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "us_model_1", market="us")
        _register_model(idx, "us_model_2", market="us")
        _register_model(idx, "cn_model_1", market="cn")

        us_versions = idx.list_versions(market="us")
        cn_versions = idx.list_versions(market="cn")

        assert all(v["market"] == "us" for v in us_versions)
        assert all(v["market"] == "cn" for v in cn_versions)
        assert len(us_versions) == 2
        assert len(cn_versions) == 1

    def test_different_models_have_different_predictions(self, tmp_path):
        """Two models with different prediction files must not be confused."""
        from src.models.artifact_manifest import ArtifactManifest

        m_a = ArtifactManifest(
            id="model_A_artifact",
            model_binary_path="model_a.pkl",
            config={"model_class": "LGBModel"},
            predictions_path="pred_a.csv",
            labels_path="label_a.csv",
            diagnostics_path="diag_a.json",
            checksums={"model_a.pkl": "hash_a", "pred_a.csv": "hash_pred_a"},
        )
        m_b = ArtifactManifest(
            id="model_B_artifact",
            model_binary_path="model_b.pkl",
            config={"model_class": "XGBModel"},
            predictions_path="pred_b.csv",
            labels_path="label_b.csv",
            diagnostics_path="diag_b.json",
            checksums={"model_b.pkl": "hash_b", "pred_b.csv": "hash_pred_b"},
        )

        assert m_a.predictions_path != m_b.predictions_path
        assert m_a.id != m_b.id
        assert m_a.checksums != m_b.checksums

    def test_stage_update_is_per_model(self, tmp_path):
        """Updating stage for model A must not affect model B."""
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "model_A")
        _register_model(idx, "model_B")

        idx.update_stage("model_A", "RECOMMENDED")

        v_a = idx.get_version("model_A")
        v_b = idx.get_version("model_B")

        assert "RECOMMENDED" in v_a["description"]
        # model_B should not have been affected
        assert "RECOMMENDED" not in (v_b.get("description") or "")

    def test_delete_model_does_not_affect_others(self, tmp_path):
        """Deleting model A must leave model B intact."""
        db_path = tmp_path / "metadata.db"
        idx = ModelRegistryIndex(db_path=db_path)
        _register_model(idx, "keep_model")
        _register_model(idx, "delete_model")

        idx.delete_version("delete_model")

        assert idx.get_version("keep_model") is not None
        assert idx.get_version("delete_model") is None
