import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import PROJECT_ROOT, get_job_coordinator, get_job_service
from src.common.paths import (
    ARTIFACTS_DIR,
    DASHBOARD_DB_PATH,
    MLRUNS_DIR,
    MODELS_DIR,
    REPORTS_DIR,
    RUNS_DIR,
)

router = APIRouter(tags=["system"])


@router.get("/thought_stream")
def get_thought_stream(limit: int = Query(50, ge=1, le=500)):
    """
    Returns the latest structured agent thought logs from artifacts/agent_thought_stream.json.
    Used for showing real-time Agent reasoning in the Dashboard.
    """
    stream_path = ARTIFACTS_DIR / "agent_thought_stream.json"
    if not stream_path.exists():
        return {"ok": True, "stream": []}

    try:
        with stream_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            # Return last N entries
            return {"ok": True, "stream": data[-limit:] if isinstance(data, list) else []}
    except Exception as e:
        return {"ok": False, "error": str(e), "stream": []}


@router.get("/paths")
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


@router.get("/docs/main")
def get_main_system_doc():
    """
    Return the SSOT user/developer guide markdown that is rendered in WebUI Docs.
    """
    doc_path = (
        PROJECT_ROOT
        / "agents"
        / "developer"
        / "docs"
        / "design"
        / "2026-03-02_trading_platform_user_developer_guide.md"
    )
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


@router.get("/docs/methodology")
def get_methodology_doc():
    """
    Return the model training methodology markdown.
    """
    doc_path = PROJECT_ROOT / "docs" / "methodology.md"
    if not doc_path.exists():
        raise HTTPException(status_code=404, detail="methodology doc not found")
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


@router.post("/panic")
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

        # 1. Update DB state immediately
        js.update_job(
            job_id,
            status="failed",
            finished_at=now,
            exit_code=-2,
            error=f"SYSTEM_PANIC: {reason}",
        )

        # 2. Try to kill the physical process if it is registered
        if js.kill_job(job_id):
            halted += 1
        else:
            # Even if not in registry (maybe just started or in another process),
            # we at least marked it as failed in DB.
            pass

    return {
        "ok": True,
        "halted_jobs": halted,
        "total_marked_failed": len(running),
        "reason": reason,
        "triggered_at": now,
    }


# Non-workflow safe commands (data_update, arena_settle stay explicit)
_EXPLICIT_SAFE_COMMANDS = {
    "data_update": ["uv", "run", "python", "scripts/collect_data.py"],
    "arena_settle": ["uv", "run", "python", "scripts/arena_settle.py"],
}

# Workflow commands use the shared envelope from src.workflows.commands
_WORKFLOW_ACTIONS = {"train", "backtest"}


def _build_safe_command(task_key: str, args: list[str]) -> list[str] | None:
    """Build a safe command list for the given task key.

    Returns the command list, or None if the task_key is not valid.
    """
    from src.workflows.commands import WorkflowCommandEnvelope

    if task_key in _EXPLICIT_SAFE_COMMANDS:
        return list(_EXPLICIT_SAFE_COMMANDS[task_key])

    if task_key not in _WORKFLOW_ACTIONS:
        return None

    # Parse market and model_type from args
    market = "cn"
    model_type = "lgbm"
    for i, a in enumerate(args):
        if a == "--market" and i + 1 < len(args):
            market = args[i + 1]
        elif a == "--model_type" and i + 1 < len(args):
            model_type = args[i + 1]

    mode = "train" if task_key == "train" else "rebacktest"
    try:
        envelope = WorkflowCommandEnvelope.from_backtest_request(
            market=market,
            model_type=model_type,
            mode=mode,
        )
        return envelope.to_argv(python_exe="uv run python")
    except Exception:
        return None


@router.post("/exec")
def execute_system_command(payload: dict):
    task_key = str(payload.get("task") or "").strip()
    args = payload.get("args") or []

    allowed_keys = list(_EXPLICIT_SAFE_COMMANDS.keys()) + list(_WORKFLOW_ACTIONS)
    base_cmd = _build_safe_command(task_key, args)
    if base_cmd is None:
        raise HTTPException(status_code=400, detail=f"Invalid task. Allowed: {allowed_keys}")

    # Sanitize args: only allow strings, no shell injection possible with Popen(list)
    sanitized_args = [str(a) for a in args if ";" not in str(a) and "&" not in str(a)]
    full_cmd = base_cmd + sanitized_args

    job_id = uuid.uuid4().hex
    job_type = f"system_{task_key}"

    log_path = RUNS_DIR / f"dashboard_exec_{job_id}.log"
    job = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(log_path),
        "commands": [full_cmd],
    }

    response = get_job_coordinator().submit_response(job)
    response["command"] = " ".join(full_cmd)
    return response
