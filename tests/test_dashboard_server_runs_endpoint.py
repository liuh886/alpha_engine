import json
import runpy
import threading
import urllib.request
from pathlib import Path

import pytest


def _start_server():
    root = Path(__file__).resolve().parents[1]
    g = runpy.run_path(str(root / "scripts" / "dashboard_server.py"), run_name="not_main")
    Handler = g["DashboardHandler"]
    ThreadingHTTPServer = g["ThreadingHTTPServer"]
    PROJECT_ROOT = g["PROJECT_ROOT"]

    handler = lambda *args, **kwargs: Handler(*args, directory=str(PROJECT_ROOT), **kwargs)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t


def test_dashboard_server_runs_list_and_detail_endpoints(tmp_path: Path, monkeypatch):
    try:
        from src.assistant.run_index import RunIndex
    except ModuleNotFoundError:
        pytest.fail("RunIndex module not implemented yet")

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))
    RunIndex(db_path=db_path).upsert_from_dashboard_db(
        {
            "models": [
                {"id": "run1", "name": "r1", "market": "us", "date": "2026-02-05 00:00", "params": {}},
            ]
        }
    )

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runs?limit=10", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        runs = data.get("runs") or []
        assert any(r.get("id") == "run1" for r in runs)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runs/run1", timeout=5) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))
        assert data2.get("ok") is True
        assert (data2.get("run") or {}).get("id") == "run1"
    finally:
        httpd.shutdown()
        t.join(timeout=5)

