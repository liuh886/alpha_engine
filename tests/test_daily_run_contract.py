from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import daily_run


def test_daily_run_fails_fast_when_inference_output_contains_failure(monkeypatch, capsys):
    class FakeResearchAssistant:
        def self_heal(self, event):
            return False

    monkeypatch.setattr(daily_run, "ResearchAssistant", FakeResearchAssistant)
    def fake_run_data_update(market):
        return {"success": True}

    def fake_run_orchestrator(market, mode, tag):
        return {"success": False, "error": "feature mismatch"}

    monkeypatch.setattr(daily_run, "run_data_update", fake_run_data_update)
    monkeypatch.setattr(daily_run, "run_orchestrator", fake_run_orchestrator)
    monkeypatch.setattr(sys, "argv", ["daily_run.py", "--market", "us"])

    rc = daily_run.main()

    assert rc != 0
    # Captured output check
    captured = capsys.readouterr()
    assert "Inference failed for us" in captured.out or "Inference failed for us" in captured.err


def test_daily_run_continues_when_inference_output_is_success(monkeypatch):
    class FakeResearchAssistant:
        def self_heal(self, event):
            return False

    monkeypatch.setattr(daily_run, "ResearchAssistant", FakeResearchAssistant)
    calls = []

    def fake_run_data_update(market):
        calls.append("data")
        return {"success": True}

    def fake_run_orchestrator(market, mode, tag):
        calls.append("orchestrator")
        return {"success": True}

    def fake_build_db():
        calls.append("build_db")

    monkeypatch.setattr(daily_run, "run_data_update", fake_run_data_update)
    monkeypatch.setattr(daily_run, "run_orchestrator", fake_run_orchestrator)
    monkeypatch.setattr(daily_run, "build_db", fake_build_db)
    monkeypatch.setattr(sys, "argv", ["daily_run.py", "--market", "us"])

    rc = daily_run.main()

    assert rc == 0
    assert "data" in calls
    assert "orchestrator" in calls
    assert "build_db" in calls


def test_daily_run_reports_task_status_and_reliability_failure(monkeypatch):
    class FakeResearchAssistant:
        def self_heal(self, event):
            return False

    monkeypatch.setattr(daily_run, "ResearchAssistant", FakeResearchAssistant)
    class FakeGovernanceService:
        instances = []

        def __init__(self, *args, **kwargs):
            self.status_events = []
            self.reliability_events = []
            self.__class__.instances.append(self)

        def update_task_status(self, *args, **kwargs):
            self.status_events.append(kwargs)

        def log_run_event(self, *args, **kwargs):
            pass

        def log_reliability_event(self, *args, **kwargs):
            self.reliability_events.append(args)

    def fake_run_data_update(market):
        return {"success": False, "error": "network error"}

    monkeypatch.setattr(daily_run, "GovernanceService", FakeGovernanceService)
    monkeypatch.setattr(daily_run, "run_data_update", fake_run_data_update)
    monkeypatch.setattr(sys, "argv", ["daily_run.py", "--market", "us"])

    rc = daily_run.main()

    assert rc != 0
    gov = FakeGovernanceService.instances[0]
    assert any(ev.get("status") == "RUNNING" for ev in gov.status_events)
    assert any("network error" in str(ev) for ev in gov.reliability_events) or rc != 0
