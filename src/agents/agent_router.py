from typing import Dict, Any, Type
import logging
from pydantic import BaseModel
from src.agents.alpha.alpha_agent import AlphaAgent
from src.agents.developer.developer_agent import DeveloperAgent
from src.agents.governance.governance_agent import GovernanceAgent
from src.agents.risk.risk_agent import RiskAgent
from src.agents.core.base_agent import BaseAgent

class AgentRouter:
    """
    Roadmap Item [38/39/37] Agent Router
    Directs tasks to the appropriate specialized mathematical agent.
    If the requested agent doesn't exist, safely routes to a fallback behavior.
    """
    def __init__(self):
        self._registry: Dict[str, Type[BaseAgent]] = {
            "alpha": AlphaAgent,
            "governance": GovernanceAgent,
            "risk": RiskAgent,
            "developer": DeveloperAgent,
        }
        self.logger = logging.getLogger("AgentRouter")

    def route_task(self, task_type: str, *args, **kwargs) -> Any:
        """
        Dynamically instantiates the correct agent and delegates the computational task.
        """
        agent_class = self._registry.get(task_type.lower())
        
        if not agent_class:
            self.logger.warning(f"No agent registered for task type '{task_type}'. Invoking Fallback Strategy.")
            return self._fallback_handler(task_type, *args, **kwargs)
            
        try:
            agent = agent_class()
            self.logger.info(f"Successfully routed '{task_type}' to {agent.__class__.__name__}.")
            
            # Very simplistic dynamic dispatch for demo purposes. 
            # In production, each agent would have a strictly defined Interface.
            if task_type.lower() == "alpha":
                return agent.research_cycle(*args, **kwargs)
            elif task_type.lower() == "governance":
                return agent.execute_daily_routine(*args, **kwargs)
            elif task_type.lower() == "risk":
                return agent.audit_market_conditions(*args, **kwargs)
            elif task_type.lower() == "developer":
                return agent.plan_execution(*args, **kwargs)
                
        except Exception as e:
            self.logger.error(f"Agent execution failed for '{task_type}': {e}")
            raise RuntimeError(f"Agent Router failed to execute task {task_type}") from e

    def _fallback_handler(self, task_type: str, *args, **kwargs):
        """
        Safe fallback mechanism for undefined intent paths.
        """
        return {
            "status": "error",
            "message": f"Intent '{task_type}' could not be resolved. Action suppressed for safety.",
            "fallback_engaged": True
        }
