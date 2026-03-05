import sys
import uuid
import time
import threading
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from src.api.dependencies import get_job_service, PROJECT_ROOT
from src.common.paths import RUNS_DIR, DASHBOARD_DB_PATH, MLRUNS_DIR, MODELS_DIR, REPORTS_DIR, ARTIFACTS_DIR

router = APIRouter(tags=["system"])

@router.get("/health")
def health_check():
    return {"ok": True}

@router.get("/api/jobs")
def list_jobs(limit: int = Query(100), status: str | None = None):
    if limit <= 0:
        limit = 100
    jobs = get_job_service().list_jobs(limit=limit, status=status)
    return {"ok": True, "jobs": jobs}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = get_job_service().get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "job": job}


@router.get("/api/jobs/{job_id}/stream")
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
                payload = json.dumps({"job_id": str(job_id), "error": "job not found"}, ensure_ascii=False)
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
                            payload = json.dumps({"job_id": str(job_id), "line": line}, ensure_ascii=False)
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


@router.get("/api/system/paths")
def get_system_paths():
    js = get_job_service()
    return {
        "ok": True,
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "dashboard_db_path": str(DASHBOARD_DB_PATH),
            "metadata_db_path": str(js.db_path),
            "data_dir": str(PROJECT_ROOT / "data"),
            "artifacts_dir": str(ARTIFACTS_DIR),
            "reports_dir": str(REPORTS_DIR),
            "mlruns_dir": str(MLRUNS_DIR),
            "models_dir": str(MODELS_DIR),
            "runs_dir": str(RUNS_DIR),
        },
    }


@router.get("/api/system/docs/main")
def get_main_system_doc():
    """
    Return the SSOT user/developer guide markdown that is rendered in WebUI Docs.
    """
    doc_path = PROJECT_ROOT / "agents" / "developer" / "docs" / "design" / "2026-03-02_trading_platform_user_developer_guide.md"
    if not doc_path.exists():
        raise HTTPException(status_code=404, detail="main doc not found")
    try:
        content = doc_path.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "path": str(doc_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "content": content,
            "updated_at": doc_path.stat().st_mtime,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/system/panic")
def panic_stop(payload: dict | None = None):
    payload = payload or {}
    reason = str(payload.get("reason") or "").strip() or "Triggered from dashboard kill switch"

    js = get_job_service()
    running = js.list_jobs(limit=10_000, status="running")
    now = time.time()

    halted = 0
    for job in running:
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            continue
        js.update_job(
            job_id,
            status="failed",
            finished_at=now,
            exit_code=-2,
            error=f"SYSTEM_PANIC: {reason}",
        )
        halted += 1

    return {
        "ok": True,
        "halted_jobs": halted,
        "reason": reason,
        "triggered_at": now,
    }


@router.post("/api/system/exec")
def execute_system_command(payload: dict):
    command_str = str(payload.get("command") or "").strip()
    if not command_str:
        raise HTTPException(status_code=400, detail="missing command")

    import shlex
    try:
        parts = shlex.split(command_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid command syntax: {e}")

    if not parts:
        raise HTTPException(status_code=400, detail="empty command")

    if parts[0] in ["python", "python.exe", "python3"]:
        parts[0] = sys.executable

    job_id = uuid.uuid4().hex
    job_type = "system_exec"
    if "orchestrator" in command_str:
        job_type = "orchestrator_run"
    elif "update_data" in command_str:
        job_type = "data_update"
    elif "arena_settle" in command_str:
        job_type = "arena_settle"

    log_path = RUNS_DIR / f"dashboard_exec_{job_id}.log"
    job = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(log_path),
        "commands": [parts],
    }

    get_job_service().create_job(job)
    t = threading.Thread(target=get_job_service().run_job, args=(job_id,), daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id}
