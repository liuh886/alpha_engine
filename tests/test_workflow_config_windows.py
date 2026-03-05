from src.common.workflow_config import apply_backtest_and_test_window


def test_apply_backtest_and_test_window_extends_end_to_latest_calendar():
    cfg = {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {"kwargs": {"start_time": "2021-01-01", "end_time": "2025-12-31"}},
                    "segments": {"test": ["2025-01-01", "2025-12-31"]},
                }
            }
        },
        "port_analysis_config": {"backtest": {"start_time": "2025-01-01", "end_time": "2025-12-31"}},
    }
    calendar = ["2025-01-02", "2026-02-04"]

    out = apply_backtest_and_test_window(cfg, calendar, default_start="2025-01-01")

    assert out["port_analysis_config"]["backtest"]["end_time"] == "2026-02-04"
    assert out["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["end_time"] == "2026-02-04"
    assert out["task"]["dataset"]["kwargs"]["segments"]["test"][1] == "2026-02-04"
    assert out["task"]["dataset"]["kwargs"]["segments"]["test"][0] == "2025-01-01"


def test_apply_backtest_and_test_window_allows_start_override():
    cfg = {
        "task": {"dataset": {"kwargs": {"handler": {"kwargs": {}}, "segments": {"test": ["2025-01-01", "2025-12-31"]}}}},
        "port_analysis_config": {"backtest": {"start_time": "2025-01-01", "end_time": "2025-12-31"}},
    }
    calendar = ["2026-02-04"]

    out = apply_backtest_and_test_window(cfg, calendar, default_start="2025-01-01", start_time="2025-06-01")

    assert out["port_analysis_config"]["backtest"]["start_time"] == "2025-06-01"
    assert out["task"]["dataset"]["kwargs"]["segments"]["test"][0] == "2025-06-01"

