import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_job_service

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs(limit: int = Query(100), status: str | None = None):
    if limit <= 0:
        limit = 100
    jobs = get_job_service().list_jobs(limit=limit, status=status)
    return {"ok": True, "jobs": jobs}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = get_job_service().get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "job": job}


@router.get("/jobs/{job_id}/stream")
def stream_job_log(job_id: str):
    js = get_job_service()
    job = js.get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    def _event_stream():
        log_offset = 0
        while True:
            current = js.get_job(str(job_id))
            if not current:
                payload = json.dumps(
                    {"job_id": str(job_id), "error": "job not found"}, ensure_ascii=False
                )
                yield f"event: error\ndata: {payload}\n\n"
                return

            log_path = str(current.get("log_path") or "").strip()
            if log_path:
                p = Path(log_path)
                if p.exists() and p.is_file():
                    try:
                        with p.open("r", encoding="utf-8", errors="replace") as f:
                            f.seek(log_offset)
                            chunk = f.read()
                            log_offset = f.tell()
                    except Exception:
                        chunk = ""
                    if chunk:
                        for line in chunk.splitlines():
                            payload = json.dumps(
                                {"job_id": str(job_id), "line": line}, ensure_ascii=False
                            )
                            yield f"data: {payload}\n\n"

            status = str(current.get("status") or "").strip().lower()
            if status in {"succeeded", "failed"}:
                payload = json.dumps({"job_id": str(job_id), "status": status}, ensure_ascii=False)
                yield f"event: done\ndata: {payload}\n\n"
                return

            yield ": keep-alive\n\n"
            time.sleep(0.5)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
