"""Runtime factory for the canonical Research Workflow.

The default executor is ``SpecBoundResearchWorkflowExecutor``, which reuses the
existing spec-bound research execution path (paradigm spec → contract identity
→ market adapter → evidence-gated promotion).
"""

from __future__ import annotations

from src.research.workflow import ResearchWorkflow
from src.research.spec_bound_workflow_executor import (
    SpecBoundResearchWorkflowExecutor,
)


def create_research_workflow() -> ResearchWorkflow:
    """Create the production workflow with the spec-bound execution adapter."""

    return ResearchWorkflow(executor=SpecBoundResearchWorkflowExecutor())
