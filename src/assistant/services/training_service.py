from __future__ import annotations

import time
import uuid
from pathlib import Path

from src.common.paths import RUNS_DIR


class TrainingService:
    def __init__(self, *, project_root: str | Path, python_exe: str):
        self._project_root = Path(project_root)
        self._python_exe = str(python_exe)

    def create_job_from_payload(self, payload: dict) -> dict:
        payload = payload or {}
        market = str(payload.get("market") or "").lower().strip()
        if market not in {"cn", "us"}:
            raise ValueError("market is required and must be 'cn' or 'us'")

        tag = str(payload.get("tag") or "").strip()
        if not tag:
            raise ValueError("tag is required for training to ensure traceability")

        model_type = str(payload.get("model_type") or "lgbm").lower().strip() or "lgbm"
        profile_path = (
            str(payload.get("profile_path") or "configs/strategy_profile.json").strip()
            or "configs/strategy_profile.json"
        )

        job_id = uuid.uuid4().hex
        log_path = RUNS_DIR / f"dashboard_train_{market}_{job_id}.log"

        cmd = [
            self._python_exe,
            "-m",
            "src.orchestrator",
            "run",
            "--market",
            market,
            "--model_type",
            model_type,
            "--profile",
            profile_path,
            "--tag",
            tag,
        ]

        return {
            "id": job_id,
            "type": "train",
            "market": market,
            "model_type": model_type,
            "tag": tag,
            "status": "queued",
            "created_at": time.time(),
            "log_path": str(log_path),
            "commands": [cmd],
        }
