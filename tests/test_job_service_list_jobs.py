import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_job_service_list_jobs_sorts_and_filters(tmp_path: Path):
    try:
        from src.assistant.job_service import JobService
    except ModuleNotFoundError:
        pytest.fail("JobService module not implemented yet")

    svc = JobService(db_path=tmp_path / "metadata.db", project_root=tmp_path)
    svc.create_job(
        {
            "id": "job1",
            "type": "backtest",
            "status": "queued",
            "created_at": 1.0,
            "log_path": str(tmp_path / "job1.log"),
            "commands": [["python", "-c", "print('1')"]],
        }
    )
    svc.create_job(
        {
            "id": "job2",
            "type": "data_update",
            "status": "failed",
            "created_at": 2.0,
            "log_path": str(tmp_path / "job2.log"),
            "commands": [["python", "-c", "print('2')"]],
        }
    )

    try:
        jobs = svc.list_jobs(limit=10)
    except AttributeError:
        pytest.fail("JobService.list_jobs is not implemented yet")

    assert [j["id"] for j in jobs] == ["job2", "job1"]

    failed = svc.list_jobs(limit=10, status="failed")
    assert [j["id"] for j in failed] == ["job2"]

