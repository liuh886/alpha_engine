from fastapi import APIRouter
from pydantic import BaseModel

from src.api.dependencies import get_model_index, get_quality_index, get_run_index

router = APIRouter(tags=["agent"])


class ChatRequest(BaseModel):
    message: str
    agent_type: str = "alpha"


@router.post("/chat")
async def agent_chat(req: ChatRequest):
    """
    [ROADMAP 61/38] Agent Router & Chat UI
    Real backend integration mapping the frontend Copilot UI to the Python AgentRouter.
    """
    try:
        from src.agents.agent_router import AgentRouter

        # Inject real dependencies into the Router
        router_instance = AgentRouter(
            quality_index=get_quality_index(),
            model_index=get_model_index(),
            run_index=get_run_index()
        )
        
        # Dispatch to the appropriate agent.
        result = router_instance.route_task(req.agent_type, market="us")

        if req.agent_type == "alpha":
            reply = f"**AgentRouter Dispatch**: AlphaAgent initiated research cycle. Result: {result.get('status', 'OK')}. Hypothesis: {result.get('hypothesis', 'N/A')}"
        elif req.agent_type == "developer":
            reply = f"**AgentRouter Dispatch**: DeveloperAgent planning execution. Next step: {result.get('next_step', 'N/A')}"
        else:
            reply = f"**AgentRouter Dispatch**: {req.agent_type.capitalize()}Agent processed request."

        return {"ok": True, "reply": reply, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
