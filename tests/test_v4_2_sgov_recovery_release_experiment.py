from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_2_sgov_recovery_release_experiment import (
    recovery_release_weights,
    run_recovery_release_backtest,
)


def _contract() -> dict:
    return {
        "boundaries": {"transaction_cost_bps_per_turnover_unit": 10.0},
        "frozen_allocations": {
            "state_0_blended": {
                "QQQI": 0.50,
                "QQQ": 0.00,
                "TQQQ": 0.00,
                "SGOV": 0.50,
            },
            "state_1_blended": {
                "QQQI": 0.25,
                "QQQ": 0.50,
                "TQQQ": 0.00,
                "SGOV": 0.25,
            },
            "state_1_qqqi_release": {
                "QQQI": 0.50,
                "QQQ": 0.50,
                "TQQQ": 0.00,
                "SGOV": 0.00,
            },
            "state_1_tqqq_precursor": {
                "QQQI": 0.25,
                "QQQ": 0.50,
                "TQQQ": 0.25,
                "SGOV": 0.00,
            },
            "state_2_frozen": {
                "QQQI": 0.00,
                "QQQ": 0.25,
                "TQQQ": 0.75,
                "SGOV": 0.00,
            },
        },
        "variants": {
            "static_blended": {
                "release_sgov_to_qqqi_on_state_1": False,
                "use_tqqq_precursor": False,
            },
            "qqqi_release_on_state_1": {
                "release_sgov_to_qqqi_on_state_1": True,
                "use_tqqq_precursor": False,
            },
            "tqqq_release_on_precursor": {
                "release_sgov_to_qqqi_on_state_1": False,
                "use_tqqq_precursor": True,
            },
            "staged_qqqi_then_tqqq_release": {
                "release_sgov_to_qqqi_on_state_1": True,
                "use_tqqq_precursor": True,
            },
        },
        "precursor": {"maximum_tqqq_weight_before_state_2": 0.25},
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


def test_qqqi_release_removes_sgov_immediately_in_executed_state_one() -> None:
    weights, precursor = recovery_release_weights(
        _reference(), _contract(), "qqqi_release_on_state_1"
    )
    assert weights.iloc[1]["QQQI"] == pytest.approx(0.50)
    assert weights.iloc[1]["QQQ"] == pytest.approx(0.50)
    assert weights.iloc[1]["SGOV"] == pytest.approx(0.0)
    assert not precursor.any()


def test_precursor_uses_prior_close_and_is_capped_at_twenty_five_percent() -> None:
    weights, precursor = recovery_release_weights(
        _reference(), _contract(), "tqqq_release_on_precursor"
    )
    assert not precursor.iloc[2]
    assert precursor.iloc[3]
    assert weights.iloc[3]["TQQQ"] == pytest.approx(0.25)
    assert weights.iloc[3]["SGOV"] == pytest.approx(0.0)
    assert weights.loc[_reference()["position_state"].ne(2), "TQQQ"].max() == pytest.approx(
        0.25
    )


def test_state_two_always_keeps_frozen_seventy_five_percent_tqqq() -> None:
    weights, _ = recovery_release_weights(
        _reference(), _contract(), "staged_qqqi_then_tqqq_release"
    )
    state_two = weights.loc[_reference()["position_state"].eq(2)].iloc[0]
    assert state_two["QQQ"] == pytest.approx(0.25)
    assert state_two["TQQQ"] == pytest.approx(0.75)
    assert state_two["QQQI"] == pytest.approx(0.0)
    assert state_two["SGOV"] == pytest.approx(0.0)


def test_backtest_charges_frozen_ten_basis_points_per_turnover_unit() -> None:
    result = run_recovery_release_backtest(
        _reference(), _contract(), "qqqi_release_on_state_1"
    )
    first = result.daily.iloc[0]
    assert first["turnover_units"] == pytest.approx(1.0)
    assert first["transaction_cost"] == pytest.approx(0.001)


def test_unknown_variant_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown release variant"):
        recovery_release_weights(_reference(), _contract(), "unknown")
