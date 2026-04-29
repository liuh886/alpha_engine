import json
import runpy
import sys
import threading
import urllib.parse
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


def test_dashboard_server_arena_endpoints(tmp_path: Path, monkeypatch):
    from src.assistant.arena_index import ArenaIndex
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex

    db_path = tmp_path / "metadata.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(db_path))

    curves = BacktestEquityCurveIndex(db_path=db_path)
    curves.upsert_from_report_normal_json(
        "run_1",
        {"columns": ["account"], "index": ["2025-01-01", "2025-01-02"], "data": [[100.0], [110.0]]},
    )
    curves.upsert_from_report_normal_json(
        "run_2",
        {"columns": ["account"], "index": ["2025-01-01", "2025-01-02"], "data": [[100.0], [120.0]]},
    )

    arena = ArenaIndex(db_path=db_path)
    a = arena.create_arena(name="US Arena", market="us")
    arena.add_participant(arena_id=a["id"], name="m1", run_id="run_1")
    arena.add_participant(arena_id=a["id"], name="m2", run_id="run_2")
    arena.settle(arena_id=a["id"], date="latest")

    httpd, t = _start_server()
    try:
        port = httpd.server_address[1]
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/arenas?limit=10", timeout=5
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        arenas = data.get("arenas") or []
        assert any(x.get("name") == "US Arena" for x in arenas)

        q = urllib.parse.urlencode({"arena_name": "US Arena", "date": "latest"})
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/arena/leaderboard?{q}", timeout=5
        ) as resp:
            data2 = json.loads(resp.read().decode("utf-8"))
        assert data2.get("ok") is True
        assert data2.get("date") == "2025-01-02"
        leaderboard = data2.get("leaderboard") or []
        assert [r.get("participant_name") for r in leaderboard] == ["m2", "m1"]
    finally:
        httpd.shutdown()
        t.join(timeout=5)
