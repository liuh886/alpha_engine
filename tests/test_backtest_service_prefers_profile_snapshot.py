import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_backtest_service_prefers_mlruns_profile_snapshot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(tmp_path))
    from src.assistant.services.backtest_service import BacktestService

    run_id = "run_123"
    # Structure: artifacts/mlruns/<exp>/<run>/artifacts/...
    snap = tmp_path / "mlruns" / "0" / run_id / "artifacts" / "strategy_profile.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text('{"meta":{"name":"S1"}}', encoding="utf-8")

    svc = BacktestService(
        project_root=tmp_path, python_exe="python", dashboard_db_path=tmp_path / "db.json"
    )
    job = svc.create_job_from_payload(
        {
            "market": "us",
            "mode": "rebacktest",
            "run_id": run_id,
            "model_path": "models/us_model.pkl",
            "start": "2025-01-01",
            "end": "latest",
            "profile_path": "configs/strategy_profile.json",
        }
    )

    cmd = job["commands"][0]
    assert "--profile" in cmd
    prof = cmd[cmd.index("--profile") + 1]
    assert str(snap).replace("\\", "/") in str(prof).replace("\\", "/")
