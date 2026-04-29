import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_create_data_update_job_builds_commands(tmp_path: Path):
    from src.dashboard.data_update_job import create_data_update_job

    job = create_data_update_job(
        project_root=tmp_path,
        python_exe="python",
    )
    assert job["type"] == "data_update"
    assert job["status"] == "queued"
    assert job["commands"][0][:2] == ["python", "scripts/update_data.py"]
