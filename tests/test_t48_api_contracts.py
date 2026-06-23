"""T48.8 contract tests: validation, route ordering, bounded limits, degraded state.

Exercises each success, validation, authorization, conflict, degraded, and
failure path for the API contracts introduced in T48.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import backtest, data, models, system
from src.api.schemas.release_contracts import (
    BacktestRunRequestV1,
    DataUpdateRequestV1,
    TrainingRunRequestV1,
)

# ---------------------------------------------------------------------------
# Lightweight stubs for dependency injection
# ---------------------------------------------------------------------------


class _ModelIndex:
    def __init__(self, version: dict | None = None):
        self.version = version

    def list_versions(self, *, limit: int, market: str | None = None) -> list[dict]:
        return []

    def get_version(self, artifact_id: str) -> dict | None:
        return self.version if self.version and self.version["id"] == artifact_id else None


class _ModelService:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def get_model_details(self, artifact_id: str) -> dict:
        self.calls.append(("details", artifact_id))
        return {"id": artifact_id}


class _JobCoordinator:
    def submit_response(self, job: dict) -> dict:
        return {
            "job_id": job.get("id", "test-job"),
            "status": "queued",
            "started_at": 123456789.0,
            "source": "test",
            "intent": "test",
            "next_action": "wait",
        }


class _DataService:
    def create_update_job_from_payload(self, payload: dict) -> dict:
        return {"id": "data-job-1", "type": "data_update"}


class _BacktestService:
    def create_job_from_payload(self, payload: dict) -> dict:
        return {"id": "bt-job-1", "type": "backtest"}

    def delete_run(self, run_id: str) -> bool:
        return run_id != "missing"


class _TrainingService:
    def create_job_from_payload(self, payload: dict) -> dict:
        return {"id": "train-job-1", "type": "training"}


class _RunIndex:
    def list_runs(self, *, market=None, limit=50, offset=0) -> list[dict]:
        return [
            {"id": f"run-{i}", "name": f"Run {i}", "market": "us", "date": "2026-01-01"}
            for i in range(min(limit, 3))
        ]

    def get_run(self, run_id: str) -> dict | None:
        return {"id": run_id, "tag": "Test", "market": "us"} if run_id != "missing" else None


class _CurveIndex:
    def list_curve(self, run_id: str, limit: int = 2000) -> list[dict]:
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model_client() -> TestClient:
    app = FastAPI()
    app.include_router(models.router, prefix="/api/models")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def data_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(data, "get_data_service", lambda: _DataService())
    monkeypatch.setattr(data, "get_job_coordinator", lambda: _JobCoordinator())
    app = FastAPI()
    app.include_router(data.router, prefix="/api/data")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def backtest_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(backtest, "get_backtest_service", lambda: _BacktestService())
    monkeypatch.setattr(backtest, "get_training_service", lambda: _TrainingService())
    monkeypatch.setattr(backtest, "get_job_coordinator", lambda: _JobCoordinator())
    monkeypatch.setattr(backtest, "get_run_index", lambda: _RunIndex())
    monkeypatch.setattr(backtest, "get_curve_index", lambda: _CurveIndex())
    app = FastAPI()
    app.include_router(backtest.router, prefix="/api/backtest")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def system_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(system, "get_job_coordinator", lambda: _JobCoordinator())
    app = FastAPI()
    app.include_router(system.router, prefix="/api/system")
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. Unknown field rejection (422)
# ---------------------------------------------------------------------------


class TestUnknownFieldRejection:
    """StrictRequestV1 with extra='forbid' must reject unknown fields."""

    def test_model_promote_rejects_unknown_fields(self, model_client):
        response = model_client.post(
            "/api/models/promote",
            json={
                "schema_version": "v1",
                "artifact_id": "model-1",
                "stage": "RECOMMENDED",
                "unexpected_field": True,
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_model_delete_rejects_unknown_fields(self, model_client):
        response = model_client.post(
            "/api/models/delete",
            json={
                "schema_version": "v1",
                "artifact_id": "model-1",
                "extra": "not allowed",
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_data_update_rejects_unknown_fields(self, data_client):
        response = data_client.post(
            "/api/data/update",
            json={"schema_version": "v1", "rogue": True},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_backtest_run_rejects_unknown_fields(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/run",
            json={"schema_version": "v1", "market": "us", "bad_field": 1},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_training_run_rejects_unknown_fields(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/train/run",
            json={"schema_version": "v1", "market": "us", "tag": "test", "junk": 1},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 2. Unknown stage rejection (422)
# ---------------------------------------------------------------------------


class TestUnknownStageRejection:
    """ModelStage enum must reject stages not in {STAGING, RECOMMENDED}."""

    @pytest.mark.parametrize("stage", ["ROOT", "PRODUCTION", "ARCHIVED", "", "staging"])
    def test_model_promote_rejects_unknown_stage(self, model_client, stage):
        response = model_client.post(
            "/api/models/promote",
            json={"schema_version": "v1", "artifact_id": "model-1", "stage": stage},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 3. Unknown market rejection (422)
# ---------------------------------------------------------------------------


class TestUnknownMarketRejection:
    """Market enum must reject markets not in {cn, us}."""

    @pytest.mark.parametrize("market", ["crypto", "eu", "japan", "", "US", "CN"])
    def test_backtest_run_rejects_unknown_market(self, backtest_client, market):
        response = backtest_client.post(
            "/api/backtest/run",
            json={"schema_version": "v1", "market": market},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    @pytest.mark.parametrize("market", ["crypto", "eu", "japan", "", "US", "CN"])
    def test_training_run_rejects_unknown_market(self, backtest_client, market):
        response = backtest_client.post(
            "/api/backtest/train/run",
            json={"schema_version": "v1", "market": market, "tag": "test-tag"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 4. /api/models/health reaches health handler (not /{version_id})
# ---------------------------------------------------------------------------


class TestModelHealthRouteOrdering:
    """Static /health route must take precedence over /{artifact_id}."""

    def test_health_endpoint_reaches_health_handler(self, model_client, monkeypatch):
        row = {
            "run_id": "run-1",
            "market": "us",
            "created_at": datetime.now().isoformat(),
        }

        class _Connection:
            def execute(self, _query):
                return self

            def fetchone(self):
                return row

        index = _ModelIndex()
        index._connect = lambda: nullcontext(_Connection())
        monkeypatch.setattr(models, "get_model_index", lambda: index)
        monkeypatch.setattr(
            models,
            "_check_prediction_freshness",
            lambda *_args: {"exists": True, "age_days": 0, "coverage": 2},
        )
        monkeypatch.setattr(models, "_check_qlib_data", lambda: {"available": True})

        response = model_client.get("/api/models/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert "checks" in body
        assert "recommended_model" in body["checks"]

    def test_health_is_not_intercepted_by_artifact_route(self, model_client, monkeypatch):
        """'health' should NOT match /{artifact_id} pattern.

        If 'health' matched /{artifact_id}, the handler would try to load
        artifact 'health' and return 404 with code='MODEL_ARTIFACT_NOT_FOUND'.
        The correct behavior is reaching the health handler, which returns
        a response containing 'checks' (200 if healthy, 503 if degraded).
        """
        monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex())
        monkeypatch.setattr(models, "get_model_service", lambda: _ModelService())

        response = model_client.get("/api/models/health")
        body = response.json()
        # Must reach the health handler (has 'checks'), NOT the artifact handler
        assert "checks" in body
        assert response.status_code in (200, 503)
        # Must NOT be an artifact-not-found response
        assert body.get("code") != "MODEL_ARTIFACT_NOT_FOUND"


# ---------------------------------------------------------------------------
# 5. List endpoint limit bounds
# ---------------------------------------------------------------------------


class TestListEndpointBounds:
    """List endpoints must enforce limit bounds."""

    def test_model_list_rejects_limit_below_1(self, model_client, monkeypatch):
        monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex())
        response = model_client.get("/api/models?limit=0")
        assert response.status_code == 422

    def test_model_list_rejects_limit_above_200(self, model_client, monkeypatch):
        monkeypatch.setattr(models, "get_model_index", lambda: _ModelIndex())
        response = model_client.get("/api/models?limit=201")
        assert response.status_code == 422

    def test_backtest_list_rejects_limit_below_1(self, backtest_client):
        response = backtest_client.get("/api/backtest/?limit=0")
        assert response.status_code == 422

    def test_backtest_list_rejects_limit_above_500(self, backtest_client):
        response = backtest_client.get("/api/backtest/?limit=501")
        assert response.status_code == 422

    def test_backtest_list_accepts_valid_limit(self, backtest_client):
        response = backtest_client.get("/api/backtest/?limit=10")
        assert response.status_code == 200

    def test_system_thought_stream_rejects_limit_below_1(
        self, system_client, monkeypatch, tmp_path
    ):
        # Thought stream reads from file; stub it to avoid file dependency
        monkeypatch.setattr("src.common.paths.ARTIFACTS_DIR", tmp_path)
        response = system_client.get("/api/system/thought_stream?limit=0")
        assert response.status_code == 422

    def test_system_thought_stream_rejects_limit_above_500(
        self, system_client, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("src.common.paths.ARTIFACTS_DIR", tmp_path)
        response = system_client.get("/api/system/thought_stream?limit=501")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 6. Missing artifact identity in mutations returns 400/422
# ---------------------------------------------------------------------------


class TestMissingArtifactIdentity:
    """Mutation operations must require explicit identity fields."""

    def test_model_promote_requires_artifact_id(self, model_client):
        response = model_client.post(
            "/api/models/promote",
            json={"schema_version": "v1", "stage": "RECOMMENDED"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_model_delete_requires_artifact_id(self, model_client):
        response = model_client.post(
            "/api/models/delete",
            json={"schema_version": "v1"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_backtest_run_requires_market(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/run",
            json={"schema_version": "v1"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_training_run_requires_market_and_tag(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/train/run",
            json={"schema_version": "v1"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_training_run_requires_tag(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/train/run",
            json={"schema_version": "v1", "market": "us"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 7. Readiness endpoint returns 503 when snapshot is missing
# ---------------------------------------------------------------------------


class TestReadinessDegradedState:
    """Readiness probe must return 503 when critical dependencies are unavailable."""

    def test_readiness_returns_503_when_snapshot_missing(self, monkeypatch):
        """When no snapshot exists, readiness must return 503."""
        from api_server import app

        # Stub snapshot to return None (no snapshot available)
        def _get_latest_snapshot():
            return None

        # Stub model registry to succeed
        class _FakeIndex:
            def list_versions(self, limit=1):
                return [{"id": "fake"}]

        # Stub dashboard DB path
        monkeypatch.setattr(
            "src.data.snapshot.DataSnapshot.get_latest_snapshot",
            staticmethod(_get_latest_snapshot),
            raising=False,
        )
        monkeypatch.setattr(
            "src.assistant.model_registry_index.ModelRegistryIndex",
            lambda **kwargs: _FakeIndex(),
            raising=False,
        )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/health/ready")

        # Should be 503 because snapshot is unavailable
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["snapshot"]["status"] == "unavailable"


# ---------------------------------------------------------------------------
# 8. Schema version enforcement
# ---------------------------------------------------------------------------


class TestSchemaVersionEnforcement:
    """Requests must include schema_version='v1'."""

    def test_model_promote_requires_v1_schema(self, model_client):
        response = model_client.post(
            "/api/models/promote",
            json={"schema_version": "v2", "artifact_id": "model-1", "stage": "STAGING"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "API_VALIDATION_ERROR"

    def test_data_update_defaults_to_v1(self, data_client):
        """DataUpdateRequestV1 should default schema_version to v1."""
        response = data_client.post(
            "/api/data/update",
            json={},
        )
        # Should succeed (v1 is default, no unknown fields)
        print(response.json() if response.content else response.content)
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 9. Contract envelope shape verification
# ---------------------------------------------------------------------------


class TestContractEnvelopeShape:
    """Verify that error responses use the stable envelope format."""

    def test_validation_error_has_ok_false(self, model_client):
        response = model_client.post(
            "/api/models/promote",
            json={"schema_version": "v1", "artifact_id": "model-1", "stage": "INVALID"},
        )
        body = response.json()
        assert body["ok"] is False
        assert "code" in body
        assert "detail" in body

    def test_success_response_has_ok_true(self, model_client, monkeypatch):
        index = _ModelIndex()
        monkeypatch.setattr(models, "get_model_index", lambda: index)
        monkeypatch.setattr(models, "get_model_service", lambda: _ModelService())

        response = model_client.get("/api/models")
        body = response.json()
        assert body["ok"] is True
        assert "schema_version" in body


# ---------------------------------------------------------------------------
# 10. Backtest mutation success paths
# ---------------------------------------------------------------------------


class TestBacktestMutationSuccess:
    """Backtest mutations should succeed with valid payloads."""

    def test_backtest_run_success(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/run",
            json={"schema_version": "v1", "market": "us"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "job_id" in body

    def test_training_run_success(self, backtest_client):
        response = backtest_client.post(
            "/api/backtest/train/run",
            json={"schema_version": "v1", "market": "us", "tag": "test-run-001"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "job_id" in body

    def test_backtest_delete_success(self, backtest_client):
        response = backtest_client.delete("/api/backtest/runs/run-1")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True

    def test_backtest_delete_missing_returns_404(self, backtest_client):
        response = backtest_client.delete("/api/backtest/runs/missing")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 11. Public endpoints return correct response shapes
# ---------------------------------------------------------------------------


class TestPublicEndpointShapes:
    """Public endpoints must conform to their response models."""

    def test_health_returns_status_and_version(self):
        from api_server import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_public_health_matches_health(self):
        from api_server import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/public/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_public_version_returns_version_and_status(self):
        from api_server import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/public/version")
        assert response.status_code == 200
        body = response.json()
        assert "version" in body
        assert body["status"] == "stable"

    def test_liveness_returns_alive(self):
        from api_server import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/health/live")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "alive"


# ---------------------------------------------------------------------------
# 12. Pydantic model unit tests
# ---------------------------------------------------------------------------


class TestPydanticModelContracts:
    """Unit tests for the Pydantic request models directly."""

    def test_data_update_defaults(self):
        req = DataUpdateRequestV1()
        assert req.schema_version == "v1"
        assert req.full is False
        assert req.market == "all"
        assert req.start == "2020-01-01"
        assert req.lookback_days == 30

    def test_data_update_lookback_bounds(self):
        with pytest.raises(Exception):
            DataUpdateRequestV1(lookback_days=-1)
        with pytest.raises(Exception):
            DataUpdateRequestV1(lookback_days=366)

    def test_backtest_run_requires_market(self):
        with pytest.raises(Exception):
            BacktestRunRequestV1()

    def test_backtest_run_valid_market(self):
        req = BacktestRunRequestV1(market="us")
        assert req.market.value == "us"
        assert req.model_type == "lgbm"

    def test_training_run_requires_tag(self):
        with pytest.raises(Exception):
            TrainingRunRequestV1(market="us")

    def test_training_run_valid(self):
        req = TrainingRunRequestV1(market="cn", tag="my-tag")
        assert req.market.value == "cn"
        assert req.tag == "my-tag"

    def test_training_run_rejects_invalid_tag_pattern(self):
        with pytest.raises(Exception):
            TrainingRunRequestV1(market="us", tag="../escape")
