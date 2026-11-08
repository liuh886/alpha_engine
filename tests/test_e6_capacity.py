import pandas as pd
import pytest

from src.research.e6_capacity import capacity_screen


def test_capacity_ignores_fill_day_and_future_volume_and_includes_terminal_sale():
    days = pd.bdate_range("2026-01-01", periods=6).strftime("%Y-%m-%d").tolist()
    prices = pd.DataFrame({"A": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]}, index=days)
    pairs = pd.DataFrame({"date": days, "symbol": "A", "close_volume_proxy": [100.0] * 6})
    daily = pd.DataFrame(
        [{"date": days[4], "nav_before": 1.0, "gross": 0.0, "terminal_fill_session": days[4]}]
    )
    assets = pd.DataFrame(
        [
            {
                "date": days[4],
                "symbol": "A",
                "fill_session": days[3],
                "trade_weight": 1.0,
                "drifted_weight": 1.0,
            }
        ]
    )
    events, result = capacity_screen(daily, assets, pairs, prices, window=2, participation=0.01)
    assert events["max_initial_capital_usd_proxy"].tolist() == [1.0, 1.0]
    assert result["forced_exit_proxy_events"] == 1
    pairs.loc[pairs["date"] >= days[3], "close_volume_proxy"] = 1e15
    later, _ = capacity_screen(daily, assets, pairs, prices, window=2, participation=0.01)
    # Entry at day3 may use only history through day2. Exit can use day3.
    assert (
        later.iloc[0]["max_initial_capital_usd_proxy"]
        == events.iloc[0]["max_initial_capital_usd_proxy"]
    )
    assert (
        later.iloc[1]["max_initial_capital_usd_proxy"]
        > events.iloc[1]["max_initial_capital_usd_proxy"]
    )
    assert (events["information_through"] < events["fill_session"]).all()
    assert result["actual_capacity_gate"].startswith("BLOCKED")


def test_capacity_rejects_missing_prior_information():
    days = ["2026-01-02", "2026-01-05"]
    prices = pd.DataFrame({"A": [1.0, 1.0]}, index=days)
    pairs = pd.DataFrame({"date": days, "symbol": "A", "close_volume_proxy": [100.0, 100.0]})
    daily = pd.DataFrame(
        [{"date": days[1], "nav_before": 1.0, "gross": 0.0, "terminal_fill_session": None}]
    )
    assets = pd.DataFrame(
        [
            {
                "date": days[1],
                "symbol": "A",
                "fill_session": days[0],
                "trade_weight": 1.0,
                "drifted_weight": 1.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="prior capacity history"):
        capacity_screen(daily, assets, pairs, prices)
