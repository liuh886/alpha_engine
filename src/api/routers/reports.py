import sys
import uuid
import time
import threading
import json
from fastapi import APIRouter, HTTPException, Query
from src.api.dependencies import get_report_index, get_job_service
from src.common.paths import RUNS_DIR

router = APIRouter(prefix="/api/reports", tags=["reports"])

def _safe_json_loads(value: str | None, *, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default

@router.get("")
def list_reports(limit: int = Query(100), type: str | None = None, ref_id: str | None = None):
    if limit <= 0:
        limit = 100
    rows = get_report_index().list_reports(limit=limit, report_type=type, ref_id=ref_id)
    decoded = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = dict(r)
        d["formats"] = _safe_json_loads(str(d.get("formats_json") or ""), default=[])
        d["paths"] = _safe_json_loads(str(d.get("paths_json") or ""), default={})
        d["meta"] = _safe_json_loads(str(d.get("meta_json") or ""), default={})
        decoded.append(d)
    return {"ok": True, "reports": decoded}

@router.get("/{report_id}")
def get_report(report_id: str):
    if not report_id:
        raise HTTPException(status_code=400, detail="missing report id")
    row = get_report_index().get_report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return {"ok": True, "report": row}

@router.post("/export")
def export_reports(payload: dict):
    type_filter = str(payload.get("type") or "all").strip() or "all"
    try:
        limit = int(payload.get("limit") or 100)
    except Exception:
        limit = 100
    if limit <= 0:
        limit = 100

    job_id = uuid.uuid4().hex
    log_path = RUNS_DIR / f"dashboard_reports_export_{job_id}.log"
    cmd = [sys.executable, "scripts/export_reports_zip.py", "--type", type_filter, "--limit", str(limit)]

    job = {
        "id": job_id,
        "type": "reports_export",
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(log_path),
        "commands": [cmd],
    }

    get_job_service().create_job(job)
    t = threading.Thread(target=get_job_service().run_job, args=(job_id,), daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id}
