"""Deterministic ties and real zero-trade holding intervals in canonical engine."""

import numpy as np
import pandas as pd
import pytest

from src.research.execution_selection import make_selection, ranked_indices
from src.research.portfolio_ledger import replay_ledger
from src.research.walkforward.pipeline import SimulationBlockError, _simulate_portfolio


def arm(**kwargs):
    return {"tie": "symbol_asc", "weekly": False, "min_hold": 0, "exit_rank": 1, **kwargs}


@pytest.mark.parametrize("tie", ["symbol_asc", "symbol_desc", "symbol_sha256"])
def test_ties_ignore_input_column_order(tie):
    symbols = ["C", "A", "B"]
    scores = np.array([1.0, 2.0, 2.0])
    chosen = [symbols[i] for i in ranked_indices(scores, symbols, tie, "frozen")]
    reversed_symbols = symbols[::-1]
    assert chosen == [
        reversed_symbols[i] for i in ranked_indices(scores[::-1], reversed_symbols, tie, "frozen")
    ]
    assert chosen[-1] == "C"


def test_weekly_no_hidden_resizing_and_holiday_first_session():
    # Monday is an exchange holiday: Tuesday is the first session of the next week.
    days = ["2026-01-16", "2026-01-20", "2026-01-21", "2026-01-22"]
    prices = pd.DataFrame(
        {"A": [10.0, 12.0, 15.0, 16.0], "B": [10.0, 10.0, 10.0, 10.0]}, index=days
    )
    scores = pd.DataFrame(1.0, index=days, columns=prices.columns)
    selector = make_selection(
        arm(weekly=True, exit_rank=2),
        symbols=list(prices.columns),
        calendar=days,
        salt="f",
        top_k=2,
    )
    daily, assets = replay_ledger(
        scores=scores, prices=prices, qqq=prices["B"], sessions=days, top_k=2, selection=selector
    )
    # Tuesday scheduled resizing >0, Wednesday carries drift exactly, last day liquidates.
    assert daily["turnover"].iloc[1] > 0
    assert daily["turnover"].iloc[-1] == pytest.approx(1.0)
    wednesday = assets.query("fill_session == '2026-01-21'")
    assert wednesday["trade_weight"].eq(0).all()


def test_minimum_hold_and_rank_buffer_are_separate_constraints():
    days = pd.bdate_range("2026-01-05", periods=8).strftime("%Y-%m-%d").tolist()
    drift = np.array([1.0, 0.0])
    select = make_selection(arm(min_hold=5), symbols=["A", "B"], calendar=days, salt="f", top_k=1)
    assert select(0, days[0], np.array([2.0, 1.0]), np.zeros(2)).tolist() == [1.0, 0.0]
    for i in range(1, 5):
        assert select(i, days[i], np.array([0.0, 1.0]), drift).tolist() == [1.0, 0.0]
    assert select(5, days[5], np.array([0.0, 1.0]), drift).tolist() == [0.0, 1.0]
    buffer = make_selection(arm(exit_rank=2), symbols=["A", "B"], calendar=days, salt="f", top_k=1)
    buffer(0, days[0], np.array([2.0, 1.0]), np.zeros(2))
    assert buffer(1, days[1], np.array([0.0, 1.0]), drift).tolist() == [1.0, 0.0]


def test_engine_refuses_selection_with_leverage_or_wrong_portfolio_size():
    days = ["2026-01-05", "2026-01-06"]
    frame = pd.DataFrame({"A": [1.0, 2.0], "B": [1.0, 2.0]}, index=days)
    with pytest.raises(SimulationBlockError, match="selection violated"):
        _simulate_portfolio(
            frame, frame, frame["A"], days, 1, 0.0008, selection=lambda *args: np.array([2.0, 0.0])
        )
