"""Runtime factory for the canonical Research Workflow."""

from __future__ import annotations

from src.research.workflow import ResearchWorkflow
from src.research.workflow_legacy import LegacyResearchPipelineExecutor


def create_research_workflow() -> ResearchWorkflow:
    """Create the production workflow with the current legacy execution adapter."""

    return ResearchWorkflow(executor=LegacyResearchPipelineExecutor())
