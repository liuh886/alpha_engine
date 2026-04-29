import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_report_index_upsert_and_list(tmp_path: Path):
    from src.assistant.report_index import ReportIndex

    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    idx = ReportIndex(db_path=db_path)

    row = idx.upsert(
        report_type="backtest",
        ref_id="run_1",
        date="2026-02-06",
        formats=["html"],
        paths={"html": "reports/backtests/us/run_1/index.html"},
        meta={"market": "us"},
    )
    assert row["id"]

    got = idx.get_report(row["id"])
    assert got is not None
    assert got["type"] == "backtest"
    assert got["ref_id"] == "run_1"

    rows = idx.list_reports(limit=10, report_type="backtest")
    assert len(rows) >= 1
