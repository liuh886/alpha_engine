import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.dependencies import get_job_coordinator, get_job_service

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


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Cancel a running or queued job. Marks it as cancelled in DB and kills the process."""
    js = get_job_service()
    job = js.get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    status = str(job.get("status") or "").strip().lower()
    if status in ("succeeded", "failed", "cancelled"):
        return {"ok": False, "error": f"Job is already {status} and cannot be cancelled"}

    # Kill the process if running
    js.kill_job(str(job_id))
    js.update_job(
        str(job_id),
        status="cancelled",
        finished_at=time.time(),
        exit_code=-3,
        error="Cancelled by user",
    )
    return {"ok": True, "job_id": str(job_id), "message": "Job cancelled"}


@router.post("/jobs/{job_id}/rerun")
def rerun_job(job_id: str):
    """Re-submit a failed or cancelled job with the same commands."""
    js = get_job_service()
    coordinator = get_job_coordinator()
    job = js.get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    status = str(job.get("status") or "").strip().lower()
    if status in ("running", "queued"):
        return {"ok": False, "error": "Job is still active; cancel it first before re-running"}

    commands = job.get("commands") or []
    if not commands:
        return {"ok": False, "error": "No commands recorded for this job; cannot re-run"}

    new_id = uuid.uuid4().hex
    new_job = {
        "id": new_id,
        "type": str(job.get("type") or "rerun"),
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(job.get("log_path") or ""),
        "commands": commands,
    }
    try:
        return coordinator.submit_response(new_job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: str, tail: int = Query(200)):
    """Return the last N lines of a job's log file."""
    js = get_job_service()
    job = js.get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    log_path = str(job.get("log_path") or "").strip()
    if not log_path:
        return {"ok": True, "job_id": str(job_id), "lines": [], "message": "No log path recorded"}

    p = Path(log_path)
    if not p.exists() or not p.is_file():
        return {"ok": True, "job_id": str(job_id), "lines": [], "message": "Log file not found"}

    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail_lines = [line.rstrip("\n\r") for line in all_lines[-max(tail, 1) :]]
        return {
            "ok": True,
            "job_id": str(job_id),
            "lines": tail_lines,
            "total_lines": len(all_lines),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "job_id": str(job_id), "lines": []}
