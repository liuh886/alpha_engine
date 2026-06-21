import sys
import time
import uuid

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import get_arena_index, get_job_coordinator, get_model_index
from src.common.paths import RUNS_DIR

router = APIRouter(tags=["arena"])


@router.get("/list")
def list_arenas(market: str | None = Query(None)):
    idx = get_arena_index()
    arenas = idx.list_arenas(market=market)
    return {"ok": True, "arenas": arenas}


@router.get("/leaderboard")
def get_arena_leaderboard(
    arena_id: str | None = Query(None),
    arena_name: str | None = Query(None),
    date: str = Query("latest"),
):
    idx = get_arena_index()
    if not arena_id and arena_name:
        a = idx.get_arena_by_name(arena_name)
        if a:
            arena_id = a["id"]

    lb = idx.get_leaderboard(arena_id=arena_id, date=date)
    resp_date = date
    if (date == "latest" or not date) and arena_id:
        resp_date = idx.get_latest_settled_date(arena_id=arena_id)

    return {"ok": True, "leaderboard": lb, "date": resp_date}


@router.post("/settle")
def settle_arena(payload: dict):
    market = str(payload.get("market") or "us").strip().lower() or "us"
    arena_name = str(payload.get("arena_name") or "").strip()
    date = str(payload.get("date") or "latest").strip() or "latest"
    seed = bool(payload.get("seed_from_model_registry") or False)
    try:
        limit = int(payload.get("limit") or 50)
    except Exception:
        limit = 50
    if limit < 0:
        limit = 0

    job_id = uuid.uuid4().hex
    log_path = RUNS_DIR / f"dashboard_arena_settle_{job_id}.log"

    cmd = [
        sys.executable,
        "scripts/arena_settle.py",
        "--market",
        market,
        "--date",
        date,
        "--limit",
        str(limit),
    ]
    if arena_name:
        cmd += ["--arena-name", arena_name]
    if seed:
        cmd += ["--seed-from-model-registry"]

    job = {
        "id": job_id,
        "type": "arena_settle",
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(log_path),
        "commands": [cmd],
    }

    return get_job_coordinator().submit_response(job)


@router.post("/participants")
def add_participant(payload: dict):
    arena_id = str(payload.get("arena_id") or "").strip()
    arena_name = str(payload.get("arena_name") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    model_version_id = str(payload.get("model_version_id") or "").strip()
    name = str(payload.get("name") or "").strip()

    if model_version_id and not run_id:
        m_ver = get_model_index().get_version(model_version_id)
        if m_ver:
            run_id = str(m_ver.get("run_id") or "")

    if not run_id:
        raise HTTPException(
            status_code=400, detail="missing run_id (or model_version_id with no bound run)"
        )

    arena_row = None
    if arena_id:
        arena_row = get_arena_index().get_arena(arena_id)
    elif arena_name:
        arena_row = get_arena_index().get_arena_by_name(arena_name)
    if not arena_row:
        raise HTTPException(status_code=404, detail="arena not found")

    a_id = str(arena_row.get("id") or "")
    try:
        participant = get_arena_index().add_participant(
            arena_id=a_id,
            name=name or model_version_id or run_id,
            run_id=run_id,
            model_version_id=model_version_id or None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "ok": True,
        "participant": participant,
        "arena": {"id": a_id, "name": arena_row.get("name")},
    }
