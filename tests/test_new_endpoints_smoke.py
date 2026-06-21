"""Smoke tests for new API endpoints: research, decay, portfolio.

These tests run against the live API server to verify endpoints are accessible.
"""

import json
import subprocess

import pytest


def _curl_get(path: str) -> dict:
    """Make a GET request to the API."""
    result = subprocess.run(
        ["curl", "-s", "-u", "admin:alpha2026", f"http://localhost:8000{path}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return {"ok": False, "error": f"curl failed: {result.stderr}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"Invalid JSON: {result.stdout[:100]}"}


def _curl_post(path: str, data: dict) -> dict:
    """Make a POST request to the API."""
    result = subprocess.run(
        ["curl", "-s", "-u", "admin:alpha2026", "-X", "POST",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(data),
         f"http://localhost:8000{path}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return {"ok": False, "error": f"curl failed: {result.stderr}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"Invalid JSON: {result.stdout[:100]}"}


def _server_running() -> bool:
    """Check if API server is running."""
    import socket
    try:
        s = socket.create_connection(("localhost", 8000), timeout=2)
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


@pytest.fixture(autouse=True)
def require_server():
    """Skip tests if API server is not running."""
    if not _server_running():
        pytest.skip("API server not running on localhost:8000")


@pytest.mark.approved_skip(reason="Requires running API server on localhost:8000")
class TestResearchEndpoints:
    """Smoke tests for /api/research endpoints."""

    def test_list_runs(self):
        """GET /api/research/runs should return ok."""
        data = _curl_get("/api/research/runs")
        assert data.get("ok") is True
        assert "runs" in data

    def test_start_run(self):
        """POST /api/research/run should accept request."""
        data = _curl_post("/api/research/run", {
            "market": "cn",
            "goal": "smoke test",
            "model_type": "lgbm",
        })
        assert data.get("ok") is True
        assert "run_id" in data


@pytest.mark.approved_skip(reason="Requires running API server on localhost:8000")
class TestDecayEndpoints:
    """Smoke tests for /api/decay endpoints."""

    def test_check_decay(self):
        """GET /api/decay/check should return factor decay status."""
        data = _curl_get("/api/decay/check?market=cn")
        assert data.get("ok") is True
        assert "total_factors" in data

    def test_get_config(self):
        """GET /api/portfolio/config should return constraint config."""
        data = _curl_get("/api/portfolio/config")
        assert data.get("ok") is True
        assert "config" in data
        assert "max_industry_weight" in data["config"]


@pytest.mark.approved_skip(reason="Requires running API server on localhost:8000")
class TestPortfolioEndpoints:
    """Smoke tests for /api/portfolio endpoints."""

    def test_check_portfolio_rejects_unbound_positions(self):
        """POST /api/portfolio/check must fail closed without artifact identities."""
        data = _curl_post("/api/portfolio/check", {
            "positions": {"000001": 0.1, "600519": 0.2},
            "market": "cn",
            "portfolio_value": 100000,
        })
        assert data.get("ok") is False
        assert data.get("error_code") == "API_VALIDATION_ERROR"
        missing_fields = {
            detail["location"][-1]
            for detail in data.get("details", [])
            if detail.get("type") == "missing"
        }
        assert missing_fields == {
            "portfolio_artifact_id",
            "model_artifact_id",
            "data_snapshot_id",
        }
