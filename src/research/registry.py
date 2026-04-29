from datetime import datetime
from pathlib import Path

import yaml

from src.common.paths import MODELS_DIR


def register_model(
    market: str,
    model_path: Path,
    config: dict,
    metrics: dict = None,
    run_id: str = None,
    model_tag: str = "",
    description: str = "",
):
    """
    Register a model to model_list.yaml and SQLite index.
    """
    # 1. Update YAML (Source of Truth)
    list_path = MODELS_DIR / "model_list.yaml"
    if list_path.exists():
        with open(list_path) as f:
            data = yaml.safe_load(f) or {"models": []}
    else:
        data = {"models": []}

    safe_metrics = {}
    if isinstance(metrics, dict):
        for k in ["annualized_return", "information_ratio", "max_drawdown"]:
            if k in metrics:
                safe_metrics[k] = float(metrics[k])

    entry = {
        "id": f"{market}_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "tag": str(model_tag or ""),
        "name": str(model_tag or ""),
        "path": str(model_path).replace("\\", "/"),
        "type": config["task"]["model"]["class"],
        "market": market,
        "created_at": str(datetime.now().date()),
        "description": str(description or ""),
        "params": config["task"]["model"]["kwargs"],
        "training": {
            "dataset": config["market"] if "market" in config else "unknown",
            "period": config["task"]["dataset"]["kwargs"]["segments"]["train"],
        },
        "backtest": {
            "period": f"{config['port_analysis_config']['backtest']['start_time']} to {config['port_analysis_config']['backtest']['end_time']}",
            "metrics": safe_metrics,
        },
    }

    if run_id:
        entry["run_id"] = str(run_id)

    data["models"].append(entry)

    with open(list_path, "w") as f:
        yaml.dump(data, f, sort_keys=False)

    print(f"Registered model to {list_path}")

    # 2. Update SQLite (Fast Index)
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex
        from src.common import paths

        # Use dynamic artifacts dir to respect test environments
        artifacts_dir = paths.get_artifacts_dir()
        db_path = resolve_metadata_db_path(artifacts_dir)
        ModelRegistryIndex(db_path=db_path).upsert_entry(entry)
    except Exception as e:
        print(f"Warning: Failed to sync model registry to SQLite: {e}")

    return entry
