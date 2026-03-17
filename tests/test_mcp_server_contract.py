from __future__ import annotations

import importlib
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
    _install_mcp_stub()
    sys.modules.pop("src.api.mcp_server", None)
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

    mcp_server.run_backtest(market="us", start_date="2025-01-01", end_date="2025-01-31")

    assert commands, "expected subprocess.run to be invoked"
    cmd = commands[0]
    assert "--start" in cmd
    assert "--end" in cmd
    assert "--start_time" not in cmd
    assert "--end_time" not in cmd


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
