import json
import runpy
import sys
import threading
import urllib.error
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


def test_delete_returns_json_500_on_exception(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    sys.path.append(str(root))
    import src.dashboard.run_deletion as rd

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(rd, "delete_backtest_run", boom)

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/runs/run_123",
            method="DELETE",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)  # noqa: S310
        assert ei.value.code == 500
        body = ei.value.read().decode("utf-8")
        payload = json.loads(body)
        assert payload.get("ok") is False
        assert "boom" in str(payload.get("error") or "")
    finally:
        httpd.shutdown()
        t.join(timeout=5)
