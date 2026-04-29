import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_apply_profile_does_not_overwrite_segments_when_train_window_missing():
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {"strategy": {"strategy_mode": "weekly_quant_rating", "universe_size": 30}}
    base = {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {"kwargs": {}},
                    "segments": {"train": ["2021-01-01", "2024-12-31"]},
                }
            }
        },
        "port_analysis_config": {"strategy": {"kwargs": {}}},
    }
    cfg = apply_profile_to_config(profile, base, "us")
    assert cfg["task"]["dataset"]["kwargs"]["segments"]["train"] == ["2021-01-01", "2024-12-31"]
