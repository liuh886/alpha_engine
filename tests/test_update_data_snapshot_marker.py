import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_update_data_script_records_latest_snapshot_marker(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "update_data.py"), run_name="not_main")
    if "record_latest_snapshot_marker" not in g:
        pytest.fail("update_data.py missing record_latest_snapshot_marker helper")

    provider_dir = tmp_path / "data" / "watchlist"
    (provider_dir / "calendars").mkdir(parents=True, exist_ok=True)
    (provider_dir / "calendars" / "day.txt").write_text("2026-02-04\n", encoding="utf-8")

    out_path = tmp_path / "artifacts" / "snapshots" / "watchlist_latest.json"
    g["record_latest_snapshot_marker"](provider_dir=provider_dir, output_path=out_path)

    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert "watchlist-day-2026-02-04" in text
