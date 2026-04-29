import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_equity_curve_index_upsert_and_drawdown(tmp_path: Path):
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex

    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    idx = BacktestEquityCurveIndex(db_path=db_path)

    report_normal = {
        "columns": ["account", "turnover"],
        "index": ["2025-01-01", "2025-01-02", "2025-01-03"],
        "data": [
            [100.0, 0.1],
            [110.0, 0.2],
            [105.0, 0.3],
        ],
    }

    inserted = idx.upsert_from_report_normal_json("run_1", report_normal)
    assert inserted == 3

    curve = idx.list_curve("run_1")
    assert [row["date"] for row in curve] == ["2025-01-01", "2025-01-02", "2025-01-03"]
    assert curve[0]["nav"] == pytest.approx(100.0)
    assert curve[1]["nav"] == pytest.approx(110.0)
    assert curve[2]["nav"] == pytest.approx(105.0)

    # Peak on 2025-01-02, drawdown on 2025-01-03 should be (110-105)/110.
    assert curve[0]["drawdown"] == pytest.approx(0.0)
    assert curve[1]["drawdown"] == pytest.approx(0.0)
    assert curve[2]["drawdown"] == pytest.approx((110.0 - 105.0) / 110.0)

    assert idx.delete_curve("run_1") is True
    assert idx.list_curve("run_1") == []


def test_equity_curve_index_ignores_missing_account(tmp_path: Path):
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex

    db_path = tmp_path / "metadata.db"
    idx = BacktestEquityCurveIndex(db_path=db_path)

    report_normal = {
        "columns": ["turnover"],
        "index": ["2025-01-01"],
        "data": [[0.1]],
    }
    assert idx.upsert_from_report_normal_json("run_2", report_normal) == 0
    assert idx.list_curve("run_2") == []
