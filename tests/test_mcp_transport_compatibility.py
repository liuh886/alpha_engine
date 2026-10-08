from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_real_mcp_transport_initialization_and_host_validation(tmp_path: Path) -> None:
    """Exercise the actual SDK/ASGI stack without executing research tools."""
    script = textwrap.dedent(
        """
        import asyncio
        import sys

        sys.path.insert(0, sys.argv[1])
        from starlette.testclient import TestClient
        from src.api.mcp_server import mcp

        async def check_tools():
            names = {tool.name for tool in await mcp.list_tools()}
            assert {"run_backtest", "run_research_cycle"} <= names

        asyncio.run(check_tools())
        with TestClient(mcp.streamable_http_app(), base_url="http://localhost:8000") as client:
            body = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "contract-test", "version": "1"},
                },
            }
            headers = {
                "Accept": "application/json, text/event-stream",
                "Origin": "http://localhost:8000",
            }
            response = client.post("/mcp", json=body, headers=headers)
            assert response.status_code == 200, response.text
            assert "protocolVersion" in response.text
            rejected = client.post("/mcp", json=body, headers={**headers, "Host": "attacker.invalid"})
            assert rejected.status_code in (400, 403, 421), rejected.text
        """
    )
    environment = dict(os.environ, ALPHA_DEVELOPER_TOKEN="contract-test-token")
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve().parents[1])],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"Real MCP transport failed:\n{result.stdout}\n{result.stderr}"
