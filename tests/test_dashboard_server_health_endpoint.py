import json
import runpy
import threading
import urllib.request
from pathlib import Path


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


def test_dashboard_server_health_endpoint():
    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
        assert data.get("ok") is True
    finally:
        httpd.shutdown()
        t.join(timeout=5)

