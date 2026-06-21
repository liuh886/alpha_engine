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
    Register a model to the SQLite registry (single source of truth).

    model_list.yaml is kept as a human-readable **append-only log**
    and is never used as an authoritative read source.

    Stage is determined by walk-forward gate status:
    - walk-forward passes  -> STAGING
    - walk-forward fails   -> CANDIDATE
    - walk-forward missing -> CANDIDATE
    """
    # 1. Build entry dict
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
            "period": (
                f"{config['port_analysis_config']['backtest']['start_time']} to "
                f"{config['port_analysis_config']['backtest']['end_time']}"
            ),
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
        if bound_walk_forward.get("gate_passed") is False:
            entry["gate_passed"] = False
            entry["gate_failures"] = bound_walk_forward.get("gate_failures", [])
        elif bound_walk_forward.get("gate_passed") is True:
            entry["gate_passed"] = True

    if artifact_id:
        entry["artifact_id"] = str(artifact_id)
    if isinstance(artifact_config, dict):
        entry["artifact_config"] = artifact_config

    # === STEP 1 (PRIMARY): Write to SQLite — the single source of truth ===
    sqlite_ok = False
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex
        from src.common import paths

        artifacts_dir = paths.get_artifacts_dir()
        db_path = resolve_metadata_db_path(artifacts_dir)
        registry_idx = ModelRegistryIndex(db_path=db_path)
        sqlite_ok = registry_idx.upsert_entry(entry, validate=True)
        if not sqlite_ok:
            logger.error("SQLite registry upsert returned False", version_id=version_id)
            raise RuntimeError("SQLite upsert failed")
        logger.info("Model registered in SQLite", version_id=version_id, stage=stage)
    except Exception as e:
        logger.error("CRITICAL: Failed to write model to SQLite registry", error=str(e))
        raise RuntimeError(f"Model registration aborted — SQLite write failed: {e}") from e

    # === STEP 2 (SECONDARY): Append to YAML as human-readable log ===
    list_path = MODELS_DIR / "model_list.yaml"
    try:
        if list_path.exists():
            with open(list_path) as f:
                data = yaml.safe_load(f) or {"models": []}
        else:
            data = {"models": []}

        data["models"].append(entry)

        with open(list_path, "w") as f:
            yaml.dump(data, f, sort_keys=False)

        logger.info("Model appended to YAML log", path=str(list_path), version_id=version_id)
    except Exception as e:
        # YAML is secondary — log warning but don't fail registration
        logger.warning(
            "Failed to append model to YAML log (SQLite registration succeeded)",
            error=str(e),
        )

    return entry
