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


def test_dashboard_server_jobs_list_endpoint(tmp_path: Path, monkeypatch):
    try:
        from src.assistant.job_service import JobService
    except ModuleNotFoundError:
        pytest.fail("JobService module not implemented yet")

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))
    JobService(db_path=db_path, project_root=tmp_path).create_job(
        {
            "id": "job1",
            "type": "backtest",
            "status": "queued",
            "created_at": 1.0,
            "log_path": str(tmp_path / "job1.log"),
            "commands": [["python", "-c", "print('1')"]],
        }
    )

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs?limit=10", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        jobs = data.get("jobs") or []
        assert any(j.get("id") == "job1" for j in jobs)
    finally:
        httpd.shutdown()
        t.join(timeout=5)

