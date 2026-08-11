from __future__ import annotations

import pandas as pd
import pytest

from scripts.refresh_qqq_v4_3_formal import QqqV43RefreshError, _verify_historical_prefix
from src.artifacts.qqq_v4_3_formal import _report


def _package(weight_sgov: float = 0.5) -> dict[str, object]:
    return {
        "report": [
            {
                "date": "2026-08-05",
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


def test_refresh_prefix_rejects_changed_sgov_history() -> None:
    with pytest.raises(QqqV43RefreshError, match="weight_SGOV"):
        _verify_historical_prefix(_package(), _package(weight_sgov=0.4))


def test_formal_report_retains_tqqq_baseline_from_existing_daily_returns() -> None:
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
    assert report[0]["bench_tqqq"] == pytest.approx(1.03)
    assert report[1]["bench_tqqq"] == pytest.approx(1.03 * 0.98)
