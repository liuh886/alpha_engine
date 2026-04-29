import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_run_index_upserts_and_queries_runs(tmp_path: Path):
    try:
        from src.assistant.run_index import RunIndex
    except ModuleNotFoundError:
        pytest.fail("RunIndex module not implemented yet")

    db_path = tmp_path / "metadata.db"
    idx = RunIndex(db_path=db_path)

    dashboard_db = {
        "generated_at": "2026-02-05 00:00:00",
        "models": [
            {
                "id": "run1",
                "name": "[US] X 2026-02-05 (run1)",
                "date": "2026-02-05 00:00",
                "market": "us",
                "params": {
                    "backtest_start": "2025-01-01",
                    "backtest_end": "2026-02-04",
                    "data_snapshot_id": "watchlist-day-2026-02-04",
                },
                "data": {},
            },
            {
                "id": "run2",
                "name": "[CN] Y 2026-02-05 (run2)",
                "date": "2026-02-05 00:01",
                "market": "cn",
                "params": {
                    "backtest_start": "2025-01-01",
                    "backtest_end": "2026-02-03",
                    "meta": {"data_snapshot_id": "watchlist-day-2026-02-03"},
                },
                "data": {},
            },
        ],
    }
    p = tmp_path / "dashboard_db.json"
    p.write_text(json.dumps(dashboard_db), encoding="utf-8")

    n = idx.upsert_from_dashboard_db_path(p)
    assert n == 2

    runs = idx.list_runs(limit=10)
    assert {r["id"] for r in runs} == {"run1", "run2"}

    try:
        us_only = idx.list_runs(limit=10, market="us")
    except TypeError:
        pytest.fail("RunIndex.list_runs does not support market filter yet")
    assert {r["id"] for r in us_only} == {"run1"}

    r1 = idx.get_run("run1")
    assert r1 is not None
    assert r1["data_snapshot_id"] == "watchlist-day-2026-02-04"

    try:
        idx.delete_run("run1")
    except AttributeError:
        pytest.fail("RunIndex.delete_run is not implemented yet")

    assert idx.get_run("run1") is None
    assert {r["id"] for r in idx.list_runs(limit=10)} == {"run2"}
