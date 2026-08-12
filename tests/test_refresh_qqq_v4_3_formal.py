from __future__ import annotations

import pandas as pd
import pytest

from scripts.refresh_qqq_v4_3_formal import (
    QqqV43RefreshError,
    _rebase_appended_report,
    _verify_historical_prefix,
)
from src.artifacts.qqq_v4_3_formal import _report


def _package(weight_sgov: float = 0.5) -> dict[str, object]:
    return {
        "report": [
            {
                "date": "2026-08-05",
                "account": 1.2,
                "bench_qqq": 1.1,
                "bench": 0.01,
                "drawdown": 0.0,
                "period_return": 0.01,
                "gross_return": 0.011,
                "transaction_cost": 0.001,
                "weight_QQQI": 0.5,
                "weight_QQQ": 0.0,
                "weight_TQQQ": 0.0,
                "weight_SGOV": weight_sgov,
                "position_state": 0,
            }
        ]
    }


def test_refresh_prefix_accepts_exact_v43_history() -> None:
    _verify_historical_prefix(_package(), _package())


def test_refresh_prefix_accepts_provider_restatement_when_decision_path_is_same() -> None:
    candidate = _package()
    candidate["report"][0]["period_return"] = 0.0100002
    candidate["report"][0]["account"] = 1.2000002

    _verify_historical_prefix(_package(), candidate)


def test_refresh_prefix_rejects_changed_sgov_history() -> None:
    with pytest.raises(QqqV43RefreshError, match="weight_SGOV"):
        _verify_historical_prefix(_package(), _package(weight_sgov=0.4))


def test_appended_report_rebases_from_frozen_account_not_restated_history() -> None:
    current = _package()
    replay = _package()
    replay["report"][0]["account"] = 1.1999998
    replay["report"][0]["bench_qqq"] = 1.0999998
    replay["report"].append(
        {
            **replay["report"][0],
            "date": "2026-08-06",
            "account": 1.211999798,
            "bench_qqq": 1.110999798,
            "bench": 0.01,
            "period_return": 0.01,
            "gross_return": 0.01,
            "transaction_cost": 0.0,
        }
    )

    appended = _rebase_appended_report(current, replay)

    assert len(appended) == 1
    assert appended[0]["account"] == pytest.approx(1.2 * 1.01)
    assert appended[0]["bench_qqq"] == pytest.approx(1.1 * 1.01)
    assert "bench_tqqq" not in appended[0]
    assert appended[0]["drawdown"] == pytest.approx(0.0)


def test_formal_report_keeps_only_declared_qqq_benchmark() -> None:
    daily = pd.DataFrame(
        {
            "net_return": [0.01, -0.02],
            "QQQ_next_open_return": [0.01, 0.02],
            "TQQQ_next_open_return": [0.03, -0.02],
            "turnover_units": [1.0, 0.0],
            "gross_return": [0.011, -0.02],
            "transaction_cost": [0.001, 0.0],
            "position_state": [0, 0],
            "weight_QQQI": [1.0, 1.0],
            "weight_QQQ": [0.0, 0.0],
            "weight_TQQQ": [0.0, 0.0],
            "weight_SGOV": [0.0, 0.0],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )

    report = _report(daily)

    assert report[0]["bench_qqq"] == pytest.approx(1.01)
    assert "bench_tqqq" not in report[0]
    assert "bench_tqqq" not in report[1]
