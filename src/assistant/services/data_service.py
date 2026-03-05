from __future__ import annotations

from pathlib import Path

from src.dashboard.data_update_job import create_data_update_job


class DataService:
    def __init__(self, *, project_root: str | Path, python_exe: str):
        self._project_root = Path(project_root)
        self._python_exe = str(python_exe)

    def create_update_job_from_payload(self, payload: dict) -> dict:
        payload = payload or {}
        full = bool(payload.get("full") or False)
        start = str(payload.get("start") or "2020-01-01").strip() or "2020-01-01"
        lookback_days = payload.get("lookback_days")
        try:
            lookback_days = int(lookback_days) if lookback_days is not None else 30
        except Exception:
            lookback_days = 30
        if lookback_days < 0:
            lookback_days = 0

        return create_data_update_job(
            project_root=self._project_root,
            python_exe=self._python_exe,
            full=full,
            start=start,
            lookback_days=lookback_days,
        )

