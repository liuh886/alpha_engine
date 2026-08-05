from __future__ import annotations

import pandas as pd

from src.research.byd_515180_execution import execute_next_common_open
from src.research.byd_515180_trend_guard import (
    _weights,
    trend_positive,
)


def test_trend_warmup_retains_baseline_sleeve() -> None:
    index = pd.date_range("2020-01-01", periods=205, freq="B")
    close = pd.Series(range(1, 206), index=index, dtype=float)
    flag = trend_positive(close, 200)
    assert flag.iloc[:199].all()
    assert flag.iloc[199:].all()


def test_soft_and_hard_guards_only_change_released_sleeve() -> None:
    index = pd.date_range("2020-01-01", periods=3, freq="B")
    base = pd.Series([1.0, 0.75, 0.75], index=index)
    trend = pd.Series([False, True, False], index=index)

    soft = _weights(base, trend, below_trend_etf_weight=0.125)
    hard = _weights(base, trend, below_trend_etf_weight=0.0)

    assert soft["byd_weight"].tolist() == [1.0, 0.75, 0.75]
    assert soft["etf_weight"].tolist() == [0.0, 0.25, 0.125]
    assert soft["cash_weight"].tolist() == [0.0, 0.0, 0.125]
    assert hard["etf_weight"].tolist() == [0.0, 0.25, 0.0]
    assert hard["cash_weight"].tolist() == [0.0, 0.0, 0.25]


def test_close_signal_executes_only_at_next_eligible_open() -> None:
    index = pd.date_range("2020-01-01", periods=4, freq="B")
    decision = pd.DataFrame(
        {
            "byd_weight": [0.75, 0.75, 0.75, 0.75],
            "etf_weight": [0.25, 0.125, 0.125, 0.25],
            "cash_weight": [0.0, 0.125, 0.125, 0.0],
        },
        index=index,
    )
    eligible = pd.Series([True, True, False, True], index=index)
    executed = execute_next_common_open(decision, eligible)

    assert executed.iloc[0].to_dict() == {
        "position_byd_weight": 0.0,
        "position_etf_weight": 0.0,
        "position_cash_weight": 1.0,
    }
    assert executed.iloc[1]["position_etf_weight"] == 0.25
    assert executed.iloc[2]["position_etf_weight"] == 0.25
    assert executed.iloc[3]["position_etf_weight"] == 0.125
