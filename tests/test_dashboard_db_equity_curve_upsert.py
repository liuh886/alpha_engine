import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex


def test_build_dashboard_db_upserts_equity_curves_to_sqlite(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")
    upsert = g.get("upsert_equity_curves_to_metadata_db")
    assert callable(upsert)

    output_data = {
        "models": [
            {
                "id": "run_1",
                "data": {
                    "report_normal": {
                        "columns": ["account", "turnover"],
                        "index": ["2025-01-01"],
                        "data": [[100.0, 0.1]],
                    }
                },
            },
            {
                "id": "run_2",
                "data": {
                    "report_normal": {
                        "columns": ["account"],
                        "index": ["2025-01-01"],
                        "data": [[200.0]],
                    }
                },
            },
        ]
    }

    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    n = upsert(output_data, db_path=db_path)
    assert n == 2

    idx = BacktestEquityCurveIndex(db_path=db_path)
    assert len(idx.list_curve("run_1")) == 1
    assert len(idx.list_curve("run_2")) == 1
