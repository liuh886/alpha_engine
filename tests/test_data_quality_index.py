import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_data_quality_index_upsert_and_get_latest(tmp_path: Path):
    from src.assistant.data_quality_index import DataQualityIndex

    db_path = tmp_path / "metadata.db"
    idx = DataQualityIndex(db_path=db_path)

    row = idx.upsert(
        snapshot_id="watchlist-day-2026-02-05",
        dataset_key="watchlist",
        freq="day",
        market="us",
        latest_calendar_day="2026-02-05",
        summary={"ok": True, "latest_calendar_day": "2026-02-05"},
    )
    assert row.get("id")

    latest = idx.get_latest(dataset_key="watchlist", freq="day", market="us")
    assert latest is not None
    assert latest.get("snapshot_id") == "watchlist-day-2026-02-05"
