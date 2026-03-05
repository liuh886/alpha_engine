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


def test_dashboard_server_models_list_and_detail_endpoints(tmp_path: Path, monkeypatch):
    from src.assistant.model_registry_index import ModelRegistryIndex

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))

    idx = ModelRegistryIndex(db_path=db_path)
    idx.upsert_entry({"id": "m1", "market": "us", "type": "LGBModel", "path": "models/m1.pkl", "run_id": "r1"})

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/models?limit=10", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        versions = data.get("versions") or []
        assert any(v.get("id") == "m1" for v in versions)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/models/m1", timeout=5) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))
        assert data2.get("ok") is True
        assert (data2.get("version") or {}).get("id") == "m1"
    finally:
        httpd.shutdown()
        t.join(timeout=5)
