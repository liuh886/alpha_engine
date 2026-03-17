from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import daily_run  # noqa: E402


def test_daily_run_fails_fast_when_inference_output_contains_failure(monkeypatch, capsys):
    calls: list[list[str]] = []

    def fake_run_step(args, cwd, capture=False):
        calls.append(list(args))
        if args[:3] == [sys.executable, "-m", "src.inference"]:
            return "Loaded 334 instruments\n  [!] Inference failed: feature mismatch\nNo results generated.\n"
        return ""

    monkeypatch.setattr(daily_run, "run_step", fake_run_step)
    monkeypatch.setattr(sys, "argv", ["daily_run.py"])

    rc = daily_run.main()

    assert rc == 2
    assert calls[0][:2] == [sys.executable, "scripts/update_data.py"]
    assert calls[1][:3] == [sys.executable, "-m", "src.inference"]
    assert len(calls) == 2  # dashboard refresh must not run after failed inference
    captured = capsys.readouterr()
    assert "Inference step failed" in captured.err


def test_daily_run_continues_when_inference_output_is_success(monkeypatch):
    calls: list[list[str]] = []

    def fake_run_step(args, cwd, capture=False):
        calls.append(list(args))
        if args[:3] == [sys.executable, "-m", "src.inference"]:
            return "Report saved to reports/watchlist_report.md\n"
        return ""

    monkeypatch.setattr(daily_run, "run_step", fake_run_step)
    monkeypatch.setattr(sys, "argv", ["daily_run.py"])

    rc = daily_run.main()

    assert rc == 0
    assert calls[0][:2] == [sys.executable, "scripts/update_data.py"]
    assert calls[1][:3] == [sys.executable, "-m", "src.inference"]
    assert calls[2][:2] == [sys.executable, "scripts/build_dashboard_db.py"]


def test_daily_run_reports_task_status_and_reliability_failure(monkeypatch):
    class FakeGovernanceService:
        instances: list["FakeGovernanceService"] = []

        def __init__(self, *_args, **_kwargs):
            self.run_events: list[tuple] = []
            self.status_events: list[tuple] = []
            self.reliability_events: list[tuple] = []
            self.__class__.instances.append(self)

        def log_run_event(self, *args, **kwargs):
            self.run_events.append((args, kwargs))

        def update_task_status(self, *args, **kwargs):
            self.status_events.append((args, kwargs))

        def log_reliability_event(self, *args, **kwargs):
            self.reliability_events.append((args, kwargs))

    def fake_run_step(args, cwd, capture=False):
        if args[:3] == [sys.executable, "-m", "src.inference"]:
            return "Loaded 334 instruments\n[!] Inference failed: feature mismatch\nNo results generated.\n"
        return ""

    monkeypatch.setattr(daily_run, "GovernanceService", FakeGovernanceService)
    monkeypatch.setattr(daily_run, "run_step", fake_run_step)
    monkeypatch.setattr(sys, "argv", ["daily_run.py", "--market", "us"])

    rc = daily_run.main()

    assert rc == 2
    gov = FakeGovernanceService.instances[0]
    assert gov.status_events[0][0][0] == "daily_run.us"
    assert gov.status_events[0][1]["status"] == "RUNNING"
    assert gov.reliability_events
    assert gov.status_events[-1][1]["status"] == "FAILED"
    assert gov.status_events[-1][1]["last_outcome"] == "FAILURE"
