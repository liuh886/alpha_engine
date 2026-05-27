from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import get_job_coordinator, get_report_service

router = APIRouter(tags=["reports"])

@router.get("")
def list_reports(limit: int = Query(100), type: str | None = None, ref_id: str | None = None):
    if limit <= 0:
        limit = 100
    reports = get_report_service().list_reports(limit=limit, report_type=type, ref_id=ref_id)
    return {"ok": True, "reports": reports}

@router.get("/{report_id}")
def get_report(report_id: str):
    if not report_id:
        raise HTTPException(status_code=400, detail="missing report id")
    row = get_report_service().get_report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return {"ok": True, "report": row}

@router.post("/export")
def export_reports(payload: dict):
    job = get_report_service().create_export_job(payload)
    return get_job_coordinator().submit_response(job)
