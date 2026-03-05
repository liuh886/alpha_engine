from __future__ import annotations

import time
from typing import Any

from src.agents.core.base_agent import BaseAgent
from src.agents.tools.governance_tools import format_thought_stream_for_report


class DeveloperAgent(BaseAgent):
    """
    Developer Agent (Architecture + Delivery)
    Owns architecture planning and implementation guidance tasks.
    """

    def __init__(self, llm_client=None):
        super().__init__(model_name="gpt-4o", max_context_tokens=2000)
        self.llm = llm_client
        self.system_prompt = self.generate_chain_of_thought_prompt(
            self.compress_context(
                """You are the Developer Agent of the Agentic Alpha Engine.
You own architecture evolution and implementation planning quality.
You must:
1. Translate product intent into executable engineering plans.
2. Keep design docs and runtime behavior aligned.
3. Distill high-value reusable engineering lessons after each delivery cycle.
"""
            )
        )

    def plan_execution(self, topic: str = "general", **kwargs: Any) -> dict[str, Any]:
        format_thought_stream_for_report(
            "Developer Agent",
            "info",
            f"Planning execution package for topic: {topic}",
        )
        time.sleep(0.2)
        return {
            "status": "ok",
            "topic": topic,
            "next_step": "Break down into design, implementation, and verification tasks.",
        }

