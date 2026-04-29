import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_update_model_list_records_run_id(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(tmp_path))
    from src.assistant.metadata_db import resolve_metadata_db_path
    from src.assistant.model_registry_index import ModelRegistryIndex
    from src.common.paths import MODELS_DIR
    from src.orchestrator import Orchestrator

    monkeypatch.chdir(tmp_path)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "us_model_20250102_000000.pkl"
    model_path.write_text("dummy", encoding="utf-8")

    config = {
        "market": "us",
        "task": {
            "model": {"class": "XGBModel", "kwargs": {"max_depth": 3}},
            "dataset": {"kwargs": {"segments": {"train": ["2020-01-01", "2024-12-31"]}}},
        },
        "port_analysis_config": {
            "backtest": {"start_time": "2025-01-01", "end_time": "2025-01-02"}
        },
    }

    orch = Orchestrator()
    orch._update_model_list("us", model_path, config, metrics={}, run_id="run_123")

    data = yaml.safe_load((MODELS_DIR / "model_list.yaml").read_text(encoding="utf-8"))

    assert data["models"][-1]["run_id"] == "run_123"

    version_id = data["models"][-1]["id"]
    db_path = resolve_metadata_db_path(tmp_path)
    assert ModelRegistryIndex(db_path=db_path).get_version(version_id) is not None
