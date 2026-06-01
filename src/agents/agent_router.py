from __future__ import annotations

from typing import Any

from src.common.logging import get_logger


class AgentRouter:
    """
    Simplified agent router that delegates all tasks to ResearchAssistant.

    The old multi-agent routing (Alpha/Risk/Governance/Developer) has been
    consolidated into a single ResearchAssistant.  This class preserves
    backward-compatible ``route_task`` signatures so existing callers
    (e.g. ``chat.py`` router) continue to work without changes.
    """

    def __init__(self, quality_index=None, model_index=None, run_index=None):
        self._quality_index = quality_index
        self._model_index = model_index
        self._run_index = run_index
        self.logger = get_logger("AgentRouter")

    def route_task(self, task_type: str, *args, **kwargs) -> Any:
        """
        Route a task to the unified ResearchAssistant.

        Supported task_type values (all map to ResearchAssistant):
          - "alpha"       -> analyze_factors()
          - "risk"        -> assess_risk()
          - "governance"  -> audit_run("latest")
          - "developer"   -> describe_architecture()
        """
        from src.agents.research_assistant import ResearchAssistant

        assistant = ResearchAssistant(quality_index=self._quality_index)
        task = task_type.lower()

        try:
            if task == "alpha":
                market = kwargs.get("market", "us")
                result = assistant.analyze_factors(market)
                self.logger.info("Routed 'alpha' -> ResearchAssistant.analyze_factors")
                return result

            if task == "risk":
                result = assistant.assess_risk()
                self.logger.info("Routed 'risk' -> ResearchAssistant.assess_risk")
                return result

            if task == "governance":
                result = assistant.audit_run("latest")
                self.logger.info("Routed 'governance' -> ResearchAssistant.audit_run")
                return result

            if task == "developer":
                desc = assistant.describe_architecture()
                self.logger.info("Routed 'developer' -> ResearchAssistant.describe_architecture")
                return {"status": "ok", "topic": "architecture", "description": desc}

            # Fallback for unknown task types
            self.logger.warning(f"Unknown task type '{task_type}', attempting chat fallback.")
            return self._fallback_handler(task_type, *args, **kwargs)

        except Exception as e:
            self.logger.error(f"Agent execution failed for '{task_type}': {e}")
            return {"ok": False, "error": str(e)}

    def _fallback_handler(self, task_type: str, *args, **kwargs):
        """Safe fallback for undefined task types."""
        return {
            "status": "error",
            "message": f"Intent '{task_type}' could not be resolved. Action suppressed for safety.",
            "fallback_engaged": True,
        }
