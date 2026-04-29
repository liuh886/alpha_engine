import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_backtest_service_creates_rebacktest_job(tmp_path: Path):
    try:
        from src.assistant.services.backtest_service import BacktestService
    except ModuleNotFoundError:
        pytest.fail("BacktestService is not implemented yet")

    svc = BacktestService(
        project_root=tmp_path, python_exe="python", dashboard_db_path=tmp_path / "db.json"
    )
    job = svc.create_job_from_payload(
        {
            "market": "us",
            "model_type": "lgbm",
            "mode": "rebacktest",
            "model_path": "models/us_model.pkl",
            "start": "2025-01-01",
            "end": "latest",
            "profile_path": "configs/strategy_profile.json",
        }
    )
    assert job["type"] == "backtest"
    assert job["mode"] == "rebacktest"
    assert job["market"] == "us"
    assert job["commands"][0][:3] == ["python", "-m", "src.orchestrator"]
