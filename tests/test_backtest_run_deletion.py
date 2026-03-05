import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_delete_backtest_run_removes_mlruns_and_dashboard_entry(tmp_path: Path):
    from src.assistant.arena_index import ArenaIndex
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
    from src.assistant.model_registry_index import ModelRegistryIndex
    from src.assistant.run_index import RunIndex
    from src.dashboard.run_deletion import delete_backtest_run

    run_id = "run_123"

    mlruns_root = tmp_path / "mlruns"
    exp_dir = mlruns_root / "exp_1"
    run_dir = exp_dir / run_id
    (run_dir / "artifacts").mkdir(parents=True)

    dashboard_json = tmp_path / "artifacts" / "dashboard" / "dashboard_db.json"
    dashboard_json.parent.mkdir(parents=True, exist_ok=True)
    dashboard_json.write_text(
        json.dumps(
            {
                "generated_at": "now",
                "name_map": {},
                "models": [
                    {"id": run_id, "name": "bad", "data": {}},
                    {"id": "run_other", "name": "ok", "data": {}},
                ],
            }
        ),
        encoding="utf-8",
    )

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    model_path = models_dir / "us_model_20250102_000000.pkl"
    model_path.write_text("dummy", encoding="utf-8")

    model_list = models_dir / "model_list.yaml"
    model_list.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"id": "m1", "path": "models/us_model_20250102_000000.pkl", "run_id": run_id},
                    {"id": "m2", "path": "models/other.pkl", "run_id": "run_other"},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # Seed run index DB row; deletion should remove it.
    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"
    RunIndex(db_path=db_path).upsert_from_dashboard_db(
        {
            "models": [
                {"id": run_id, "name": "bad", "market": "us", "date": "2026-02-05 00:00", "params": {}},
            ]
        }
    )
    assert RunIndex(db_path=db_path).get_run(run_id) is not None

    BacktestEquityCurveIndex(db_path=db_path).upsert_from_report_normal_json(
        run_id,
        {
            "columns": ["account", "turnover"],
            "index": ["2025-01-01"],
            "data": [[100.0, 0.1]],
        },
    )
    assert BacktestEquityCurveIndex(db_path=db_path).list_curve(run_id)

    arena = ArenaIndex(db_path=db_path)
    a = arena.create_arena(name="US Arena", market="us")
    arena.add_participant(arena_id=a["id"], name="m1", run_id=run_id)
    arena.settle(arena_id=a["id"], date="latest")
    assert arena.get_leaderboard(arena_id=a["id"], date="2025-01-01")

    # Seed model registry index so deletion also cleans it up.
    assert ModelRegistryIndex(db_path=db_path).upsert_from_model_list_yaml(model_list, project_root=tmp_path) == 2
    assert ModelRegistryIndex(db_path=db_path).get_version("m1") is not None

    deleted = delete_backtest_run(
        run_id,
        mlruns_root=mlruns_root,
        dashboard_json_path=dashboard_json,
        model_list_path=model_list,
        project_root=tmp_path,
    )
    assert deleted is True
    assert not run_dir.exists()
    assert not model_path.exists()

    updated = json.loads(dashboard_json.read_text(encoding="utf-8"))
    ids = [m["id"] for m in updated["models"]]
    assert run_id not in ids
    assert "run_other" in ids

    updated_list = yaml.safe_load(model_list.read_text(encoding="utf-8"))
    run_ids = [m.get("run_id") for m in updated_list.get("models", [])]
    assert run_id not in run_ids
    assert "run_other" in run_ids

    assert RunIndex(db_path=db_path).get_run(run_id) is None
    assert BacktestEquityCurveIndex(db_path=db_path).list_curve(run_id) == []
    assert ModelRegistryIndex(db_path=db_path).get_version("m1") is None
    assert arena.list_participants(arena_id=a["id"]) == []
    assert arena.get_leaderboard(arena_id=a["id"], date="2025-01-01") == []
