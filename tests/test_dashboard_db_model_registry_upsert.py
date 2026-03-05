import runpy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_build_dashboard_db_upserts_model_registry_to_sqlite(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")
    upsert = g.get("upsert_model_registry_to_metadata_db")
    assert callable(upsert)

    model_list_path = tmp_path / "models" / "model_list.yaml"
    model_list_path.parent.mkdir(parents=True, exist_ok=True)
    model_list_path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"id": "m1", "market": "us", "type": "LGBModel", "path": "models/m1.pkl", "run_id": "r1"},
                    {"id": "m2", "market": "us", "type": "LGBModel", "path": "models/m2.pkl", "run_id": "r2"},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    n = upsert(model_list_path=model_list_path, db_path=db_path)
    assert n == 2

    from src.assistant.model_registry_index import ModelRegistryIndex

    idx = ModelRegistryIndex(db_path=db_path)
    assert {v["id"] for v in idx.list_versions(limit=10)} == {"m1", "m2"}

