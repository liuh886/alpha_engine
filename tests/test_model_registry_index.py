import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_model_registry_index_upserts_from_yaml_and_deletes_by_run(tmp_path: Path):
    from src.assistant.model_registry_index import ModelRegistryIndex

    model_list_path = tmp_path / "models" / "model_list.yaml"
    model_list_path.parent.mkdir(parents=True, exist_ok=True)
    model_list_path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "us_model_20250102_000000",
                        "tag": "LGBM_v1",
                        "path": "models/us_model_LGBM_v1_20250102_000000.pkl",
                        "type": "LGBModel",
                        "market": "us",
                        "created_at": "2025-01-02",
                        "run_id": "run_1",
                        "backtest": {"metrics": {"annualized_return": 0.1}},
                    },
                    {
                        "id": "us_model_20250103_000000",
                        "tag": "LGBM_v2",
                        "path": "models/us_model_LGBM_v2_20250103_000000.pkl",
                        "type": "LGBModel",
                        "market": "us",
                        "created_at": "2025-01-03",
                        "run_id": "run_2",
                        "backtest": {"metrics": {"annualized_return": 0.2}},
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    idx = ModelRegistryIndex(db_path=db_path)
    assert idx.upsert_from_model_list_yaml(model_list_path, project_root=tmp_path) == 2

    versions = idx.list_versions(limit=10)
    assert {v["id"] for v in versions} == {"us_model_20250102_000000", "us_model_20250103_000000"}
    v1 = idx.get_version("us_model_20250102_000000")
    assert v1 and v1.get("run_id") == "run_1"
    assert v1.get("tag") == "LGBM_v1"

    assert idx.delete_versions_for_run("run_1") is True
    assert idx.get_version("us_model_20250102_000000") is None
    assert idx.get_version("us_model_20250103_000000") is not None

