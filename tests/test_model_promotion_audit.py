"""Audit model promotion: gate checks, stage detection, and error handling.

Tests that:
- Promotion to STAGING does not run RECOMMENDED gates
- Promotion to RECOMMENDED returns structured gate_failures (not 409)
- Frontend stage detection uses actual stage field, not description parsing
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestModelPromotionGates:
    """Test promotion gate behavior."""

    def test_staging_promotion_does_not_run_recommended_gates(self):
        """Promoting to STAGING should succeed without checking RECOMMENDED gates."""
        from src.assistant.services.model_service import ModelService

        mock_index = MagicMock()
        mock_index.get_version.return_value = {
            "id": "test-model",
            "metrics": {"sharpe": 1.0},
        }
        mock_index.update_version.return_value = True

        service = ModelService(project_root=PROJECT_ROOT, model_index=mock_index)

        # Promoting to STAGING should not check walk-forward gates
        result = service.promote_model("test-model", "STAGING")
        assert result.get("ok") is True

    def test_recommended_promotion_returns_gate_failures(self):
        """Promoting to RECOMMENDED without meeting gates should return gate_failures."""
        from src.assistant.services.model_service import ModelService

        mock_index = MagicMock()
        mock_index.get_version.return_value = {
            "id": "test-model",
            "metrics": {"sharpe": 1.0, "annualized_return": 0.1},
        }

        service = ModelService(project_root=PROJECT_ROOT, model_index=mock_index)

        result = service.promote_model("test-model", "RECOMMENDED")
        # Should fail because walk-forward validation is missing
        assert result.get("ok") is False
        assert "gate_failures" in result
        assert len(result["gate_failures"]) > 0

    def test_promotion_endpoint_returns_200_on_failure(self):
        """The /api/models/promote endpoint should return 200 with ok=False, not 409."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.routers.models import router

        app = FastAPI()
        app.include_router(router, prefix="/api/models")

        # Mock the dependencies
        with patch("src.api.routers.models.get_model_index") as mock_index, \
             patch("src.api.routers.models.get_model_service") as mock_service:
            mock_index.return_value.get_version.return_value = {"id": "test-model"}
            mock_service.return_value.promote_model.return_value = {
                "ok": False,
                "gate_failures": ["missing walk-forward validation"],
            }

            client = TestClient(app)
            response = client.post(
                "/api/models/promote",
                json={
                    "schema_version": "v1",
                    "artifact_id": "test-model",
                    "stage": "RECOMMENDED",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is False
            assert data["code"] == "MODEL_PROMOTION_CONFLICT"
            assert "gate_failures" in data


class TestFrontendStageDetection:
    """Test that frontend stage detection is correct."""

    def test_parse_stage_function_removed(self):
        """The frontend should NOT use parseStage(description) to derive stage."""
        models_page = Path(PROJECT_ROOT) / "qlib-dashboard" / "src" / "pages" / "ModelsPage.tsx"
        content = models_page.read_text(encoding="utf-8")

        # parseStage function should be removed
        assert "function parseStage" not in content, (
            "ModelsPage still has parseStage function that derives stage from description. "
            "Use v.stage field instead."
        )

    def test_models_page_uses_stage_field(self):
        """ModelsPage should use v.stage field, not description parsing."""
        models_page = Path(PROJECT_ROOT) / "qlib-dashboard" / "src" / "pages" / "ModelsPage.tsx"
        content = models_page.read_text(encoding="utf-8")

        # Should use v.stage for stage detection
        assert "v.stage" in content, (
            "ModelsPage should use v.stage field for stage detection"
        )

    def test_toggle_promote_uses_stage_field(self):
        """togglePromote should use v.stage, not description.includes('RECOMMENDED')."""
        models_page = Path(PROJECT_ROOT) / "qlib-dashboard" / "src" / "pages" / "ModelsPage.tsx"
        content = models_page.read_text(encoding="utf-8")

        # Should NOT use description.includes for RECOMMENDED detection
        assert 'description").includes("RECOMMENDED")' not in content, (
            "togglePromote still uses description.includes('RECOMMENDED'). "
            "Use v.stage field instead."
        )

    def test_model_version_has_stage_field(self):
        """The ModelVersion type should have a stage field."""
        api_types = Path(PROJECT_ROOT) / "qlib-dashboard" / "src" / "lib" / "api-types.ts"
        content = api_types.read_text(encoding="utf-8")

        # Check that ModelVersion has stage field
        assert "stage" in content


# Need to import MagicMock after defining the test class
from unittest.mock import MagicMock, patch
