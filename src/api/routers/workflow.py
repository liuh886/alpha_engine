from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.common.paths import PROJECT_ROOT
from src.governance.service import GovernanceService
from src.workflows.hooks import get_task_slug, run_rebacktest_pipeline, run_training_pipeline

router = APIRouter(tags=["workflows"])


class WorkflowRequest(BaseModel):
    market: str = "us"
    model_type: str = "lgbm"
    profile: str = ""
    tag: str = ""
    details: dict[str, Any] | None = None


@router.post("/train")
def run_train_wf(payload: WorkflowRequest, background_tasks: BackgroundTasks):
    gov = GovernanceService(PROJECT_ROOT)
    get_task_slug("run", payload.market)

    # Check if already running (mutex)
    active = [
        w
        for w in gov.query_workflows(status="RUNNING")
        if w["market"] == str(payload.market).upper() and "Pipeline Run" in str(w["name"])
    ]
    if active:
        raise HTTPException(
            status_code=409, detail=f"Workflow already running: {active[0]['workflow_id']}"
        )

    background_tasks.add_task(
        run_training_pipeline,
        market=payload.market,
        model_type=payload.model_type,
        profile=payload.profile,
        tag=payload.tag,
        details=payload.details,
    )
    return {"ok": True, "message": "Training workflow started in background"}


@router.post("/backtest")
def run_backtest_wf(payload: WorkflowRequest, background_tasks: BackgroundTasks):
    gov = GovernanceService(PROJECT_ROOT)
    get_task_slug("rebacktest", payload.market)

    active = [
        w
        for w in gov.query_workflows(status="RUNNING")
        if w["market"] == str(payload.market).upper() and "Rebacktest" in str(w["name"])
    ]
    if active:
        raise HTTPException(
            status_code=409, detail=f"Workflow already running: {active[0]['workflow_id']}"
        )

    background_tasks.add_task(
        run_rebacktest_pipeline,
        market=payload.market,
        model_type=payload.model_type,
        profile=payload.profile,
        tag=payload.tag,
        details=payload.details,
    )
    return {"ok": True, "message": "Backtest workflow started in background"}


@router.get("/status")
def list_workflows(status: str | None = None, limit: int = 20):
    gov = GovernanceService(PROJECT_ROOT)
    return gov.query_workflows(status=status, limit=limit)
