import sys
import tempfile
from pathlib import Path

import pytest

from src.assistant.job_service import JobService


@pytest.fixture
def service():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        db_path = root / "metadata.db"
        yield JobService(db_path=db_path, project_root=root)

def test_job_failure_captures_output(service):
    # Create a job that definitely fails
    job_id = "fail_job"
    # Use a command that exits with 1
    cmd = [sys.executable, "-c", "import sys; print('hello world'); sys.exit(1)"]
    
    log_path = service.project_root / "fail.log"
    
    service.create_job({
        "id": job_id,
        "type": "test",
        "commands": [cmd],
        "log_path": str(log_path)
    })
    
    service.run_job(job_id)
    
    job = service.get_job(job_id)
    assert job["status"] == "failed"
    assert job["exit_code"] == 1
    assert "hello world" in job["error"]
    assert "Command failed" in job["error"]
    
    # Check log file exists and contains output
    assert log_path.exists()
    assert "hello world" in log_path.read_text()

def test_job_exception_captures_traceback(service):
    job_id = "exc_job"
    # Invalid command to trigger exception in run_job logic (e.g. non-existent file)
    cmd = ["/non/existent/path/to/nothing"]
    
    service.create_job({
        "id": job_id,
        "type": "test",
        "commands": [cmd]
    })
    
    # This might throw FileNotFoundError which is caught by the try-except in run_job
    service.run_job(job_id)
    
    job = service.get_job(job_id)
    assert job["status"] == "failed"
    assert "Exception" in job["error"]
    assert "Traceback" in job["error"]
