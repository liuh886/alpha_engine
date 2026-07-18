from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_mcp_stub() -> None:
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, *_args, **_kwargs):
            pass

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self):
            return None

    fastmcp_module.FastMCP = FastMCP
    sys.modules["mcp"] = types.ModuleType("mcp")
    sys.modules["mcp.server"] = types.ModuleType("mcp.server")
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def test_run_backtest_uses_orchestrator_cli_flags(monkeypatch):
    # Save original mcp modules
    orig_mcp = sys.modules.get("mcp")
    orig_mcp_server = sys.modules.get("mcp.server")
    orig_mcp_fastmcp = sys.modules.get("mcp.server.fastmcp")
    orig_mcp_server_mod = sys.modules.pop("src.api.mcp_server", None)

    try:
        _install_mcp_stub()
        mcp_server = importlib.import_module("src.api.mcp_server")

        commands: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            commands.append(list(cmd))
            return types.SimpleNamespace(stdout="ok", stderr="")

        workflow_module = types.ModuleType("qlib.workflow")
        workflow_module.R = types.SimpleNamespace(list_rec=lambda **_kwargs: [])
        qlib_module = types.ModuleType("qlib")
        qlib_module.workflow = workflow_module

        monkeypatch.setitem(sys.modules, "qlib", qlib_module)
        monkeypatch.setitem(sys.modules, "qlib.workflow", workflow_module)
        monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)

        # Ensure token verification passes in test environment
        monkeypatch.setenv("ALPHA_DEVELOPER_TOKEN", "")
        mcp_server._DEVELOPER_TOKEN = ""

        mcp_server.run_backtest(market="us", start_date="2025-01-01", end_date="2025-01-31")

        assert commands, "expected subprocess.run to be invoked"
        cmd = commands[0]
        assert "--start" in cmd
        assert "--end" in cmd
        assert "--start_time" not in cmd
        assert "--end_time" not in cmd

    finally:
        # Restore original mcp modules
        if orig_mcp is not None:
            sys.modules["mcp"] = orig_mcp
        else:
            sys.modules.pop("mcp", None)
        if orig_mcp_server is not None:
            sys.modules["mcp.server"] = orig_mcp_server
        else:
            sys.modules.pop("mcp.server", None)
        if orig_mcp_fastmcp is not None:
            sys.modules["mcp.server.fastmcp"] = orig_mcp_fastmcp
        else:
            sys.modules.pop("mcp.server.fastmcp", None)
        if orig_mcp_server_mod is not None:
            sys.modules["src.api.mcp_server"] = orig_mcp_server_mod


def test_run_backtest_auth_failure(monkeypatch):
    """When token is set and doesn't match, should return auth error."""
    orig_mcp = sys.modules.get("mcp")
    orig_mcp_server = sys.modules.get("mcp.server")
    orig_mcp_fastmcp = sys.modules.get("mcp.server.fastmcp")
    orig_mcp_server_mod = sys.modules.pop("src.api.mcp_server", None)

    try:
        _install_mcp_stub()
        mcp_server = importlib.import_module("src.api.mcp_server")

        # Set a specific token
        monkeypatch.setenv("ALPHA_DEVELOPER_TOKEN", "secret123")
        mcp_server._DEVELOPER_TOKEN = "secret123"

        # Call with wrong token
        result = mcp_server.run_backtest(token="wrong_token", market="us")
        assert "Authentication failed" in result

        # Call with no token
        result = mcp_server.run_backtest(token="", market="us")
        assert "Authentication failed" in result

    finally:
        if orig_mcp is not None:
            sys.modules["mcp"] = orig_mcp
        else:
            sys.modules.pop("mcp", None)
        if orig_mcp_server is not None:
            sys.modules["mcp.server"] = orig_mcp_server
        else:
            sys.modules.pop("mcp.server", None)
        if orig_mcp_fastmcp is not None:
            sys.modules["mcp.server.fastmcp"] = orig_mcp_fastmcp
        else:
            sys.modules.pop("mcp.server.fastmcp", None)
        if orig_mcp_server_mod is not None:
            sys.modules["src.api.mcp_server"] = orig_mcp_server_mod


