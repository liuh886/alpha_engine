import math
from copy import deepcopy
from datetime import datetime
from numbers import Real
from pathlib import Path

import yaml

from src.common.logging import get_logger
from src.common.paths import MODELS_DIR

logger = get_logger(__name__)


def _determine_stage(walk_forward: dict | None) -> str:
    """Determine the initial stage based on walk-forward results.

    Fail-closed: if walk-forward is missing or did not pass, the model
    starts as CANDIDATE -- never STAGING or RECOMMENDED.
    """
    if not isinstance(walk_forward, dict):
        return "CANDIDATE"
    if walk_forward.get("gate_passed") is not True:
        return "CANDIDATE"
    return "STAGING"


def register_model(
    market: str,
    model_path: Path,
    config: dict,
    metrics: dict = None,
    run_id: str = None,
    model_tag: str = "",
    description: str = "",
    walk_forward: dict = None,
    artifact_id: str = "",
    artifact_config: dict = None,
):
    """
    Register a model to model_list.yaml and SQLite index.

    Stage is determined by walk-forward gate status:
    - walk-forward passes  -> STAGING
    - walk-forward fails   -> CANDIDATE
    - walk-forward missing -> CANDIDATE
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
        for key, value in metrics.items():
            if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value):
                safe_metrics[str(key)] = float(value)

    version_id = f"{market}_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Determine stage from walk-forward results (fail-closed)
    stage = _determine_stage(walk_forward)

    entry = {
        "id": version_id,
        "tag": str(model_tag or ""),
        "name": str(model_tag or ""),
        "path": str(model_path).replace("\\", "/"),
        "type": config["task"]["model"]["class"],
        "market": market,
        "created_at": str(datetime.now().date()),
        "stage": stage,
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

    if walk_forward:
        bound_walk_forward = deepcopy(walk_forward)
        bound_walk_forward["model_id"] = version_id
        if artifact_id:
            bound_walk_forward["artifact_id"] = str(artifact_id)
        entry["walk_forward"] = bound_walk_forward
        # Propagate walk-forward gate status to top-level for easy filtering
        if bound_walk_forward.get("gate_passed") is False:
            entry["gate_passed"] = False
            entry["gate_failures"] = bound_walk_forward.get("gate_failures", [])
        elif bound_walk_forward.get("gate_passed") is True:
            entry["gate_passed"] = True

    if artifact_id:
        entry["artifact_id"] = str(artifact_id)
    if isinstance(artifact_config, dict):
        entry["artifact_config"] = artifact_config

    data["models"].append(entry)

    with open(list_path, "w") as f:
        yaml.dump(data, f, sort_keys=False)

    logger.info("Registered model", path=str(list_path), stage=stage)

    # 2. Update SQLite (Fast Index) -- use validate=True for fail-closed behavior
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex
        from src.common import paths

        # Use dynamic artifacts dir to respect test environments
        artifacts_dir = paths.get_artifacts_dir()
        db_path = resolve_metadata_db_path(artifacts_dir)
        ModelRegistryIndex(db_path=db_path).upsert_entry(entry, validate=True)
    except Exception as e:
        logger.warning("Failed to sync model registry to SQLite", error=str(e))

    return entry
