from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

from src.assistant.job_service import JobService
from src.assistant.report_index import ReportIndex
from src.common.paths import RUNS_DIR


class ReportService:
    def __init__(self, *, project_root: Path, report_index: ReportIndex, job_service: JobService):
        self._project_root = project_root
        self._report_index = report_index
        self._job_service = job_service

    def list_reports(self, limit: int = 100, report_type: str | None = None, ref_id: str | None = None) -> list[dict]:
        rows = self._report_index.list_reports(limit=limit, report_type=report_type, ref_id=ref_id)
        decoded = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            d = dict(r)
            d["formats"] = self._safe_json_loads(str(d.get("formats_json") or ""), default=[])
            d["paths"] = self._safe_json_loads(str(d.get("paths_json") or ""), default={})
            d["meta"] = self._safe_json_loads(str(d.get("meta_json") or ""), default={})
            decoded.append(d)
        return decoded

    def get_report(self, report_id: str) -> dict | None:
        return self._report_index.get_report(report_id)

    def create_export_job(self, payload: dict) -> dict:
        type_filter = str(payload.get("type") or "all").strip() or "all"
        try:
            limit = int(payload.get("limit") or 100)
        except Exception:
            limit = 100
        
        job_id = uuid.uuid4().hex
        log_path = RUNS_DIR / f"dashboard_reports_export_{job_id}.log"
        cmd = [
            sys.executable,
            "scripts/export_reports_zip.py",
            "--type",
            type_filter,
            "--limit",
            str(limit),
        ]

        return {
            "id": job_id,
            "type": "reports_export",
            "status": "queued",
            "created_at": time.time(),
            "log_path": str(log_path),
            "commands": [cmd],
        }

    def _safe_json_loads(self, value: str | None, *, default):
        if not value:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default
