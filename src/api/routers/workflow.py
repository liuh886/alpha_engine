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

# Stale lock threshold: 4 hours
_STALE_LOCK_SECONDS = 14400

router = APIRouter(tags=["workflows"])


class WorkflowRequest(BaseModel):
    market: str = "us"
    model_type: str = "lgbm"
    profile: str = ""
    tag: str = ""
    snapshot_id: str = ""
    details: dict[str, Any] | None = None


class ResearchCycleRequest(BaseModel):
    market: str = "us"
    goal: str = "Find alpha factors"
    auto_promote: bool = True


def _check_workflow_mutex(gov: GovernanceService, market: str, name_pattern: str) -> None:
    """Check for running workflows with stale-lock override."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    active = [
        w
        for w in gov.query_workflows(status="RUNNING")
        if w["market"] == str(market).upper() and name_pattern in str(w["name"])
    ]
    if not active:
        return

    # Check if the running workflow is stale (older than 4 hours)
    for w in active:
        updated_at_str = w.get("updated_at")
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                age_seconds = (now - updated_at).total_seconds()
            except (ValueError, TypeError):
                age_seconds = 0
        else:
            age_seconds = 0

        if age_seconds > _STALE_LOCK_SECONDS:
            logger.warning(
                "Workflow is RUNNING but stale, overriding lock",
                workflow_id=w["workflow_id"],
                age_seconds=int(age_seconds),
            )
            gov.update_workflow_status(w["workflow_id"], status="FAILED")
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Workflow already running: {w['workflow_id']}",
            )


@router.post("/train")
def run_train_wf(payload: WorkflowRequest, background_tasks: BackgroundTasks):
    gov = GovernanceService(PROJECT_ROOT)
    workflow_id = get_task_slug("run", payload.market)

    _check_workflow_mutex(gov, payload.market, "Pipeline Run")

    # Extract snapshot_id from top-level field or nested details
    snapshot_id = payload.snapshot_id or (payload.details or {}).get("snapshot_id", "")

    background_tasks.add_task(
        run_training_pipeline,
        market=payload.market,
        model_type=payload.model_type,
        profile=payload.profile,
        tag=payload.tag,
        snapshot_id=snapshot_id,
        details=payload.details,
    )
    return {
        "ok": True,
        "workflow_id": workflow_id,
        "message": "Training workflow started in background",
    }


@router.post("/backtest")
def run_backtest_wf(payload: WorkflowRequest, background_tasks: BackgroundTasks):
    gov = GovernanceService(PROJECT_ROOT)
    workflow_id = get_task_slug("rebacktest", payload.market)

    _check_workflow_mutex(gov, payload.market, "Rebacktest")

    background_tasks.add_task(
        run_rebacktest_pipeline,
        market=payload.market,
        model_type=payload.model_type,
        profile=payload.profile,
        tag=payload.tag,
        details=payload.details,
    )
    return {
        "ok": True,
        "workflow_id": workflow_id,
        "message": "Backtest workflow started in background",
    }


@router.post("/research-cycle")
def run_research_cycle_wf(payload: ResearchCycleRequest, background_tasks: BackgroundTasks):
    """Trigger a spec-bound research workflow in the background.

    Executes the market's fixed paradigm spec through the canonical
    ResearchStep sequence with identity-proven execution and
    evidence-gated promotion.
    """
    gov = GovernanceService(PROJECT_ROOT)
    get_task_slug("research-cycle", payload.market)

    _check_workflow_mutex(gov, payload.market, "Research Cycle")

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