def test_run_backtest_auth_success(monkeypatch):
    """When token matches, should proceed with backtest."""
    orig_mcp = sys.modules.get("mcp")
    orig_mcp_server = sys.modules.get("mcp.server")
    orig_mcp_fastmcp = sys.modules.get("mcp.server.fastmcp")
    orig_mcp_server_mod = sys.modules.pop("src.api.mcp_server", None)

    try:
        _install_mcp_stub()
        mcp_server = importlib.import_module("src.api.mcp_server")

        commands: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            commands.append(list(cmd))
            return types.SimpleNamespace(stdout="ok", stderr="", returncode=0)

        workflow_module = types.ModuleType("qlib.workflow")
        workflow_module.R = types.SimpleNamespace(list_rec=lambda **_kwargs: [])
        qlib_module = types.ModuleType("qlib")
        qlib_module.workflow = workflow_module

        monkeypatch.setitem(sys.modules, "qlib", qlib_module)
        monkeypatch.setitem(sys.modules, "qlib.workflow", workflow_module)
        monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)

        # Set token and call with matching token
        monkeypatch.setenv("ALPHA_DEVELOPER_TOKEN", "secret123")
        mcp_server._DEVELOPER_TOKEN = "secret123"

        mcp_server.run_backtest(
            token="secret123", market="us", start_date="2025-01-01", end_date="2025-01-31"
        )

        assert commands, "expected subprocess.run to be invoked"
        cmd = commands[0]
        assert "--market" in cmd
        assert "us" in cmd

    finally:
        if orig_mcp is not None:
            sys.modules["mcp"] = orig_mcp
        else:
            sys.modules.pop("mcp", None)
        if orig_mcp_server is not None:
            sys.modules["mcp.server"] = orig_mcp_server
        else:
            sys.modules.pop("mcp.server", None)
        if orig_mcp_fastmcp is not None:
            sys.modules["mcp.server.fastmcp"] = orig_mcp_fastmcp
        else:
            sys.modules.pop("mcp.server.fastmcp", None)
        if orig_mcp_server_mod is not None:
            sys.modules["src.api.mcp_server"] = orig_mcp_server_mod


def test_run_research_cycle_uses_research_workflow_adapter(monkeypatch):
    orig_mcp = sys.modules.get("mcp")
    orig_mcp_server = sys.modules.get("mcp.server")
    orig_mcp_fastmcp = sys.modules.get("mcp.server.fastmcp")
    orig_mcp_server_mod = sys.modules.pop("src.api.mcp_server", None)

    try:
        _install_mcp_stub()
        mcp_server = importlib.import_module("src.api.mcp_server")

        from src.research.workflow_types import (
            ResearchStep,
            ResearchWorkflowResult,
            StepResult,
            WorkflowStatus,
        )

        captured_requests = []

        class FakeWorkflow:
            def run(self, request):
                captured_requests.append(request)
                return ResearchWorkflowResult(
                    run_id="rw_mcp_contract",
                    request=request,
                    status=WorkflowStatus.COMPLETED,
                    steps=[
                        StepResult(
                            step=ResearchStep.SCAN,
                            status=WorkflowStatus.SKIPPED,
                            output={"market": request.market},
                        )
                    ],
                    promotion_decision={
                        "schema_version": "1.0",
                        "subject_id": "rw_mcp_contract",
                        "status": "missing_evidence",
                        "trade_ready": False,
                        "evidence_refs": [],
                    },
                )

        monkeypatch.setattr(mcp_server, "create_research_workflow", FakeWorkflow)
        monkeypatch.setenv("ALPHA_DEVELOPER_TOKEN", "")
        mcp_server._DEVELOPER_TOKEN = ""

        response = mcp_server.run_research_cycle(market="cn", goal="Find earnings alpha")
        payload = json.loads(response)

        assert captured_requests, "expected ResearchWorkflow.run to be invoked"
        request = captured_requests[0]
        assert request.market == "cn"
        assert request.goal == "Find earnings alpha"
        assert request.requested_by == "mcp.run_research_cycle"
        assert request.metadata["goal"] == "Find earnings alpha"
        assert payload["status"] == "success"
        assert payload["success"] is True
        assert payload["success_scope"] == "workflow_execution"
        assert payload["run_id"] == "rw_mcp_contract"
        assert payload["workflow_status"] == "completed"
        assert payload["promotion_status"] == "missing_evidence"
        assert payload["trade_ready"] is False
        assert payload["steps"][0]["step"] == "scan"

    finally:
        if orig_mcp is not None:
            sys.modules["mcp"] = orig_mcp
        else:
            sys.modules.pop("mcp", None)
        if orig_mcp_server is not None:
            sys.modules["mcp.server"] = orig_mcp_server
        else:
            sys.modules.pop("mcp.server", None)
        if orig_mcp_fastmcp is not None:
            sys.modules["mcp.server.fastmcp"] = orig_mcp_fastmcp
        else:
            sys.modules.pop("mcp.server.fastmcp", None)
        if orig_mcp_server_mod is not None:
            sys.modules["src.api.mcp_server"] = orig_mcp_server_mod


