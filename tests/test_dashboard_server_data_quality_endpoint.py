import json
import runpy
import sys
import threading
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


def test_dashboard_server_data_quality_latest_endpoint(tmp_path: Path, monkeypatch):
    from src.assistant.data_quality_index import DataQualityIndex

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))

    DataQualityIndex(db_path=db_path).upsert(
        snapshot_id="watchlist-day-2026-02-05",
        dataset_key="watchlist",
        freq="day",
        market="all",
        latest_calendar_day="2026-02-05",
        summary={"ok": True, "warnings": []},
    )

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/data/quality/latest?dataset_key=watchlist&freq=day&market=all",
            timeout=5,
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        q = data.get("quality") or {}
        assert q.get("snapshot_id") == "watchlist-day-2026-02-05"
    finally:
        httpd.shutdown()
        t.join(timeout=5)

