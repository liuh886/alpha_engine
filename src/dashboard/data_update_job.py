from __future__ import annotations

import time
import uuid
from pathlib import Path

from src.common.paths import RUNS_DIR
from src.dashboard.data_update_runner import build_update_data_commands


def create_data_update_job(
    *,
    project_root: Path,
    python_exe: str,
    full: bool = False,
    market: str = "all",
    start: str = "2020-01-01",
    lookback_days: int = 30,
) -> dict:
    job_id = uuid.uuid4().hex
    log_path = RUNS_DIR / f"dashboard_update_data_{job_id}.log"

    commands = build_update_data_commands(
        python_exe=python_exe,
        full=bool(full),
        market=str(market),
        start=str(start),
        lookback_days=int(lookback_days),
        rebuild_dashboard_db=True,
    )

    return {
        "id": job_id,
        "type": "data_update",
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(log_path),
        "commands": commands,
    }
