"""Walk-forward validation API endpoints."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter(tags=["walk-forward"])

# In-memory job store; production would use the shared JobService.
_jobs: dict[str, dict[str, Any]] = {}

# Directory for persisted walk-forward results.
_WF_DIR: Path | None = None


def _get_wf_dir() -> Path:
    """Return the artifacts/walk_forward directory, creating it if needed."""
    global _WF_DIR
    if _WF_DIR is None:
        from src.common.paths import ARTIFACTS_DIR

        _WF_DIR = ARTIFACTS_DIR / "walk_forward"
    _WF_DIR.mkdir(parents=True, exist_ok=True)
    return _WF_DIR


def _persist_result(job_id: str, result_dict: dict[str, Any]) -> Path:
    """Save a walk-forward result to a JSON file in the artifacts directory."""
    wf_dir = _get_wf_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    market = result_dict.get("market", "unknown")
    file_path = wf_dir / f"{market}_{ts}_{job_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2, default=str)
    log.info("Persisted walk-forward result", file=str(file_path))
    return file_path


def _load_persisted_result(job_id: str) -> dict[str, Any] | None:
    """Try to load a persisted result for the given job_id from disk."""
    wf_dir = _get_wf_dir()
    for p in wf_dir.glob(f"*_{job_id}.json"):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


class WalkForwardRequest(BaseModel):
    """Request body for walk-forward validation."""

    market: str = "us"
    model_type: str = "lgbm"
    train_start: str = "2021-01-01"
    train_end: str = ""
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
        result_dict = asdict(result)
        # Convert None values to null-safe representation for JSON
        for split in result_dict.get("splits", []):
            if split.get("ic") is None:
                split["ic"] = None
            if split.get("rank_ic") is None:
                split["rank_ic"] = None
        _jobs[job_id]["status"] = "succeeded"
        _jobs[job_id]["result"] = result_dict
        # Persist to disk so results survive restarts.
        try:
            file_path = _persist_result(job_id, result_dict)
            _jobs[job_id]["persisted_file"] = str(file_path)
        except Exception:
            log.warning("Failed to persist walk-forward result", job_id=job_id, exc_info=True)
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
    Falls back to persisted JSON files when the in-memory cache misses
    (e.g. after a server restart).
    """
    job = _jobs.get(job_id)
    if job:
        return {"ok": True, "job_id": job_id, **job}

    # Fallback: try loading from persisted files on disk.
    persisted = _load_persisted_result(job_id)
    if persisted:
        return {
            "ok": True,
            "job_id": job_id,
            "status": "succeeded",
            "result": persisted,
            "source": "disk",
        }

    raise HTTPException(status_code=404, detail="job not found")
