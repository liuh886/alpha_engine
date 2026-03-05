import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_data_service_creates_update_job(tmp_path: Path):
    try:
        from src.assistant.services.data_service import DataService
    except ModuleNotFoundError:
        pytest.fail("DataService is not implemented yet")

    svc = DataService(project_root=tmp_path, python_exe="python")
    job = svc.create_update_job_from_payload({"full": False, "lookback_days": 7})
    assert job["type"] == "data_update"
    assert job["commands"][0][:2] == ["python", "scripts/update_data.py"]

