"""
Agents package — Alpha Engine AI agents.

The former multi-agent system (Alpha, Risk, Governance, Developer) has been
consolidated into a single ``ResearchAssistant``.
"""

from __future__ import annotations

from .goal_parser import ResearchGoal, parse_research_goal  # noqa: F401
from .research_assistant import ResearchAssistant  # noqa: F401 — primary export

__all__ = ["ResearchAssistant", "ResearchGoal", "parse_research_goal"]
