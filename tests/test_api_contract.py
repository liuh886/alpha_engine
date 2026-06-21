"""Contract tests for API endpoints using FastAPI TestClient.

These tests verify schema, authentication, error paths, and data semantics
without requiring a running server.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    """Create FastAPI test client."""
    from fastapi.testclient import TestClient

    # Import the app - this triggers all router registrations
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from api_server import app

    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return valid auth headers."""
    import base64

    creds = base64.b64encode(b"admin:alpha2026").decode()
    return {"Authorization": f"Basic {creds}"}


class TestHealthEndpoint:
    """Test health endpoint."""

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestResearchEndpoints:
    """Test research pipeline endpoints."""

    def test_list_runs_returns_schema(self, client, auth_headers):
        resp = client.get("/api/research/runs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "runs" in data
        assert "total" in data
        assert isinstance(data["runs"], list)

    def test_list_runs_requires_auth(self, client):
        resp = client.get("/api/research/runs")
        assert resp.status_code == 401

    def test_start_run_requires_body(self, client, auth_headers):
        resp = client.post("/api/research/run", headers=auth_headers)
        assert resp.status_code == 422  # Validation error

    def test_start_run_accepts_valid_body(self, client, auth_headers):
        resp = client.post(
            "/api/research/run",
            json={"market": "cn", "goal": "test", "model_type": "lgbm"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "run_id" in data

    def test_get_nonexistent_run(self, client, auth_headers):
        resp = client.get("/api/research/runs/nonexistent_id", headers=auth_headers)
        assert resp.status_code == 404


class TestDecayEndpoints:
    """Test decay monitoring endpoints."""

    def test_check_decay_returns_schema(self, client, auth_headers):
        resp = client.get("/api/decay/check?market=cn", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "total_factors" in data
        assert "status_distribution" in data

    def test_check_nonexistent_factor(self, client, auth_headers):
        resp = client.get("/api/decay/factor/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


class TestPortfolioEndpoints:
    """Test portfolio constraint endpoints."""

    def test_get_config_returns_schema(self, client, auth_headers):
        resp = client.get("/api/portfolio/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "config" in data
        assert "max_industry_weight" in data["config"]

    def test_check_portfolio_requires_artifact_identities(self, client, auth_headers):
        resp = client.post(
            "/api/portfolio/check",
            json={
                "positions": {"000001": 0.1, "600519": 0.2},
                "market": "cn",
                "portfolio_value": 100000,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "API_VALIDATION_ERROR"


class TestDataEndpoints:
    """Test data endpoints."""

    def test_data_status(self, client, auth_headers):
        resp = client.get("/api/data/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True


class TestAPIFailurePaths:
    """Test API error handling and failure paths."""

    def test_portfolio_empty_positions(self, client, auth_headers):
        """An empty portfolio cannot produce an operational risk decision."""
        resp = client.post(
            "/api/portfolio/check",
            json={"positions": {}, "market": "cn"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "API_VALIDATION_ERROR"

    def test_portfolio_invalid_market(self, client, auth_headers):
        """Unknown markets are rejected at the contract boundary."""
        resp = client.post(
            "/api/portfolio/check",
            json={"positions": {"000001": 1.0}, "market": "invalid"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "API_VALIDATION_ERROR"

    def test_decay_factor_not_found(self, client, auth_headers):
        """Non-existent factor should return 404."""
        resp = client.get("/api/decay/factor/this_factor_does_not_exist_xyz", headers=auth_headers)
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    def test_research_run_invalid_market(self, client, auth_headers):
        """Invalid market in research run should be handled."""
        resp = client.post(
            "/api/research/run",
            json={"market": "invalid", "goal": "test"},
            headers=auth_headers,
        )
        # Should not crash
        assert resp.status_code in (200, 400, 422, 500)

    def test_unauthenticated_endpoints_return_401(self, client):
        """All protected endpoints should return 401 without auth."""
        protected_paths = [
            "/api/research/runs",
            "/api/decay/check",
            "/api/portfolio/config",
            "/api/data/status",
        ]
        for path in protected_paths:
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} should require auth"

    def test_portfolio_check_with_extreme_weights(self, client, auth_headers):
        """Weights outside the declared position range are rejected."""
        resp = client.post(
            "/api/portfolio/check",
            json={
                "positions": {"000001": 5.0, "600519": -2.0},
                "market": "cn",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "API_VALIDATION_ERROR"


class TestPipelineFailureRecording:
    """Test that pipeline step failures are properly recorded."""

    def test_failed_step_persists_error(self, tmp_path):
        """Failed pipeline step should persist error message in run."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="failure test")
        run.start()

        with pytest.raises(RuntimeError, match="training exploded"):
            with run.step("train"):
                raise RuntimeError("training exploded")

        # Save and reload
        path = tmp_path / "failed_run.json"
        run.save(path)
        loaded = ResearchRun.load(path)

        train_step = loaded.get_step("train")
        assert train_step is not None
        assert train_step.status == StepStatus.FAILED
        assert "training exploded" in train_step.error

    def test_partial_completion_preserves_successful_steps(self, tmp_path):
        """Run with 2/3 successful steps should preserve the successful ones."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="partial test")
        run.start()

        with run.step("step1") as s:
            s.output = {"result": "ok"}

        with pytest.raises(ValueError):
            with run.step("step2"):
                raise ValueError("step2 failed")

        path = tmp_path / "partial_run.json"
        run.save(path)
        loaded = ResearchRun.load(path)

        assert loaded.get_step("step1").status == StepStatus.COMPLETED
        assert loaded.get_step("step1").output == {"result": "ok"}
        assert loaded.get_step("step2").status == StepStatus.FAILED
        assert "step2 failed" in loaded.get_step("step2").error

    def test_run_fail_sets_status(self):
        """run.fail() should set status and completed_at."""
        from src.research.pipeline import ResearchRun, StepStatus

        run = ResearchRun(market="cn", goal="fail test")
        run.start()
        run.fail("pipeline crashed")

        assert run.status == StepStatus.FAILED
        assert run.completed_at is not None
        assert "crashed" in run.recommendation


# ---------------------------------------------------------------------------
# Slice 2: System Router Command Registry tests
# ---------------------------------------------------------------------------


class TestSystemCommandRegistry:
    """Test that system router uses workflow command envelope."""

    def test_build_safe_command_workflow_actions(self):
        """train/backtest should use WorkflowCommandEnvelope with valid argv tokens."""
        from src.api.routers.system import _build_safe_command

        train_cmd = _build_safe_command("train", ["--market", "cn"])
        assert train_cmd is not None
        # Each element must be a separate argv token (F1 fix)
        assert train_cmd[0] in ("uv", "python")
        assert "-m" in train_cmd
        assert "src.orchestrator" in train_cmd
        assert "--market" in train_cmd
        # No element should contain spaces (no "uv run python" single string)
        assert all(" " not in tok for tok in train_cmd), (
            f"argv tokens must not contain spaces: {train_cmd}"
        )

        backtest_cmd = _build_safe_command("backtest", ["--market", "us"])
        assert backtest_cmd is not None
        assert "rebacktest" in backtest_cmd
        assert "--market" in backtest_cmd
        assert all(" " not in tok for tok in backtest_cmd)

    def test_build_safe_command_explicit_commands(self):
        """data_update/arena_settle should use explicit commands."""
        from src.api.routers.system import _build_safe_command

        data_cmd = _build_safe_command("data_update", [])
        assert data_cmd is not None
        assert "collect_data.py" in " ".join(data_cmd)

        arena_cmd = _build_safe_command("arena_settle", [])
        assert arena_cmd is not None
        assert "arena_settle.py" in " ".join(arena_cmd)

    def test_build_safe_command_invalid_returns_none(self):
        """Unknown task keys should return None."""
        from src.api.routers.system import _build_safe_command

        assert _build_safe_command("invalid_task", []) is None
        assert _build_safe_command("", []) is None

    def test_exec_rejects_invalid_task(self, client, auth_headers):
        """Invalid task should return 400."""
        resp = client.post(
            "/api/system/exec",
            json={"task": "invalid_task"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "Invalid task" in resp.json()["detail"]

    def test_all_argv_tokens_are_individual(self):
        """No argv token should contain spaces — each must be a separate element."""
        from src.workflows.commands import WorkflowCommandEnvelope

        for mode in ("train", "rebacktest"):
            env = WorkflowCommandEnvelope.from_backtest_request(market="cn", mode=mode)
            for python_exe in ("python", "uv run python", ["uv", "run", "python"]):
                argv = env.to_argv(python_exe=python_exe)
                for tok in argv:
                    assert " " not in tok, f"Token '{tok}' contains spaces in {mode} argv: {argv}"


# ---------------------------------------------------------------------------
# T44.4: Dashboard smoke tests (API-level, no browser required)
# ---------------------------------------------------------------------------


class TestDashboardSmoke:
    """Smoke tests for dashboard data endpoints."""

    def test_health_endpoint(self, client):
        """Health endpoint must return ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_system_paths_endpoint(self, client, auth_headers):
        """System paths must return project structure."""
        resp = client.get("/api/system/paths", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "project_root" in data["paths"]

    def test_data_status_endpoint(self, client, auth_headers):
        """Data status must return market data info."""
        resp = client.get("/api/data/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_portfolio_config_endpoint(self, client, auth_headers):
        """Portfolio config must return constraint settings."""
        resp = client.get("/api/portfolio/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "max_industry_weight" in data["config"]

    def test_constraint_config_has_all_types(self, client, auth_headers):
        """Constraint config must include all 6 constraint types."""
        resp = client.get("/api/portfolio/config", headers=auth_headers)
        config = resp.json()["config"]
        required_keys = [
            "max_industry_weight",
            "max_pairwise_correlation",
            "max_single_factor_exposure",
            "min_daily_volume_usd",
            "max_daily_turnover",
            "consecutive_loss_days",
        ]
        for key in required_keys:
            assert key in config, f"Missing constraint: {key}"
