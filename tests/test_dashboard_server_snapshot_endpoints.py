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


def test_dashboard_server_latest_snapshot_endpoint(tmp_path: Path, monkeypatch):
    try:
        from src.assistant.data_snapshot_index import DataSnapshotIndex
    except ModuleNotFoundError:
        pytest.fail("DataSnapshotIndex is not implemented yet")

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))
    DataSnapshotIndex(db_path=db_path).upsert(
        {
            "snapshot_id": "watchlist-day-2026-02-04",
            "dataset_key": "watchlist",
            "provider_uri": "data/watchlist",
            "freq": "day",
            "latest_calendar_day": "2026-02-04",
            "generated_at": "t",
        }
    )

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/data/snapshots/latest", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        snap = data.get("snapshot") or {}
        assert snap.get("snapshot_id") == "watchlist-day-2026-02-04"
    finally:
        httpd.shutdown()
        t.join(timeout=5)

