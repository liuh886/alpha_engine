from __future__ import annotations

import pandas as pd
import pytest

from src.research.v4_2_sgov_defense_experiment import run_state_weight_backtest


def _contract() -> dict:
    return {
        "portfolio": {
            "transaction_cost_bps_per_turnover_unit": 10.0,
            "annual_risk_free_rate": 0.0,
            "charge_initial_entry": True,
            "current_v4_2": {
                "state_0": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0},
                "state_1": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0},
                "state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75, "SGOV": 0.0},
            },
            "sgov_pure_defense": {
                "state_0": {"QQQI": 0.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 1.0},
                "state_1": {"QQQI": 0.0, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.5},
                "state_2": {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75, "SGOV": 0.0},
            },
        }
    }


def _reference() -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=4, freq="B")
    return pd.DataFrame(
        {
            "position_state": [0, 1, 2, 0],
            "position_label": ["defensive", "attack", "leveraged_attack", "defensive"],
            "executed_reason": ["initial", "enter", "leverage", "exit"],
            "QQQI_next_open_return": [-0.02, 0.01, 0.01, -0.01],
            "QQQ_next_open_return": [-0.01, 0.02, 0.02, -0.02],
            "TQQQ_next_open_return": [-0.03, 0.04, 0.06, -0.05],
            "SGOV_next_open_return": [0.0001, 0.0001, 0.0001, 0.0001],
        },
        index=index,
    )


def test_sgov_variant_uses_sgov_in_states_zero_and_one() -> None:
    result = run_state_weight_backtest(_reference(), _contract(), "sgov_pure_defense")
    assert result.daily.iloc[0]["weight_SGOV"] == pytest.approx(1.0)
    assert result.daily.iloc[1]["weight_SGOV"] == pytest.approx(0.5)
    assert result.daily.iloc[2]["weight_TQQQ"] == pytest.approx(0.75)
    assert result.daily.iloc[2]["weight_SGOV"] == pytest.approx(0.0)


def test_transaction_cost_stays_at_ten_basis_points_per_turnover_unit() -> None:
    result = run_state_weight_backtest(_reference(), _contract(), "current_v4_2")
    first = result.daily.iloc[0]
    assert first["turnover_units"] == pytest.approx(1.0)
    assert first["transaction_cost"] == pytest.approx(0.001)


def test_unknown_variant_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown portfolio variant"):
        run_state_weight_backtest(_reference(), _contract(), "unknown")
