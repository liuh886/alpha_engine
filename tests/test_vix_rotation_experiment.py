from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.vix_rotation_experiment import (
    VixRotationConfig,
    build_vix_features,
    generate_vix_decision_states,
    vix_regime_asset_metrics,
)
from src.research.vix_rotation_runtime import (
    _run_weighted_state_backtest,
    generate_price_repair_decision_states,
    state_reachability,
)


def _prepared(rows: list[dict[str, object]]) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=len(rows))
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
        "QQQ_next_open_return": 0.0,
        "TQQQ_next_open_return": 0.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows], index=index)


def _run_vix(prepared: pd.DataFrame, config: VixRotationConfig | None = None):
    effective_config = config or VixRotationConfig()
    decisions = generate_vix_decision_states(prepared, effective_config)
    return _run_weighted_state_backtest(
        prepared,
        effective_config,
        decisions,
        strategy_key="rotation_vix_v2",
        display_name="Rotation VIX v2",
    )


def test_vix_features_use_only_current_and_past_rows() -> None:
    index = pd.bdate_range("2020-01-02", periods=320)
    values = np.linspace(12.0, 25.0, len(index))
    bars = pd.DataFrame({"date": index, "close": values})
    config = VixRotationConfig()
    original = build_vix_features(bars, config)
    changed = bars.copy()
    changed.loc[changed.index[-5:], "close"] = [80.0, 70.0, 60.0, 50.0, 40.0]
    revised = build_vix_features(changed, config)
    pd.testing.assert_frame_equal(original.iloc[:-5], revised.iloc[:-5])


def test_vix_easing_allows_qqq_only_after_shock_memory_and_price_repair() -> None:
    prepared = _prepared(
        [
            {},
            {"shock_memory": True, "early_repair": True, "vix_easing": False},
            {"shock_memory": True, "early_repair": True, "vix_easing": True},
        ]
    )
    decisions = generate_vix_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [0, 0, 1]


def test_vix_stress_blocks_partial_tqqq_and_forces_defense_on_price_failure() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True, "vix_easing": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": False,
                "vix_stress": True,
            },
            {"vix_stress": True, "stress_price_failure": True},
        ]
    )
    decisions = generate_vix_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 1, 0]


def test_ma50_and_vix_normalization_enable_partial_tqqq_state() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True, "vix_easing": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
            },
            {},
        ]
    )
    decisions = generate_vix_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 2, 2]


def test_positions_execute_one_session_after_close_decision() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True, "vix_easing": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
            },
            {},
            {},
        ]
    )
    result = _run_vix(prepared)
    assert result.daily["position_state"].tolist() == [0, 1, 2, 2]


def test_partial_leverage_uses_fixed_half_tqqq_weight_and_turnover_cost() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True, "vix_easing": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
            },
            {},
            {},
        ]
    )
    config = VixRotationConfig(
        leveraged_tqqq_weight=0.50,
        transaction_cost_bps_per_turnover_unit=10.0,
    )
    result = _run_vix(prepared, config)
    leveraged = result.daily.loc[result.daily["position_state"].eq(2)].iloc[0]
    assert np.isclose(leveraged["weight_QQQ"], 0.50)
    assert np.isclose(leveraged["weight_TQQQ"], 0.50)
    assert np.isclose(leveraged["turnover_units"], 1.0)
    assert np.isclose(leveraged["transaction_cost"], 0.001)


def test_vix_spike_exits_partial_tqqq_to_qqq_before_full_defense() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True, "vix_easing": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
            },
            {"vix_stress": True, "stress_price_failure": False},
        ]
    )
    decisions = generate_vix_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 2, 1]


def test_vix_regime_metrics_begin_after_close_confirmation() -> None:
    prepared = _prepared(
        [
            {
                "vix_regime": "stress",
                "QQQI_next_open_return": 0.90,
                "QQQ_next_open_return": 0.80,
            },
            {
                "vix_regime": "normal",
                "QQQI_next_open_return": 0.01,
                "QQQ_next_open_return": 0.03,
            },
            {
                "vix_regime": "normal",
                "QQQI_next_open_return": 0.02,
                "QQQ_next_open_return": 0.04,
            },
        ]
    )
    table = vix_regime_asset_metrics(prepared)
    stress = table.loc["stress"]
    assert stress.loc["QQQI", "sessions"] == 1
    assert np.isclose(stress.loc["QQQI", "cumulative_return"], 0.01)
    assert np.isclose(stress.loc["QQQ", "cumulative_return"], 0.03)


def test_price_repair_ablation_uses_same_price_gates_without_vix() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
            },
            {"below_ma_short_n": True},
        ]
    )
    decisions = generate_price_repair_decision_states(prepared)
    assert decisions["decision_state"].tolist() == [1, 2, 1]


def test_runtime_trade_reason_is_lagged_with_executed_position() -> None:
    prepared = _prepared(
        [
            {"shock_memory": True, "early_repair": True},
            {
                "shock_memory": True,
                "medium_repair": True,
                "secondary_confirmation": True,
            },
            {},
            {},
        ]
    )
    decisions = generate_price_repair_decision_states(prepared)
    result = _run_weighted_state_backtest(
        prepared,
        VixRotationConfig(),
        decisions,
        strategy_key="test",
        display_name="test",
    )
    assert result.daily["position_state"].tolist() == [0, 1, 2, 2]
    assert result.trades.loc[1, "executed_reason"] == "enter_qqq_early_price_repair"
    assert result.trades.loc[2, "executed_reason"] == "enter_partial_tqqq_ma50_confirmation"
    assert state_reachability(result)["all_states_reached"]
