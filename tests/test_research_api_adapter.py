from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

from src.research.workflow_types import ResearchWorkflowRequest

ROOT = Path(__file__).resolve().parents[1]


def test_research_run_endpoint_submits_research_workflow(monkeypatch):
    from fastapi.testclient import TestClient

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import src.api.routers.research as research_router
    from api_server import app

    calls: list[ResearchWorkflowRequest] = []

    class FakeResearchWorkflow:
        def run(self, request: ResearchWorkflowRequest):
            calls.append(request)
            return SimpleNamespace(run_id=request.run_id)

    monkeypatch.setattr(research_router, "create_research_workflow", FakeResearchWorkflow)

    creds = base64.b64encode(b"admin:alpha2026").decode()
    client = TestClient(app)
    resp = client.post(
        "/api/research/run",
        json={"market": "us", "goal": "adapter test", "model_type": "lgbm"},
        headers={"Authorization": f"Basic {creds}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["run_id"].startswith("rw_")
    assert len(calls) == 1
    assert calls[0].market == "us"
    assert calls[0].goal == "adapter test"
    assert calls[0].model_type == "lgbm"
    assert calls[0].requested_by == "api.research.run"
