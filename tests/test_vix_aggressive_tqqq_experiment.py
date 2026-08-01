from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from src.research.vix_aggressive_tqqq_experiment import (
    _relabel_result,
    validate_weight_only_change,
)
from src.research.vix_rotation_experiment import (
    VixRotationConfig,
    generate_vix_decision_states,
)
from src.research.vix_rotation_runtime import _run_weighted_state_backtest


def _contract(weight: float) -> dict:
    return {
        "boundaries": {"signal_time": "session_close_t"},
        "data": {"provider": "test"},
        "price_logic": {"ma_short": 20},
        "vix_logic": {"rolling_window": 252},
        "portfolio": {
            "leveraged_tqqq_weight": weight,
            "transaction_cost_bps_per_turnover_unit": 10.0,
        },
        "validation": {"require_all_states_reached": True},
        "change_control": {
            "allowed_change": "portfolio.leveraged_tqqq_weight",
            "all_signal_rules_frozen": True,
        },
    }


def _prepared() -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=5)
    defaults: dict[str, object] = {
        "shock_memory": False,
        "early_repair": False,
        "medium_repair": False,
        "secondary_confirmation": False,
        "long_break": False,
        "stress_price_failure": False,
        "below_ma_short_n": False,
        "vix_stress": False,
        "vix_easing": False,
        "vix_normalized": False,
        "vix_close": 18.0,
        "vix_regime": "normal",
        "QQQI_next_open_return": 0.0,
        "QQQ_next_open_return": 0.01,
        "TQQQ_next_open_return": 0.03,
    }
    rows = [
        {**defaults, "shock_memory": True, "early_repair": True, "vix_easing": True},
        {
            **defaults,
            "shock_memory": True,
            "medium_repair": True,
            "secondary_confirmation": True,
            "vix_normalized": True,
        },
        defaults,
        defaults,
        defaults,
    ]
    return pd.DataFrame(rows, index=index)


def test_contract_accepts_only_higher_tqqq_weight() -> None:
    baseline = _contract(0.50)
    challenger = _contract(0.75)
    assert validate_weight_only_change(baseline, challenger) == (0.50, 0.75)


def test_contract_rejects_signal_rule_change() -> None:
    baseline = _contract(0.50)
    challenger = deepcopy(_contract(0.75))
    challenger["vix_logic"]["rolling_window"] = 126
    with pytest.raises(ValueError, match="vix_logic"):
        validate_weight_only_change(baseline, challenger)


def test_higher_weight_preserves_states_and_increases_recovery_capture() -> None:
    prepared = _prepared()
    baseline_config = VixRotationConfig(
        leveraged_tqqq_weight=0.50,
        transaction_cost_bps_per_turnover_unit=10.0,
    )
    challenger_config = VixRotationConfig(
        leveraged_tqqq_weight=0.75,
        transaction_cost_bps_per_turnover_unit=10.0,
    )
    decisions = generate_vix_decision_states(prepared, baseline_config)
    baseline = _run_weighted_state_backtest(
        prepared,
        baseline_config,
        decisions,
        strategy_key="baseline",
        display_name="baseline",
    )
    challenger = _run_weighted_state_backtest(
        prepared,
        challenger_config,
        decisions,
        strategy_key="challenger",
        display_name="challenger",
    )
    pd.testing.assert_series_equal(
        baseline.daily["position_state"], challenger.daily["position_state"]
    )
    leveraged = challenger.daily["position_state"].eq(2)
    assert leveraged.any()
    assert np.isclose(challenger.daily.loc[leveraged, "weight_TQQQ"].iloc[0], 0.75)
    assert challenger.daily.loc[leveraged, "net_return"].sum() > baseline.daily.loc[
        leveraged, "net_return"
    ].sum()


def test_relabel_result_changes_identity_without_mutating_evidence() -> None:
    prepared = _prepared()
    config = VixRotationConfig(leveraged_tqqq_weight=0.75)
    decisions = generate_vix_decision_states(prepared, config)
    original = _run_weighted_state_backtest(
        prepared,
        config,
        decisions,
        strategy_key="rotation_vix_v2",
        display_name="original",
    )
    relabelled = _relabel_result(
        original,
        strategy="rotation_vix_v3_75",
        display_name="VIX v3",
    )
    assert original.metrics["strategy"] == "rotation_vix_v2"
    assert relabelled.metrics["strategy"] == "rotation_vix_v3_75"
    assert relabelled.daily is original.daily
    assert relabelled.trades is original.trades
