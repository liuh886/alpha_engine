import json
import runpy
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def _start_server():
    g = runpy.run_path(str(ROOT / "scripts" / "dashboard_server.py"), run_name="not_main")
    Handler = g["DashboardHandler"]
    ThreadingHTTPServer = g["ThreadingHTTPServer"]
    PROJECT_ROOT = g["PROJECT_ROOT"]

    handler = lambda *args, **kwargs: Handler(*args, directory=str(PROJECT_ROOT), **kwargs)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, t


def test_dashboard_server_arena_settle_creates_job(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]

        payload = json.dumps({"market": "us", "arena_name": "US Arena", "date": "latest"}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/arena/settle",
            method="POST",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        job_id = data.get("job_id")
        assert isinstance(job_id, str) and job_id

        # Poll until finished (should be quick; no qlib work here)
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/jobs/{job_id}", timeout=5
            ) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            status = (j.get("job") or {}).get("status")
            if status in {"succeeded", "failed"}:
                break
            time.sleep(0.1)

        assert status == "succeeded"
    finally:
        httpd.shutdown()
        t.join(timeout=5)
