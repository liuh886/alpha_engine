import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_build_data_snapshot_id_from_calendar_latest_day(tmp_path: Path):
    try:
        from src.assistant.data_snapshot import build_data_snapshot_id, read_latest_calendar_day
    except ModuleNotFoundError:
        pytest.fail("data_snapshot module is not implemented yet")

    cal_dir = tmp_path / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    (cal_dir / "day.txt").write_text("2026-02-03\n2026-02-04\n", encoding="utf-8")

    latest = read_latest_calendar_day(tmp_path)
    assert latest == "2026-02-04"

    snap = build_data_snapshot_id(dataset_key="watchlist", freq="day", latest_calendar_day=latest)
    assert snap == "watchlist-day-2026-02-04"
