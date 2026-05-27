from __future__ import annotations

import pytest

from src.assistant.job_coordinator import JobCoordinator


class FakeJobService:
    def __init__(self):
        self.created_jobs = []
        self.run_ids = []

    def create_job(self, job: dict) -> None:
        self.created_jobs.append(job)

    def run_job(self, job_id: str) -> None:
        self.run_ids.append(job_id)


class ImmediateThread:
    created = []

    def __init__(self, *, target, args, daemon, name):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.name = name
        self.started = False
        ImmediateThread.created.append(self)

    def start(self):
        self.started = True
        self.target(*self.args)


def test_job_coordinator_persists_then_starts_job(monkeypatch):
    monkeypatch.setattr("src.assistant.job_coordinator.threading.Thread", ImmediateThread)
    ImmediateThread.created.clear()

    service = FakeJobService()
    coordinator = JobCoordinator(service)
    job = {
        "id": "job-123456789",
        "type": "backtest",
        "status": "queued",
        "commands": [["python", "-c", "print('ok')"]],
    }

    response = coordinator.submit_response(job)

    assert response == {"ok": True, "job_id": "job-123456789"}
    assert service.created_jobs == [job]
    assert service.run_ids == ["job-123456789"]
    assert ImmediateThread.created[0].daemon is True
    assert ImmediateThread.created[0].name == "alpha-backtest-job-1234"


def test_job_coordinator_rejects_invalid_job():
    coordinator = JobCoordinator(FakeJobService())

    with pytest.raises(ValueError, match="job.id is required"):
        coordinator.submit({"commands": [["python"]]})

    with pytest.raises(ValueError, match="job.commands is required"):
        coordinator.submit({"id": "job-1", "commands": []})
