from __future__ import annotations

import pandas as pd
import pytest

from scripts.refresh_allocation_formal import (
    AllocationRefreshError,
    _increment_qqq_attribution,
    _qqq_metrics_from_report,
    _verify_qqq_decision_overlap,
)


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "position_state": [1, 1],
            "decision_state": [1, 2],
            "position_label": ["attack", "attack"],
            "decision_reason": ["hold", "enter_leverage"],
            "executed_reason": ["enter_attack", "hold"],
            "weight_QQQI": [0.5, 0.5],
            "weight_QQQ": [0.5, 0.5],
            "weight_TQQQ": [0.0, 0.0],
            "QQQI_next_open_return": [0.01, 0.02],
            "QQQ_next_open_return": [0.02, 0.01],
            "TQQQ_next_open_return": [0.03, 0.02],
            "transaction_cost": [0.0, 0.001],
        },
        index=pd.to_datetime(["2026-07-30", "2026-07-31"]),
    )


def test_overlap_ignores_revised_economic_return_but_locks_decision_path() -> None:
    existing = {
        "2026-07-30": {
            "period_return": -0.99,
            "gross_return": -0.99,
            "transaction_cost": 0.25,
            "position_state": 1,
            "decision_state": 1,
            "position_label": "attack",
            "decision_reason": "hold",
            "executed_reason": "enter_attack",
            "weight_QQQI": 0.5,
            "weight_QQQ": 0.5,
            "weight_TQQQ": 0.0,
        }
    }
    _verify_qqq_decision_overlap(existing, _daily())


def test_overlap_fails_closed_when_frozen_decision_path_changes() -> None:
    existing = {
        "2026-07-30": {
            "position_state": 0,
            "decision_state": 1,
            "weight_QQQI": 1.0,
            "weight_QQQ": 0.0,
            "weight_TQQQ": 0.0,
        }
    }
    with pytest.raises(AllocationRefreshError, match="decision path changed"):
        _verify_qqq_decision_overlap(existing, _daily())


def test_overlap_requires_all_frozen_decision_dates_to_be_replayed() -> None:
    existing = {
        "2026-07-29": {"position_state": 1, "decision_state": 1},
    }
    with pytest.raises(AllocationRefreshError, match="missing 1 frozen decision dates"):
        _verify_qqq_decision_overlap(existing, _daily())


def test_metrics_are_recomputed_from_frozen_plus_appended_report() -> None:
    report = [
        {
            "date": "2026-07-29",
            "period_return": 0.01,
            "turnover": 0.0,
            "transaction_cost": 0.0,
        },
        {
            "date": "2026-07-30",
            "period_return": -0.005,
            "turnover": 1.0,
            "transaction_cost": 0.001,
        },
        {
            "date": "2026-07-31",
            "period_return": 0.02,
            "turnover": 0.0,
            "transaction_cost": 0.0,
        },
    ]
    metrics = _qqq_metrics_from_report(report, annual_risk_free_rate=0.0)
    assert metrics["Total Return"] == pytest.approx(
        (1.01 * 0.995 * 1.02) - 1.0
    )
    assert metrics["Turnover"] == pytest.approx(1.0)
    assert metrics["Transaction Cost"] == pytest.approx(0.001)


def test_attribution_extends_only_new_sessions_from_frozen_values() -> None:
    existing = [
        {"instrument": "QQQI", "value": 0.10},
        {"instrument": "QQQ", "value": 0.20},
        {"instrument": "TQQQ", "value": 0.30},
    ]
    result = _increment_qqq_attribution(
        existing=existing,
        daily=_daily(),
        appended_dates={"2026-07-31"},
        previous_weights={"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
    )
    values = {row["instrument"]: row["value"] for row in result}
    assert values["QQQI"] == pytest.approx(0.11)
    assert values["QQQ"] == pytest.approx(0.205)
    assert values["TQQQ"] == pytest.approx(0.30)
