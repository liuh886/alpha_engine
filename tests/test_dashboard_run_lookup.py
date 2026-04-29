from __future__ import annotations

import json
from pathlib import Path


def test_get_run_model_path_prefers_model_path(tmp_path: Path):
    db = {
        "models": [
            {
                "id": "run_1",
                "params": {"model_path": "models/us_model_1.pkl", "profile": "configs/p1.json"},
            },
        ]
    }
    db_path = tmp_path / "dashboard_db.json"
    db_path.write_text(json.dumps(db), encoding="utf-8")

    from src.dashboard.run_lookup import get_run_model_path, get_run_profile_path

    assert get_run_model_path("run_1", dashboard_db_path=db_path) == "models/us_model_1.pkl"
    assert get_run_profile_path("run_1", dashboard_db_path=db_path) == "configs/p1.json"


def test_get_run_model_path_falls_back_to_source_model_path(tmp_path: Path):
    db = {
        "models": [
            {"id": "run_2", "params": {"source_model_path": "models/us_model_2.pkl"}},
        ]
    }
    db_path = tmp_path / "dashboard_db.json"
    db_path.write_text(json.dumps(db), encoding="utf-8")

    from src.dashboard.run_lookup import get_run_model_path

    assert get_run_model_path("run_2", dashboard_db_path=db_path) == "models/us_model_2.pkl"


def test_get_run_model_path_returns_none_when_missing(tmp_path: Path):
    db_path = tmp_path / "dashboard_db.json"
    db_path.write_text(json.dumps({"models": []}), encoding="utf-8")

    from src.dashboard.run_lookup import get_run_model_path

    assert get_run_model_path("nope", dashboard_db_path=db_path) is None
