"""Canonical-engine ledger parity and independently checkable accounting."""
import numpy as np
import pandas as pd
import pytest

from src.research.portfolio_ledger import replay_ledger, summarize_ledger
from src.research.walkforward.pipeline import _simulate_portfolio


def example():
    days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    prices = pd.DataFrame({"A": [10., 12., 9., 10.], "B": [20., 20., 22., 21.]}, index=days)
    scores = pd.DataFrame({"A": [2., 0., 2., 0.], "B": [1., 1., 1., 1.]}, index=days)
    return days, prices, scores, prices["B"]


def test_recording_does_not_change_engine_or_tie_selection():
    days, prices, scores, bench = example()
    scores.iloc[1] = 1.0  # preserve the engine's original tied-score policy
    expected = _simulate_portfolio(scores, prices, bench, days, 1, .0008)
    daily, assets = replay_ledger(scores=scores, prices=prices, qqq=bench, sessions=days, top_k=1)
    for col, values in zip(("gross", "net", "turnover", "qqq"), expected):
        np.testing.assert_array_equal(daily[col], values)
    np.testing.assert_allclose(assets.groupby("date")["net_contribution"].sum(), daily["net"], atol=1e-15)
    assert assets["actual_fill_observed"].eq(False).all()


def test_hand_computed_trades_drift_liquidation_and_pnl():
    days, prices, scores, bench = example()
    daily, assets = replay_ledger(scores=scores, prices=prices, qqq=bench, sessions=days, top_k=1)
    # Enter A at 10, sell it at 12 to buy B at 20, then sell B to buy A.
    a0 = assets.query("symbol == 'A'").iloc[0]
    assert a0["fill_quantity_per_unit_gross_nav"] == .1
    assert a0["gross_contribution"] == pytest.approx(.2)
    assert daily["turnover"].tolist() == [1., 1., 2.]
    assert daily["net"].tolist() == pytest.approx([.2-.0008, .1-.0008, 1/9-.0016])
    assert daily["cash_weight_before_fill"].iloc[0] == 1
    assert daily["cash_weight_after_terminal"].iloc[-1] == 1
    result = summarize_ledger(daily, assets)
    assert sum(result["asset_pnl_nav_units"].values()) == pytest.approx(result["net_return"],abs=1e-14)


def test_drift_record_is_not_target_weight():
    days, prices, scores, bench = example()
    daily, assets = replay_ledger(scores=scores, prices=prices, qqq=bench, sessions=days, top_k=2)
    first = assets.query("date == '2026-01-05'")
    assert first["simulated_held_weight"].tolist() == [.5,.5]
    assert first["drifted_weight"].tolist() == pytest.approx([.6/1.1,.5/1.1])
    assert daily["turnover"].iloc[1] == pytest.approx(abs(.5-.6/1.1))


def test_latency_metadata_cannot_claim_same_close_as_delayed():
    days, prices, scores, bench = example()
    with pytest.raises(ValueError, match="signal is not available"):
        replay_ledger(scores=scores, prices=prices, qqq=bench, sessions=days,
                      top_k=1, mode="delayed_close_1session")