def test_run_iterative_research_removed():
    """Verify run_iterative_research is no longer an MCP tool (ADR-0009)."""
    orig_mcp = sys.modules.get("mcp")
    orig_mcp_server = sys.modules.get("mcp.server")
    orig_mcp_fastmcp = sys.modules.get("mcp.server.fastmcp")
    orig_mcp_server_mod = sys.modules.pop("src.api.mcp_server", None)

    try:
        _install_mcp_stub()
        mcp_server = importlib.import_module("src.api.mcp_server")
        assert not hasattr(mcp_server, "run_iterative_research"), (
            "run_iterative_research MCP tool must be removed (ADR-0009)"
        )
    finally:
        if orig_mcp is not None:
            sys.modules["mcp"] = orig_mcp
        else:
            sys.modules.pop("mcp", None)
        if orig_mcp_server is not None:
            sys.modules["mcp.server"] = orig_mcp_server
        else:
            sys.modules.pop("mcp.server", None)
        if orig_mcp_fastmcp is not None:
            sys.modules["mcp.server.fastmcp"] = orig_mcp_fastmcp
        else:
            sys.modules.pop("mcp.server.fastmcp", None)
        if orig_mcp_server_mod is not None:
            sys.modules["src.api.mcp_server"] = orig_mcp_server_mod


def test_run_backtest_handles_subprocess_error(monkeypatch):
    """When subprocess returns non-zero, should handle gracefully."""
    import subprocess as sp

    orig_mcp = sys.modules.get("mcp")
    orig_mcp_server = sys.modules.get("mcp.server")
    orig_mcp_fastmcp = sys.modules.get("mcp.server.fastmcp")
    orig_mcp_server_mod = sys.modules.pop("src.api.mcp_server", None)

    try:
        _install_mcp_stub()
        mcp_server = importlib.import_module("src.api.mcp_server")

        def fake_run(cmd, **_kwargs):
            raise sp.CalledProcessError(1, cmd, output="error output", stderr="error details")

        workflow_module = types.ModuleType("qlib.workflow")
        workflow_module.R = types.SimpleNamespace(list_rec=lambda **_kwargs: [])
        qlib_module = types.ModuleType("qlib")
        qlib_module.workflow = workflow_module

        monkeypatch.setitem(sys.modules, "qlib", qlib_module)
        monkeypatch.setitem(sys.modules, "qlib.workflow", workflow_module)
        monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)
        monkeypatch.setenv("ALPHA_DEVELOPER_TOKEN", "")
        mcp_server._DEVELOPER_TOKEN = ""

        result = mcp_server.run_backtest(market="us")
        # Should return error message, not crash
        assert isinstance(result, str)

    finally:
        if orig_mcp is not None:
            sys.modules["mcp"] = orig_mcp
        else:
            sys.modules.pop("mcp", None)
        if orig_mcp_server is not None:
            sys.modules["mcp.server"] = orig_mcp_server
        else:
            sys.modules.pop("mcp.server", None)
        if orig_mcp_fastmcp is not None:
            sys.modules["mcp.server.fastmcp"] = orig_mcp_fastmcp
        else:
            sys.modules.pop("mcp.server.fastmcp", None)
        if orig_mcp_server_mod is not None:
            sys.modules["src.api.mcp_server"] = orig_mcp_server_mod


def test_metrics_extractor_supports_tuple_payloads():
    from src.common.metrics_extractor import MetricsExtractor

    class FakeRecord:
        def load_object(self, key):
            if key == "port_analysis.pkl":
                return ({}, {"annualized_return": 0.12345, "information_ratio": 1.23456})
            return None

    metrics = MetricsExtractor.extract_from_record(FakeRecord())

    assert metrics["annualized_return"] == 0.1235
    assert metrics["information_ratio"] == 1.2346
