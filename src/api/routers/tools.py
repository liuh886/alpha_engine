from __future__ import annotations

from fastapi import APIRouter

from src.api.dependencies import get_quality_index

router = APIRouter(tags=["tools"])


def _get_assistant():
    """Lazy-import and instantiate ResearchAssistant with available dependencies."""
    from src.agents.research_assistant import ResearchAssistant

    return ResearchAssistant(quality_index=get_quality_index())


@router.post("/analyze-factors")
async def analyze_factors(market: str = "us"):
    """Run factor analysis (replaces Alpha Agent)."""
    assistant = _get_assistant()
    return assistant.analyze_factors(market)


@router.post("/suggest-hyperparams")
async def suggest_hyperparams():
    """Suggest LightGBM hyperparameter adjustments."""
    assistant = _get_assistant()
    result = assistant.suggest_hyperparams()
    return {"ok": True, **result}


@router.post("/assess-risk")
async def assess_risk(run_id: str | None = None):
    """Run risk assessment (replaces Risk Agent)."""
    assistant = _get_assistant()
    return assistant.assess_risk(run_id)


@router.get("/data-quality/{market}")
async def data_quality(market: str):
    """Check data quality for a market (replaces Alpha Agent data scout)."""
    assistant = _get_assistant()
    return assistant.check_data_quality(market)


@router.post("/audit-run/{run_id}")
async def audit_run(run_id: str):
    """Audit a backtest run for consistency (replaces Governance Agent)."""
    assistant = _get_assistant()
    return assistant.audit_run(run_id)


@router.get("/capabilities")
async def list_capabilities():
    """List all available research tools."""
    assistant = _get_assistant()
    return {"ok": True, "capabilities": assistant.list_capabilities()}


@router.post("/chat")
async def tools_chat(message: str):
    """Natural language interface to all research tools."""
    assistant = _get_assistant()
    reply = await assistant.chat(message)
    return {"ok": True, "reply": reply}
