import numpy as np
import pandas as pd
import pytest

from src.research.walkforward.pipeline import _simulate_portfolio, SimulationBlockError


def example():
    dates = ["2026-11-11", "2026-11-12", "2026-11-13"]
    prices = pd.DataFrame({"A": [10.0, 11.0, 12.0], "B": [10.0, 10.0, 9.0]}, index=dates)
    scores = pd.DataFrame({"A": [2.0, 0.0, 2.0], "B": [1.0, 1.0, 1.0]}, index=dates)
    return dates, prices, scores


def test_first_paper_fill_records_pending_cost_without_invented_return():
    dates, prices, scores = example()
    state = {}
    result = _simulate_portfolio(
        scores, prices, prices["B"], dates[:1], 1, 0.0008, liquidate_at_end=False, end_state=state
    )
    assert result == ([], [], [], [])
    assert state["target_weight"].tolist() == [1.0, 0.0]
    assert state["turnover"] == 1 and state["pending_fee_return"] == 0.0008


def test_end_state_does_not_change_old_returns_and_matches_next_prefix_fill():
    dates, prices, scores = example()
    state = {}
    snapshots = []
    old = _simulate_portfolio(
        scores, prices, prices["B"], dates[:2], 1, 0.0008, liquidate_at_end=False
    )
    new = _simulate_portfolio(
        scores, prices, prices["B"], dates[:2], 1, 0.0008, liquidate_at_end=False, end_state=state
    )
    assert old == new
    assert state["target_weight"].tolist() == [0.0, 1.0]
    _simulate_portfolio(
        scores, prices, prices["B"], dates, 1, 0.0008, liquidate_at_end=False, ledger=snapshots
    )
    np.testing.assert_array_equal(state["target_weight"], snapshots[-1]["target_and_held_weight"])
    assert state["turnover"] == snapshots[-1]["turnover"]


def test_terminal_state_cannot_implicitly_enable_liquidating_mode():
    dates, prices, scores = example()
    with pytest.raises(SimulationBlockError, match="non-liquidating"):
        _simulate_portfolio(scores, prices, prices["B"], dates, 1, 0.0008, end_state={})
