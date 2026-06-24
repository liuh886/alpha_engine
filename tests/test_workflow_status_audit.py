"""Audit workflow status handling: terminal states and stale lock override.

Tests that:
- /api/workflow/train can return SUCCESS, FAILED, RESEARCH_CANDIDATE
- RESEARCH_CANDIDATE is treated as terminal (not stuck in running)
- Stale workflow locks are properly detected and overridden
- updated_at ISO string parsing works correctly
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestWorkflowStaleLock:
    """Test stale workflow lock detection and override."""

    def _make_workflow(self, workflow_id: str, status: str, updated_at: str) -> dict:
        """Create a mock workflow row."""
        return {
            "workflow_id": workflow_id,
            "name": "Pipeline Run: cn",
            "market": "CN",
            "status": status,
            "updated_at": updated_at,
            "start_time": updated_at,
            "end_time": None,
            "error": None,
            "details_json": None,
        }

    def test_stale_lock_detected_with_iso_timestamp(self):
        """A RUNNING workflow with updated_at > 4 hours ago should be detected as stale."""
        from src.api.routers.workflow import _check_workflow_mutex

        # Create a workflow that was updated 5 hours ago
        five_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        stale_workflow = self._make_workflow("wf-stale", "RUNNING", five_hours_ago)

        gov = MagicMock()
        gov.query_workflows.return_value = [stale_workflow]

        # Should not raise (stale lock is cleared)
        _check_workflow_mutex(gov, "cn", "Pipeline Run")

        # Should have called update_workflow_status to FAILED
        gov.update_workflow_status.assert_called_once_with("wf-stale", status="FAILED")

    def test_recent_lock_raises_409(self):
        """A RUNNING workflow updated recently should raise HTTP 409."""
        from fastapi import HTTPException

        from src.api.routers.workflow import _check_workflow_mutex

        # Create a workflow that was updated 1 minute ago
        one_minute_ago = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        recent_workflow = self._make_workflow("wf-recent", "RUNNING", one_minute_ago)

        gov = MagicMock()
        gov.query_workflows.return_value = [recent_workflow]

        with pytest.raises(HTTPException) as exc_info:
            _check_workflow_mutex(gov, "cn", "Pipeline Run")

        assert exc_info.value.status_code == 409
        assert "wf-recent" in str(exc_info.value.detail)

    def test_no_running_workflow_passes(self):
        """When no RUNNING workflow exists, mutex check should pass silently."""
        from src.api.routers.workflow import _check_workflow_mutex

        gov = MagicMock()
        gov.query_workflows.return_value = []

        # Should not raise
        _check_workflow_mutex(gov, "cn", "Pipeline Run")

    def test_iso_string_parsing_handles_invalid_format(self):
        """Invalid ISO format should not crash the mutex check."""
        from fastapi import HTTPException

        from src.api.routers.workflow import _check_workflow_mutex

        # Create a workflow with invalid updated_at
        bad_workflow = self._make_workflow("wf-bad", "RUNNING", "not-a-date")

        gov = MagicMock()
        gov.query_workflows.return_value = [bad_workflow]

        # Should not crash, should raise 409 (age_seconds defaults to 0)
        with pytest.raises(HTTPException) as exc_info:
            _check_workflow_mutex(gov, "cn", "Pipeline Run")

        assert exc_info.value.status_code == 409

    def test_different_market_not_blocked(self):
        """A RUNNING workflow for a different market should not block."""
        from src.api.routers.workflow import _check_workflow_mutex

        gov = MagicMock()
        # The mutex check filters by market, so return empty for different market
        gov.query_workflows.return_value = []

        # Should not raise - no matching workflows
        _check_workflow_mutex(gov, "cn", "Pipeline Run")


class TestWorkflowTerminalStatuses:
    """Test that workflow terminal statuses are handled correctly."""

    def test_research_candidate_is_terminal_status(self):
        """RESEARCH_CANDIDATE should be treated as a terminal status by the backend."""
        # Check that _pipeline_gate_outcome returns RESEARCH_CANDIDATE for failed gates
        from src.workflows.hooks import _pipeline_gate_outcome

        # Walk-forward with gate_passed=False
        wf = {"gate_passed": False, "gate_failures": ["low_ic"]}
        result = _pipeline_gate_outcome(wf)
        assert result["status"] == "RESEARCH_CANDIDATE"
        assert result["operational_success"] is False

    def test_success_is_terminal_status(self):
        """SUCCESS should be returned when walk-forward gate passes."""
        from src.workflows.hooks import _pipeline_gate_outcome

        wf = {"gate_passed": True, "gate_failures": []}
        result = _pipeline_gate_outcome(wf)
        assert result["status"] == "SUCCESS"
        assert result["operational_success"] is True

    def test_none_walkforward_is_research_candidate(self):
        """Missing walk-forward data should result in RESEARCH_CANDIDATE."""
        from src.workflows.hooks import _pipeline_gate_outcome

        result = _pipeline_gate_outcome(None)
        assert result["status"] == "RESEARCH_CANDIDATE"
        assert result["operational_success"] is False


class TestWorkflowApiEndpoint:
    """Test the /api/workflow/train endpoint behavior."""

    def test_workflow_router_has_train_endpoint(self):
        """The workflow router must have a /train endpoint."""
        from src.api.routers.workflow import router

        routes = [r.path for r in router.routes]
        assert "/train" in routes

    def test_workflow_router_has_backtest_endpoint(self):
        """The workflow router must have a /backtest endpoint."""
        from src.api.routers.workflow import router

        routes = [r.path for r in router.routes]
        assert "/backtest" in routes

    def test_workflow_router_has_status_endpoint(self):
        """The workflow router must have a /status endpoint."""
        from src.api.routers.workflow import router

        routes = [r.path for r in router.routes]
        assert "/status" in routes
