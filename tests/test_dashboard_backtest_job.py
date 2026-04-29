import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_create_backtest_job_validates_market_and_builds_commands(tmp_path: Path):
    from src.dashboard.backtest_job import create_backtest_job

    job = create_backtest_job(
        market="us",
        model_type="lgbm",
        project_root=tmp_path,
        python_exe="python",
        profile_path="configs/strategy_profile.json",
    )
    assert job["market"] == "us"
    assert job["status"] == "queued"
    assert job["commands"][0][:6] == ["python", "-m", "src.orchestrator", "run", "--market", "us"]


def test_create_backtest_job_rejects_unknown_market(tmp_path: Path):
    from src.dashboard.backtest_job import create_backtest_job

    try:
        create_backtest_job(
            market="hk",
            model_type="lgbm",
            project_root=tmp_path,
            python_exe="python",
            profile_path="configs/strategy_profile.json",
        )
    except ValueError as e:
        assert "market" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


def test_create_backtest_job_rebacktest_requires_model_path(tmp_path: Path):
    from src.dashboard.backtest_job import create_backtest_job

    try:
        create_backtest_job(
            market="us",
            model_type="lgbm",
            mode="rebacktest",
            project_root=tmp_path,
            python_exe="python",
            profile_path="configs/strategy_profile.json",
        )
    except ValueError as e:
        assert "model_path" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")
