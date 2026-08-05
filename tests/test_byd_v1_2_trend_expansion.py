from __future__ import annotations

import pandas as pd
import pytest

from src.research.byd_v1_2_trend_expansion import (
    BASELINE,
    PRIMARY,
    ROBUSTNESS,
    build_decisions,
    run_financed_allocation,
)


def _research_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2026-01-01", periods=7, freq="D")
    common = pd.DataFrame(
        {
            "market_state": [
                "sideways",
                "bull",
                "bull",
                "bull",
                "bull",
                "bull",
                "bear",
            ],
            "vol_state": ["low", "low", "low", "low", "high", "low", "low"],
            "drawdown_252": [-0.12, -0.05, -0.04, -0.03, -0.02, -0.02, -0.15],
            "mom_20": [-0.01, 0.02, 0.03, 0.01, 0.01, 0.02, -0.01],
            "mom_60": [0.01, 0.04, 0.05, 0.03, 0.03, 0.04, -0.02],
            "common_open_eligible": [True] * 7,
            "byd_open_return": [0.01, 0.02, -0.01, 0.03, 0.01, 0.02, 0.0],
            "etf_open_return": [0.0] * 7,
        },
        index=index,
    )
    signals = pd.DataFrame(
        {"base_byd_weight": [0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 0.75]},
        index=index,
    )
    return common, signals


def test_expansion_state_and_declared_leverage_are_frozen() -> None:
    common, signals = _research_frames()
    decisions, state = build_decisions(common, signals)
    index = common.index

    assert state["trend_expansion_active"].tolist() == [
        False,
        True,
        True,
        True,
        False,
        True,
        False,
    ]
    assert decisions[BASELINE].loc[index[2]].to_dict() == {
        "byd_weight": 1.0,
        "etf_weight": 0.0,
        "cash_weight": 0.0,
    }
    assert decisions[PRIMARY].loc[index[2], "byd_weight"] == pytest.approx(1.125)
    assert decisions[PRIMARY].loc[index[2], "etf_weight"] == pytest.approx(0.0)
    assert decisions[PRIMARY].loc[index[2], "cash_weight"] == pytest.approx(-0.125)
    assert decisions[ROBUSTNESS].loc[index[2], "byd_weight"] == pytest.approx(1.10)
    assert decisions[ROBUSTNESS].loc[index[2], "etf_weight"] == pytest.approx(0.0)
    assert decisions[ROBUSTNESS].loc[index[2], "cash_weight"] == pytest.approx(-0.10)
    for decision in decisions.values():
        assert (decision["byd_weight"] >= 0.0).all()
        assert (decision["etf_weight"] >= 0.0).all()
        assert decision.sum(axis=1).round(12).eq(1.0).all()


def test_financing_is_charged_only_after_leveraged_target_executes() -> None:
    common, signals = _research_frames()
    decisions, _ = build_decisions(common, signals)
    result = run_financed_allocation(
        PRIMARY,
        common,
        decisions[PRIMARY],
        cost_bps=20.0,
        annual_financing_rate=0.06,
    )
    daily = result.daily

    assert daily.iloc[0]["borrowed_weight"] == pytest.approx(0.0)
    assert daily.iloc[1]["borrowed_weight"] == pytest.approx(0.0)
    assert daily.iloc[2]["borrowed_weight"] == pytest.approx(0.125)
    assert daily.iloc[2]["financing_cost"] == pytest.approx(
        0.125 * 0.06 / 252.0
    )
    assert daily.loc[daily["borrowed_weight"].eq(0.0), "financing_cost"].eq(0.0).all()
    assert daily["net_return"].le(daily["gross_return"]).all()
