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


def test_dashboard_server_run_curve_endpoint(tmp_path: Path, monkeypatch):
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))

    BacktestEquityCurveIndex(db_path=db_path).upsert_from_report_normal_json(
        "run1",
        {
            "columns": ["account", "turnover"],
            "index": ["2025-01-01"],
            "data": [[100.0, 0.1]],
        },
    )

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runs/run1/curve?limit=10", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        assert data.get("run_id") == "run1"
        curve = data.get("curve") or []
        assert len(curve) == 1
        assert curve[0].get("nav") == 100.0
    finally:
        httpd.shutdown()
        t.join(timeout=5)

