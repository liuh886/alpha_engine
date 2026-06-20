from __future__ import annotations

from src.api.routers.workflow import ResearchCycleRequest, run_research_cycle_wf
from src.research.workflow_types import ResearchWorkflowRequest


class ImmediateBackgroundTasks:
    def add_task(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


class FakeGovernanceService:
    def __init__(self, _project_root):
        pass

    def query_workflows(self, status=None, limit=20):
        return []


def test_workflow_research_cycle_submits_research_workflow(monkeypatch):
    import src.api.routers.workflow as workflow_router

    calls: list[ResearchWorkflowRequest] = []

    class FakeWorkflow:
        def run(self, request: ResearchWorkflowRequest):
            calls.append(request)

    monkeypatch.setattr(workflow_router, "GovernanceService", FakeGovernanceService)
    monkeypatch.setattr(workflow_router, "create_research_workflow", FakeWorkflow)

    response = run_research_cycle_wf(
        ResearchCycleRequest(market="cn", goal="adapter workflow", auto_promote=False),
        ImmediateBackgroundTasks(),
    )

    assert response["ok"] is True
    assert len(calls) == 1
    assert calls[0].market == "cn"
    assert calls[0].goal == "adapter workflow"
    assert calls[0].requested_by == "api.workflow.research-cycle"
    assert calls[0].metadata == {"auto_promote": False}
