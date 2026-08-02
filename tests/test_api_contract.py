"""Migration contract for the temporary FastAPI adapter host.

The supported browser product is the static/local Research Artifact Studio.
These tests cover only routers still awaiting domain extraction and assert that
first-wave browser/system routes remain retired.
"""

import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from api_server import app

    return TestClient(app)


@pytest.fixture
def auth_headers():
    creds = base64.b64encode(b"admin:alpha2026").decode()
    return {"Authorization": f"Basic {creds}"}


class TestMigrationHost:
    def test_health_declares_deprecation(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "deprecated"
        assert "version" in payload

    def test_version_declares_adapter_retirement(self, client):
        response = client.get("/api/public/version")
        assert response.status_code == 200
        assert response.json()["status"] == "legacy-adapter-retirement"

    @pytest.mark.parametrize(
        "path",
        [
            "/api/system/docs/main",
            "/api/system/paths",
            "/api/jobs",
            "/api/reports",
            "/api/artifacts/dashboard-db",
            "/api/arena",
            "/api/strategy",
            "/api/agent/chat",
            "/api/tools",
        ],
    )
    def test_first_wave_routes_are_absent(self, client, auth_headers, path):
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 404


class TestResearchAdapter:
    def test_list_runs_returns_schema(self, client, auth_headers):
        response = client.get("/api/research/runs", headers=auth_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert isinstance(payload["runs"], list)
        assert isinstance(payload["total"], int)

    def test_list_runs_requires_auth(self, client):
        assert client.get("/api/research/runs").status_code == 401

    def test_start_run_requires_body(self, client, auth_headers):
        assert client.post("/api/research/run", headers=auth_headers).status_code == 422

    def test_start_run_delegates_to_research_workflow(self, client, auth_headers, monkeypatch):
        captured = []

        class FakeWorkflow:
            def run(self, request):
                captured.append(request)
                return type("Result", (), {"run_id": request.run_id})()

        monkeypatch.setattr(
            "src.api.routers.research.create_research_workflow",
            lambda: FakeWorkflow(),
        )

        response = client.post(
            "/api/research/run",
            json={"market": "cn", "goal": "test", "model_type": "lgbm"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert payload["run_id"]
        assert len(captured) == 1
        assert captured[0].market == "cn"
        assert captured[0].goal == "test"
        assert captured[0].model_type == "lgbm"

    def test_get_nonexistent_run(self, client, auth_headers):
        response = client.get("/api/research/runs/nonexistent_id", headers=auth_headers)
        assert response.status_code == 404


class TestRemainingReadAdapters:
    def test_decay_status_schema(self, client, auth_headers):
        response = client.get("/api/decay/check?market=cn", headers=auth_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "ok" in payload
        assert "total_factors" in payload
        assert "status_distribution" in payload

    def test_nonexistent_decay_factor_is_404(self, client, auth_headers):
        response = client.get("/api/decay/factor/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    def test_portfolio_config_schema(self, client, auth_headers):
        response = client.get("/api/portfolio/config", headers=auth_headers)
        assert response.status_code == 200, response.text
        config = response.json()["config"]
        for key in (
            "max_industry_weight",
            "max_pairwise_correlation",
            "max_single_factor_exposure",
            "min_daily_volume_usd",
            "max_daily_turnover",
            "consecutive_loss_days",
        ):
            assert key in config

    def test_data_status_schema(self, client, auth_headers):
        response = client.get("/api/data/status", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestRemainingAdapterFailurePaths:
    @pytest.mark.parametrize(
        "payload",
        [
            {"positions": {}, "market": "cn"},
            {"positions": {"000001": 1.0}, "market": "invalid"},
            {"positions": {"000001": 5.0, "600519": -2.0}, "market": "cn"},
        ],
    )
    def test_invalid_portfolio_requests_fail_closed(self, client, auth_headers, payload):
        response = client.post("/api/portfolio/check", json=payload, headers=auth_headers)
        assert response.status_code == 422
        assert response.json()["code"] == "API_VALIDATION_ERROR"

    def test_portfolio_requires_artifact_identities(self, client, auth_headers):
        response = client.post(
            "/api/portfolio/check",
            json={
                "positions": {"000001": 0.1, "600519": 0.2},
                "market": "cn",
                "portfolio_value": 100000,
            },
            headers=auth_headers,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "API_VALIDATION_ERROR"

    def test_remaining_adapters_require_authentication(self, client):
        for path in (
            "/api/research/runs",
            "/api/decay/check",
            "/api/portfolio/config",
            "/api/data/status",
        ):
            assert client.get(path).status_code == 401


def test_workflow_command_envelope_remains_cli_owned():
    from src.workflows.commands import WorkflowCommandEnvelope

    for mode in ("train", "rebacktest"):
        envelope = WorkflowCommandEnvelope.from_backtest_request(market="cn", mode=mode)
        for python_exe in ("python", "uv run python", ["uv", "run", "python"]):
            argv = envelope.to_argv(python_exe=python_exe)
            assert all(" " not in token for token in argv)
