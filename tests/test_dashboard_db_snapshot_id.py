import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_dashboard_db_builder_infers_data_snapshot_id_from_params():
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")
    if "infer_data_snapshot_id" not in g:
        pytest.fail("build_dashboard_db.py missing infer_data_snapshot_id helper")

    infer = g["infer_data_snapshot_id"]
    assert infer({"data_snapshot_id": "watchlist-day-2026-02-04"}) == "watchlist-day-2026-02-04"
    assert infer({"backtest_end": "2026-02-04"}) == "watchlist-day-2026-02-04"
