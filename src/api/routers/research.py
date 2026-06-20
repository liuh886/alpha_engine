"""Research Pipeline API — Observable research workflow endpoints.

Endpoints:
    POST /research/run          — Start a new research run
    GET  /research/runs         — List all research runs
    GET  /research/runs/{id}    — Get run details
    GET  /research/runs/{id}/steps — Get step-by-step status
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from src.research.workflow_runtime import create_research_workflow
from src.research.workflow_types import ResearchWorkflowRequest, utc_now

logger = structlog.get_logger()

router = APIRouter(prefix="/research", tags=["research"])


class ResearchRunRequest(BaseModel):
    """Request to start a research run."""
    market: str = "cn"
    goal: str = "Find alpha factors"
    model_type: str = "lgbm"


@router.post("/run")
def start_research_run(
    request: ResearchRunRequest,
    background_tasks: BackgroundTasks,
):
    """Submit a canonical research workflow run in the background."""
    run_id = f"rw_{utc_now().replace(':', '').replace('-', '')}"
    workflow_request = ResearchWorkflowRequest(
        market=request.market,
        goal=request.goal,
        model_type=request.model_type,
        run_id=run_id,
        requested_by="api.research.run",
    )

    def _run():
        try:
            result = create_research_workflow().run(workflow_request)
            logger.info("research_run_completed_api", run_id=result.run_id)
        except Exception as e:
            logger.error("research_run_failed_api", run_id=run_id, error=str(e))

    background_tasks.add_task(_run)

    return {
        "ok": True,
        "run_id": run_id,
        "message": f"Research run started for {request.market} market",
    }


@router.get("/runs")
def list_research_runs(
    market: str = Query(None, description="Filter by market"),
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(20, description="Max runs to return"),
):
    """List all research runs."""
    import json
    from pathlib import Path

    runs = []
    workflow_runs = create_research_workflow().list_runs(limit=limit)
    for run_data in workflow_runs:
        req = run_data.get("request", {})
        if market and req.get("market") != market:
            continue
        if status and run_data.get("status") != status:
            continue
        steps = run_data.get("steps", [])
        runs.append({
            "run_id": run_data["run_id"],
            "market": req.get("market"),
            "goal": req.get("goal"),
            "status": run_data.get("status"),
            "recommendation": run_data.get("evidence_bundle_id"),
            "created_at": run_data.get("started_at"),
            "completed_at": run_data.get("completed_at"),
            "n_steps": len(steps),
            "n_completed": sum(1 for s in steps if s.get("status") == "completed"),
            "n_failed": sum(1 for s in steps if s.get("status") == "failed"),
        })

    if len(runs) >= limit:
        return {"ok": True, "runs": runs[:limit], "total": len(runs[:limit])}

    runs_dir = Path("artifacts/research_runs")
    if not runs_dir.exists():
        return {"ok": True, "runs": runs, "total": len(runs)}

    for f in sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f) as fh:
                run_data = json.load(fh)

            # Apply filters
            if market and run_data.get("market") != market:
                continue
            if status and run_data.get("status") != status:
                continue

            runs.append({
                "run_id": run_data["run_id"],
                "market": run_data["market"],
                "goal": run_data["goal"],
                "status": run_data["status"],
                "recommendation": run_data.get("recommendation"),
                "created_at": run_data["created_at"],
                "completed_at": run_data.get("completed_at"),
                "n_steps": run_data.get("n_steps", 0),
                "n_completed": run_data.get("n_completed", 0),
                "n_failed": run_data.get("n_failed", 0),
            })
        except Exception:
            continue

        if len(runs) >= limit:
            break

    return {"ok": True, "runs": runs, "total": len(runs)}


@router.get("/runs/{run_id}")
def get_research_run(run_id: str):
    """Get details of a specific research run."""
    import json
    from pathlib import Path

    workflow_path = Path(f"artifacts/research_workflows/{run_id}.json")
    if workflow_path.exists():
        with open(workflow_path) as f:
            run_data = json.load(f)
        return {"ok": True, "run": run_data}

    run_path = Path(f"artifacts/research_runs/{run_id}.json")
    if not run_path.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    with open(run_path) as f:
        run_data = json.load(f)

    return {"ok": True, "run": run_data}


@router.get("/runs/{run_id}/steps")
def get_research_run_steps(run_id: str):
    """Get step-by-step status of a research run."""
    import json
    from pathlib import Path

    workflow_path = Path(f"artifacts/research_workflows/{run_id}.json")
    if workflow_path.exists():
        with open(workflow_path) as f:
            run_data = json.load(f)
        steps = run_data.get("steps", [])
        return {
            "ok": True,
            "run_id": run_id,
            "steps": steps,
            "summary": {
                "total": len(steps),
                "completed": sum(1 for s in steps if s["status"] == "completed"),
                "failed": sum(1 for s in steps if s["status"] == "failed"),
                "pending": sum(1 for s in steps if s["status"] == "pending"),
            },
        }

    run_path = Path(f"artifacts/research_runs/{run_id}.json")
    if not run_path.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    with open(run_path) as f:
        run_data = json.load(f)

    steps = run_data.get("steps", [])
    return {
        "ok": True,
        "run_id": run_id,
        "steps": steps,
        "summary": {
            "total": len(steps),
            "completed": sum(1 for s in steps if s["status"] == "completed"),
            "failed": sum(1 for s in steps if s["status"] == "failed"),
            "pending": sum(1 for s in steps if s["status"] == "pending"),
        },
    }
