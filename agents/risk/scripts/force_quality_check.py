import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.metadata_db import resolve_metadata_db_path
from src.data.quality import generate_data_quality_summary

q = generate_data_quality_summary(
    dataset_key="watchlist",
    freq="day",
    provider_uri=project_root / "data" / "watchlist",
    csv_dir=project_root / "data" / "csv_source",
    markets=["us", "cn"],
)

print(q)

if q.get("ok"):
    idx = DataQualityIndex(db_path=resolve_metadata_db_path(project_root))
    snapshot_id = str(q.get("snapshot_id"))
    latest_day = str(q.get("latest_calendar_day"))
    
    idx.upsert(
        snapshot_id=snapshot_id,
        dataset_key="watchlist",
        freq="day",
        market="all",
        latest_calendar_day=latest_day,
        summary=q,
    )
    print("Saved to DB!")
