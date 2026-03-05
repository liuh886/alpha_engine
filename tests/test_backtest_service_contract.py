from src.assistant.services.backtest_service import BacktestService


def test_backtest_service_explicit_contract():
    service = BacktestService(
        project_root=".",
        python_exe="python",
        dashboard_db_path="artifacts/dashboard/dashboard_db.json"
    )
    
    payload = {
        "market": "us",
        "mode": "train",
        "strategy_template": "TopK_10_2W",
        "cost_params": {"commission": 0.0005},
        "tag": "BT_TEST"
    }
    
    job = service.create_job_from_payload(payload)
    assert job["strategy_template"] == "TopK_10_2W"
    assert job["cost_params"] == {"commission": 0.0005}
    assert job["tag"] == "BT_TEST"
