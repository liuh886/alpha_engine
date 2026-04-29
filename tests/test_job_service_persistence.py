import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_job_service_persists_and_updates_status(tmp_path: Path):
    try:
        from src.assistant.job_service import JobService
    except ModuleNotFoundError:
        pytest.fail("JobService module not implemented yet")

    db_path = tmp_path / "metadata.db"
    svc = JobService(db_path=db_path, project_root=tmp_path)

    job = {
        "id": "job1",
        "type": "backtest",
        "status": "queued",
        "created_at": 1.0,
        "log_path": str(tmp_path / "job1.log"),
        "commands": [["python", "-c", "print('hello')"]],
        "market": "us",
        "model_type": "lgbm",
        "mode": "rebacktest",
    }

    svc.create_job(job)
    loaded = svc.get_job("job1")
    assert loaded["id"] == "job1"
    assert loaded["status"] == "queued"
    assert loaded["type"] == "backtest"
    assert loaded["commands"] == job["commands"]

    svc.update_job("job1", status="running", started_at=2.0)
    loaded2 = svc.get_job("job1")
    assert loaded2["status"] == "running"
    assert loaded2["started_at"] == 2.0


def test_job_service_run_job_updates_status_and_writes_log(tmp_path: Path):
    try:
        from src.assistant.job_service import JobService
    except ModuleNotFoundError:
        pytest.fail("JobService module not implemented yet")

    db_path = tmp_path / "metadata.db"
    svc = JobService(db_path=db_path, project_root=tmp_path)

    log_path = tmp_path / "job2.log"
    job = {
        "id": "job2",
        "type": "backtest",
        "status": "queued",
        "created_at": 1.0,
        "log_path": str(log_path),
        "commands": [[sys.executable, "-c", "print('ok')"]],
    }
    svc.create_job(job)

    try:
        svc.run_job("job2")
    except AttributeError:
        pytest.fail("JobService.run_job is not implemented yet")

    loaded = svc.get_job("job2")
    assert loaded is not None
    assert loaded["status"] == "succeeded"
    assert loaded["exit_code"] == 0
    assert loaded["started_at"] is not None
    assert loaded["finished_at"] is not None

    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "ok" in text
