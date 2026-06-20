from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.common.paths import PROJECT_ROOT
from src.governance.service import GovernanceService
from src.research.workflow_runtime import create_research_workflow
from src.research.workflow_types import ResearchWorkflowRequest
from src.workflows.hooks import get_task_slug, run_rebacktest_pipeline, run_training_pipeline

logger = structlog.get_logger()

router = APIRouter(tags=["workflows"])


class WorkflowRequest(BaseModel):
    market: str = "us"
    model_type: str = "lgbm"
    profile: str = ""
    tag: str = ""
    details: dict[str, Any] | None = None


class ResearchCycleRequest(BaseModel):
    market: str = "us"
    goal: str = "Find alpha factors"
    auto_promote: bool = True


@router.post("/train")
def run_train_wf(payload: WorkflowRequest, background_tasks: BackgroundTasks):
    gov = GovernanceService(PROJECT_ROOT)
    workflow_id = get_task_slug("run", payload.market)

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
    return {"ok": True, "workflow_id": workflow_id, "message": "Training workflow started in background"}


@router.post("/backtest")
def run_backtest_wf(payload: WorkflowRequest, background_tasks: BackgroundTasks):
    gov = GovernanceService(PROJECT_ROOT)
    workflow_id = get_task_slug("rebacktest", payload.market)

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
    return {"ok": True, "workflow_id": workflow_id, "message": "Backtest workflow started in background"}


@router.post("/research-cycle")
def run_research_cycle_wf(
    payload: ResearchCycleRequest, background_tasks: BackgroundTasks
):
    """Trigger a full research cycle in the background.

    Runs: scan -> compile -> backtest -> attribute -> promote.
    """
    gov = GovernanceService(PROJECT_ROOT)
    get_task_slug("research-cycle", payload.market)

    # Mutex check
    active = [
        w
        for w in gov.query_workflows(status="RUNNING")
        if w["market"] == str(payload.market).upper() and "Research Cycle" in str(w["name"])
    ]
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Research cycle already running: {active[0]['workflow_id']}",
        )

    def _run():
        try:
            workflow_request = ResearchWorkflowRequest(
                market=payload.market,
                goal=payload.goal,
                requested_by="api.workflow.research-cycle",
                metadata={"auto_promote": payload.auto_promote},
            )
            create_research_workflow().run(workflow_request)
        except Exception as e:
            logger.warning("Research cycle failed", error=str(e))

    background_tasks.add_task(_run)
    return {"ok": True, "message": "Research cycle started in background"}


@router.get("/status")
def list_workflows(
    status: str | None = None,
    workflow_id: str | None = None,
    limit: int = 20,
):
    gov = GovernanceService(PROJECT_ROOT)
    workflows = gov.query_workflows(status=status, limit=limit)
    if workflow_id:
        workflows = [w for w in workflows if w.get("workflow_id") == workflow_id]
    return workflows
