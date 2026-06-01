"""Walk-forward validation API endpoints."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

import structlog

log = structlog.get_logger()

router = APIRouter(tags=["walk-forward"])

# In-memory job store; production would use the shared JobService.
_jobs: dict[str, dict[str, Any]] = {}


class WalkForwardRequest(BaseModel):
    """Request body for walk-forward validation."""

    market: str = "us"
    model_type: str = "lgbm"
    train_start: str = "2021-01-01"
    train_end: str = "2026-04-03"
    test_window_months: int = 6
    step_months: int = 3


def _run_wf_job(job_id: str, payload: WalkForwardRequest) -> None:
    """Background task that executes walk-forward validation."""
    _jobs[job_id]["status"] = "running"
    try:
        from src.research.walk_forward import walk_forward_validate

        result = walk_forward_validate(
            market=payload.market,
            model_type=payload.model_type,
            train_start=payload.train_start,
            train_end=payload.train_end,
            test_window_months=payload.test_window_months,
            step_months=payload.step_months,
        )
        _jobs[job_id]["status"] = "succeeded"
        _jobs[job_id]["result"] = asdict(result)
        log.info("Walk-forward job completed", job_id=job_id)
    except Exception as exc:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)
        log.exception("Walk-forward job failed", job_id=job_id, error=str(exc))


@router.post("/walk-forward")
def start_walk_forward(
    payload: WalkForwardRequest, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Trigger an async walk-forward validation job.

    Returns a ``job_id`` that can be polled via
    ``GET /backtest/walk-forward/{job_id}``.
    """
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "pending", "params": payload.model_dump()}
    background_tasks.add_task(_run_wf_job, job_id, payload)
    log.info("Walk-forward job submitted", job_id=job_id, market=payload.market)
    return {"ok": True, "job_id": job_id}


@router.get("/walk-forward/{job_id}")
def get_walk_forward_result(job_id: str) -> dict[str, Any]:
    """Poll for walk-forward validation results.

    Status transitions: pending -> running -> succeeded / failed.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "job_id": job_id, **job}
