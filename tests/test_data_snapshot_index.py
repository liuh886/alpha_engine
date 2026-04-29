import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_data_snapshot_index_upserts_and_queries_latest(tmp_path: Path):
    try:
        from src.assistant.data_snapshot_index import DataSnapshotIndex
    except ModuleNotFoundError:
        pytest.fail("DataSnapshotIndex is not implemented yet")

    idx = DataSnapshotIndex(db_path=tmp_path / "metadata.db")

    idx.upsert(
        {
            "snapshot_id": "watchlist-day-2026-02-03",
            "dataset_key": "watchlist",
            "provider_uri": "data/watchlist",
            "freq": "day",
            "latest_calendar_day": "2026-02-03",
            "generated_at": "t1",
        }
    )
    idx.upsert(
        {
            "snapshot_id": "watchlist-day-2026-02-04",
            "dataset_key": "watchlist",
            "provider_uri": "data/watchlist",
            "freq": "day",
            "latest_calendar_day": "2026-02-04",
            "generated_at": "t2",
        }
    )

    latest = idx.get_latest(dataset_key="watchlist", freq="day")
    assert latest is not None
    assert latest["snapshot_id"] == "watchlist-day-2026-02-04"

    one = idx.get_snapshot("watchlist-day-2026-02-03")
    assert one is not None
    assert one["latest_calendar_day"] == "2026-02-03"
