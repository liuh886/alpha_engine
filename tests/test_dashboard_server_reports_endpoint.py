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


def test_dashboard_server_reports_list_and_detail_endpoints(tmp_path: Path, monkeypatch):
    from src.assistant.report_index import ReportIndex

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))

    idx = ReportIndex(db_path=db_path)
    row = idx.upsert(
        report_type="backtest",
        ref_id="run_1",
        date="2026-02-06",
        formats=["html"],
        paths={"html": "reports/backtests/us/run_1/index.html"},
        meta={"market": "us"},
    )
    report_id = row["id"]

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/reports?type=backtest&ref_id=run_1&limit=10", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        reports = data.get("reports") or []
        assert any(r.get("id") == report_id for r in reports)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/reports/{report_id}", timeout=5) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))
        assert data2.get("ok") is True
        assert (data2.get("report") or {}).get("id") == report_id
    finally:
        httpd.shutdown()
        t.join(timeout=5)

