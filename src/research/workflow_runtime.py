"""Runtime factory for the canonical Research Workflow.

The default executor is ``SpecBoundResearchWorkflowExecutor``, which reuses the
existing spec-bound research execution path (paradigm spec → contract identity
→ market adapter → evidence-gated promotion).

``LegacyResearchPipelineExecutor`` remains available as an explicit compatibility
adapter for callers that still depend on the legacy pipeline, but no API/MCP
default path instantiates it automatically.
"""

from __future__ import annotations

from src.research.workflow import ResearchWorkflow
from src.research.spec_bound_workflow_executor import (
    SpecBoundResearchWorkflowExecutor,
)


def create_research_workflow() -> ResearchWorkflow:
    """Create the production workflow with the spec-bound execution adapter."""

    return ResearchWorkflow(executor=SpecBoundResearchWorkflowExecutor())


def create_legacy_research_workflow() -> ResearchWorkflow:
    """Explicit compatibility: create a workflow backed by the legacy pipeline.

    Prefer ``create_research_workflow`` for all new and default paths.
    """

    from src.research.workflow_legacy import LegacyResearchPipelineExecutor

    return ResearchWorkflow(executor=LegacyResearchPipelineExecutor())
