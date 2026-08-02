from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_2_sgov_precursor_50_experiment import (
    precursor_50_weights,
    run_precursor_50_backtest,
)


def _contract() -> dict:
    return {
        "boundaries": {"transaction_cost_bps_per_turnover_unit": 10.0},
        "allocation": {
            "state_0_blended": {
                "QQQI": 0.50,
                "QQQ": 0.00,
                "TQQQ": 0.00,
                "SGOV": 0.50,
            },
            "ordinary_state_1": {
                "QQQI": 0.25,
                "QQQ": 0.50,
                "TQQQ": 0.00,
                "SGOV": 0.25,
            },
            "precursor_50": {
                "QQQI": 0.00,
                "QQQ": 0.50,
                "TQQQ": 0.50,
                "SGOV": 0.00,
            },
            "formal_state_2": {
                "QQQI": 0.00,
                "QQQ": 0.25,
                "TQQQ": 0.75,
                "SGOV": 0.00,
            },
        },
        "precursor": {"maximum_tqqq_weight_before_state_2": 0.50},
    }


def _reference() -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=6, freq="B")
    return pd.DataFrame(
        {
            "position_state": [0, 1, 1, 1, 2, 1],
            "position_label": [
                "defensive",
                "attack",
                "attack",
                "attack",
                "leveraged_attack",
                "attack",
            ],
            "executed_reason": ["initial", "enter", "hold", "hold", "leverage", "exit"],
            "shock_memory": [True, True, True, True, True, True],
            "medium_repair": [False, False, True, True, True, True],
            "vix_normalized": [False, False, True, True, True, True],
            "vxn_stress": [False, False, False, False, False, False],
            "QQQI_next_open_return": [0.00, 0.01, 0.01, 0.01, 0.01, 0.01],
            "QQQ_next_open_return": [0.00, 0.02, 0.02, 0.02, 0.02, 0.02],
            "TQQQ_next_open_return": [0.00, 0.04, 0.04, 0.04, 0.04, 0.04],
            "SGOV_next_open_return": [0.00, 0.0001, 0.0001, 0.0001, 0.0001, 0.0001],
        },
        index=index,
    )


def test_precursor_50_uses_prior_close_without_lookahead() -> None:
    weights, precursor = precursor_50_weights(_reference(), _contract())
    assert not precursor.iloc[2]
    assert precursor.iloc[3]
    assert precursor.iloc[5]
    assert weights.iloc[3]["QQQ"] == pytest.approx(0.50)
    assert weights.iloc[3]["TQQQ"] == pytest.approx(0.50)
    assert weights.iloc[3]["QQQI"] == pytest.approx(0.0)
    assert weights.iloc[3]["SGOV"] == pytest.approx(0.0)


def test_pre_state_two_tqqq_is_capped_at_fifty_percent() -> None:
    weights, _ = precursor_50_weights(_reference(), _contract())
    mask = _reference()["position_state"].ne(2)
    assert weights.loc[mask, "TQQQ"].max() == pytest.approx(0.50)


def test_formal_state_two_remains_seventy_five_percent_tqqq() -> None:
    weights, _ = precursor_50_weights(_reference(), _contract())
    state_two = weights.loc[_reference()["position_state"].eq(2)].iloc[0]
    assert state_two["QQQ"] == pytest.approx(0.25)
    assert state_two["TQQQ"] == pytest.approx(0.75)
    assert state_two["QQQI"] == pytest.approx(0.0)
    assert state_two["SGOV"] == pytest.approx(0.0)


def test_backtest_charges_ten_basis_points_per_turnover_unit() -> None:
    result = run_precursor_50_backtest(_reference(), _contract())
    first = result.daily.iloc[0]
    assert first["turnover_units"] == pytest.approx(1.0)
    assert first["transaction_cost"] == pytest.approx(0.001)
    assert result.metrics["precursor_sessions"] == 2


def test_invalid_precursor_weight_is_rejected() -> None:
    contract = _contract()
    contract["allocation"]["precursor_50"]["TQQQ"] = 0.60
    with pytest.raises(ValueError, match="weights must sum to one"):
        precursor_50_weights(_reference(), contract)
