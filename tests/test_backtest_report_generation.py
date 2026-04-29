import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_generate_backtest_report_indexes_sqlite_and_writes_html(tmp_path: Path):
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
    from src.assistant.report_index import ReportIndex
    from src.assistant.run_index import RunIndex
    from src.reporting.backtest_report import generate_backtest_report

    project_root = tmp_path
    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    dashboard_db_path = project_root / "artifacts" / "dashboard" / "dashboard_db.json"
    dashboard_db_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": "2026-02-06 00:00:00",
        "models": [
            {
                "id": "run_1",
                "name": "Test Run",
                "date": "2026-02-06 00:00",
                "experiment": "0",
                "market": "us",
                "params": {
                    "backtest_start": "2025-01-01",
                    "backtest_end": "2026-02-05",
                    "meta": {"data_snapshot_id": "watchlist-day-2026-02-05"},
                },
                "data": {
                    "report_normal": {
                        "columns": ["account", "turnover"],
                        "index": ["2026-02-04", "2026-02-05"],
                        "data": [[100.0, 0.1], [110.0, 0.2]],
                    }
                },
            }
        ],
        "name_map": {},
    }
    dashboard_db_path.write_text(json.dumps(payload), encoding="utf-8")

    RunIndex(db_path=db_path).upsert_from_dashboard_db(payload)
    BacktestEquityCurveIndex(db_path=db_path).upsert_from_report_normal_json(
        "run_1",
        payload["models"][0]["data"]["report_normal"],
    )

    out = generate_backtest_report(run_id="run_1", project_root=project_root, db_path=db_path)
    assert out["ok"] is True
    rel = out["report_rel_path"]
    assert rel
    assert (project_root / rel).exists()

    rows = ReportIndex(db_path=db_path).list_reports(limit=10, report_type="backtest")
    assert any(r.get("ref_id") == "run_1" for r in rows)
