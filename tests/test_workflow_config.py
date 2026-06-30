from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from src.common.workflow_config import apply_label_horizon_purge
from src.research.service import ResearchService


def _config(label: str, segments: dict | None = None) -> dict:
    return {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {
                            "data_loader": {"kwargs": {"config": {"label": [label]}}}
                        }
                    },
                    "segments": segments
                    or {
                        "train": ["2025-01-02", "2025-01-10"],
                        "valid": ["2025-01-13", "2025-01-17"],
                        "test": ["2025-01-20", "2025-01-24"],
                    },
                }
            }
        },
        "port_analysis_config": {
            "backtest": {"start_time": "2025-01-20", "end_time": "2025-01-24"}
        },
    }


def test_purges_ten_session_label_on_observed_calendar_without_mutation():
    calendar = pd.bdate_range("2024-12-02", "2025-03-03")
    cfg = _config(
        "Ref($close, -2) / Ref($close, -1) - 1",
        {
            "train": ["2024-12-02", "2025-01-10"],
            "valid": ["2025-01-13", "2025-02-07"],
            "test": ["2025-02-10", "2025-03-03"],
        },
    )
    labels = cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"][
        "kwargs"
    ]["config"]["label"]
    labels.append("Ref($open, -10) / Ref($open, -1) - 1")
    original = deepcopy(cfg)

    result = apply_label_horizon_purge(cfg, calendar)
    segments = result["task"]["dataset"]["kwargs"]["segments"]

    assert segments == {
        "train": ["2024-12-02", "2024-12-27"],
        "valid": ["2025-01-13", "2025-01-24"],
        "test": ["2025-02-10", "2025-03-03"],
    }
    assert cfg == original
    assert result is not cfg


def test_purges_two_sessions_using_irregular_observed_calendar():
    calendar = pd.to_datetime(
        [
            "2025-01-02",
            "2025-01-03",
            "2025-01-06",
            "2025-01-07",
            "2025-01-10",
            "2025-01-13",
            "2025-01-14",
            "2025-01-17",
            "2025-01-20",
            "2025-01-21",
            "2025-01-24",
        ]
    )

    result = apply_label_horizon_purge(
        _config("Ref($close, -2) / Ref($close, -1) - 1"), calendar
    )

    assert result["task"]["dataset"]["kwargs"]["segments"] == {
        "train": ["2025-01-02", "2025-01-06"],
        "valid": ["2025-01-13", "2025-01-13"],
        "test": ["2025-01-20", "2025-01-24"],
    }


def test_feature_refs_do_not_affect_label_horizon_and_no_forward_label_needs_no_calendar():
    cfg = _config("$close / Ref($close, 10) - 1")
    loader_config = cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"][
        "kwargs"
    ]["config"]
    loader_config["feature"] = ["Ref($close, -99)"]

    result = apply_label_horizon_purge(cfg, None)

    assert result == cfg
    assert result is not cfg


@pytest.mark.parametrize("calendar", [None, [], pd.bdate_range("2025-01-09", periods=2)])
def test_forward_label_fails_closed_on_missing_or_insufficient_calendar(calendar):
    with pytest.raises(ValueError, match="calendar|Calendar"):
        apply_label_horizon_purge(_config("Ref($close, -10) / $close - 1"), calendar)


def test_prepare_experiment_purges_returned_config_and_preserves_input(monkeypatch):
    calendar = pd.bdate_range("2024-12-02", "2025-03-03")
    cfg = _config(
        "Ref($close, -2) / Ref($close, -1) - 1",
        {
            "train": ["2024-12-02", "2025-01-10"],
            "valid": ["2025-01-13", "2025-02-07"],
            "test": ["2025-02-10", "2025-03-03"],
        },
    )
    original = deepcopy(cfg)
    monkeypatch.setattr("src.research.service.D", SimpleNamespace(calendar=lambda: calendar))
    monkeypatch.setattr(
        "src.research.service.resolve_start_date", lambda start, cal: (start, None)
    )
    monkeypatch.setattr("src.research.service.clean_universe", lambda *args: ["AAPL"])

    result = ResearchService().prepare_experiment(
        "us", cfg, start_time="2025-02-10", end_time="2025-03-03"
    )
    kwargs = result["task"]["dataset"]["kwargs"]

    assert kwargs["segments"]["train"][1] == "2025-01-08"
    assert kwargs["segments"]["valid"][1] == "2025-02-05"
    assert kwargs["segments"]["test"] == ["2025-02-10", "2025-03-03"]
    assert kwargs["handler"]["kwargs"]["instruments"] == ["AAPL"]
    assert cfg == original
