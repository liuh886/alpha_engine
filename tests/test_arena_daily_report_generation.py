import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_generate_arena_daily_report(tmp_path: Path):
    from src.assistant.arena_index import ArenaIndex
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
    from src.assistant.report_index import ReportIndex
    from src.reporting.arena_daily_report import generate_arena_daily_report

    project_root = tmp_path
    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"

    BacktestEquityCurveIndex(db_path=db_path).upsert_from_report_normal_json(
        "run_1",
        {
            "columns": ["account", "turnover"],
            "index": ["2026-02-04", "2026-02-05"],
            "data": [[100.0, 0.1], [105.0, 0.2]],
        },
    )

    arena = ArenaIndex(db_path=db_path)
    a = arena.create_arena(name="US Arena", market="us")
    arena_id = str(a.get("id") or "")
    arena.add_participant(arena_id=arena_id, name="Model A", run_id="run_1")
    arena.settle(arena_id=arena_id, date="2026-02-05")

    out = generate_arena_daily_report(
        arena_id=arena_id, date="2026-02-05", project_root=project_root, db_path=db_path
    )
    assert out["ok"] is True
    rel = out["report_rel_path"]
    assert rel
    assert (project_root / rel).exists()

    rows = ReportIndex(db_path=db_path).list_reports(limit=10, report_type="arena_daily")
    assert any(r.get("ref_id") == arena_id for r in rows)
