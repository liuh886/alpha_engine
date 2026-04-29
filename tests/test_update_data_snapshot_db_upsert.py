import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_update_data_can_upsert_snapshot_payload_to_sqlite(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "update_data.py"), run_name="not_main")
    if "upsert_snapshot_payload_to_metadata_db" not in g:
        pytest.fail("update_data.py missing upsert_snapshot_payload_to_metadata_db helper")

    db_path = tmp_path / "metadata.db"
    payload = {
        "snapshot_id": "watchlist-day-2026-02-04",
        "dataset_key": "watchlist",
        "provider_uri": "data/watchlist",
        "freq": "day",
        "latest_calendar_day": "2026-02-04",
        "generated_at": "t",
    }

    g["upsert_snapshot_payload_to_metadata_db"](payload=payload, db_path=db_path)

    from src.assistant.data_snapshot_index import DataSnapshotIndex

    assert DataSnapshotIndex(db_path=db_path).get_snapshot("watchlist-day-2026-02-04") is not None
