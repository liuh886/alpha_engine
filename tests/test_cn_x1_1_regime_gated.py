from __future__ import annotations

import pandas as pd

from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    regime_signal,
    run_regime_portfolio,
    yearly_state_coverage,
)


def _ledger(dates: pd.DatetimeIndex, window: str = "2023H1") -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    counter = 1
    for date in dates:
        for sector_index, sector in enumerate(("A", "B", "C", "D", "E")):
            for name_index in range(3):
                rows.append(
                    {
                        "window": window,
                        "datetime": date,
                        "instrument": f"{counter:06d}",
                        "entity": f"Name {counter}",
                        "sector": sector,
                        "score": 100.0 - sector_index * 10 - name_index,
                        "execution_forward_return": 0.02 - sector_index / 1000.0,
                    }
                )
                counter += 1
        counter = 1
    return pd.DataFrame(rows)


def test_regime_state_is_strictly_trailing() -> None:
    dates = pd.bdate_range("2022-01-03", periods=220)
    close = pd.DataFrame(
        {
            "000300": range(100, 320),
            "000001": range(50, 270),
            "000002": range(40, 260),
        },
        index=dates,
        dtype=float,
    )

    state = build_regime_state(
        close,
        symbols=["000001", "000002"],
        benchmark="000300",
    )

    assert not state.iloc[100]["long_trend"]
    assert state.iloc[-1]["long_trend"]
    assert state.iloc[-1]["medium_momentum"]
    assert state.iloc[-1]["cross_sectional_breadth"]
    assert state.iloc[-1]["votes"] == 3


def test_predeclared_rules_are_distinct() -> None:
    date = pd.Timestamp("2024-01-02")
    state = pd.DataFrame(
        {
            "long_trend": [True],
            "medium_momentum": [False],
            "cross_sectional_breadth": [True],
            "breadth_value": [0.6],
            "votes": [2],
        },
        index=[date],
    )

    assert regime_signal(state, date, "two_of_three")
    assert regime_signal(state, date, "trend_only")
    assert not regime_signal(state, date, "momentum_and_breadth")
    assert not regime_signal(state, date, "three_of_three")


def test_risk_off_falls_back_to_benchmark_and_charges_transition_cost() -> None:
    dates = pd.bdate_range("2023-01-03", periods=3)
    ledger = _ledger(dates)
    benchmark = pd.Series([0.01, 0.01, 0.01], index=dates)
    state = pd.DataFrame(
        {
            "long_trend": [True, False, True],
            "medium_momentum": [True, False, True],
            "cross_sectional_breadth": [True, False, True],
            "breadth_value": [0.8, 0.2, 0.8],
            "votes": [3, 0, 3],
        },
        index=dates,
    )

    summary, periods, holdings, windows = run_regime_portfolio(
        ledger,
        benchmark,
        state,
        windows=("2023H1",),
        variant=RegimeGateSpec().variant(),
        rebalance_sessions=1,
        cost_bps=20,
    )

    risk_off = periods.loc[~periods["risk_on"]].iloc[0]
    assert risk_off["gross_return"] == risk_off["benchmark_return"]
    assert risk_off["net_return"] < risk_off["benchmark_return"]
    assert set(holdings.loc[holdings["datetime"] == dates[1], "instrument"]) == {"000300"}
    assert summary["risk_on_share"] == 2 / 3
    assert windows.iloc[0]["window"] == "2023H1"


def test_yearly_state_coverage_reports_both_states() -> None:
    periods = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2023-01-03", "2023-02-03", "2024-01-03"]),
            "risk_on": [True, False, True],
        }
    )

    result = yearly_state_coverage(periods).set_index("year")

    assert result.loc[2023, "both_states_present"]
    assert not result.loc[2024, "both_states_present"]
