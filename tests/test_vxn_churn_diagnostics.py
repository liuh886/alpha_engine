from __future__ import annotations

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vxn_churn_diagnostics import (
    reentry_cycles,
    round_trip_summary,
    state_dwell_table,
)


def _result() -> StrategyResult:
    index = pd.date_range("2024-01-01", periods=10, freq="B")
    daily = pd.DataFrame(
        {
            "position_state": [0, 1, 1, 0, 0, 1, 0, 1, 1, 1],
            "net_return": [
                0.0,
                0.01,
                -0.01,
                0.0,
                0.0,
                0.02,
                0.0,
                0.01,
                0.01,
                0.01,
            ],
        },
        index=index,
    )
    return StrategyResult(
        "test",
        daily,
        pd.DataFrame(),
        {
            "strategy": "test",
            "switch_count": 5,
            "turnover_units": 7.5,
        },
    )


def test_state_dwell_and_round_trip_counts() -> None:
    dwell = state_dwell_table(_result())
    leverage = dwell[dwell["state"].eq(1)]
    assert leverage["sessions"].tolist() == [2, 1, 3]
    summary = round_trip_summary(dwell, [1, 2, 5])
    counts = summary.set_index("threshold_sessions")["episode_count"].to_dict()
    assert counts == {1: 1, 2: 2, 5: 3}


def test_reentry_cycles_measure_session_gap() -> None:
    result = _result()
    dwell = state_dwell_table(result)
    cycles = reentry_cycles(dwell, result.daily.index)
    assert cycles["gap_sessions"].tolist() == [3, 2]
    assert cycles["same_calendar_month"].all()
