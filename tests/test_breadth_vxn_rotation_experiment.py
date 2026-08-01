from __future__ import annotations

import pandas as pd

from src.research.breadth_vxn_rotation_experiment import (
    build_breadth_features,
    generate_breadth_decision_states,
    generate_dual_volatility_decision_states,
    generate_vxn_only_decision_states,
)
from src.research.vix_rotation_experiment import VixRotationConfig


def _bars(values: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=len(values))
    return pd.DataFrame({"date": dates, "open": values, "close": values})


def _prepared(rows: list[dict[str, object]]) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=len(rows))
    defaults: dict[str, object] = {
        "long_break": False,
        "stress_price_failure": False,
        "shock_memory": True,
        "early_repair": False,
        "medium_repair": False,
        "secondary_confirmation": False,
        "below_ma_short_n": False,
        "vix_stress": False,
        "vix_easing": False,
        "vix_normalized": False,
        "vxn_stress": False,
        "vxn_easing": False,
        "vxn_normalized": False,
        "breadth_confirmed": False,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows], index=index)


def test_equal_weight_ratio_confirms_broadening_only_when_trend_and_momentum_agree() -> None:
    qqq = _bars([100, 101, 102, 103, 104, 105])
    qqqe = _bars([100, 102, 104, 106, 109, 112])
    features = build_breadth_features(
        qqqe,
        qqq,
        ratio_ma_window=3,
        momentum_sessions=2,
    )
    assert bool(features["breadth_confirmed"].iloc[-1])
    assert features["breadth_regime"].iloc[-1] == "broadening"


def test_breadth_gate_blocks_partial_leverage_until_confirmation() -> None:
    prepared = _prepared(
        [
            {"early_repair": True, "vix_easing": True},
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
                "breadth_confirmed": False,
            },
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
                "breadth_confirmed": True,
            },
        ]
    )
    decisions = generate_breadth_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 1, 2]


def test_vxn_only_can_replace_vix_without_using_vix_flags() -> None:
    prepared = _prepared(
        [
            {"early_repair": True, "vxn_easing": True},
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vxn_normalized": True,
            },
        ]
    )
    decisions = generate_vxn_only_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 2]
    assert "vxn" in decisions["decision_reason"].iloc[-1]


def test_dual_confirmation_requires_both_indices_and_either_can_exit() -> None:
    prepared = _prepared(
        [
            {"early_repair": True, "vix_easing": True, "vxn_easing": False},
            {"early_repair": True, "vix_easing": True, "vxn_easing": True},
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
                "vxn_normalized": True,
            },
            {"vxn_stress": True},
        ]
    )
    decisions = generate_dual_volatility_decision_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [0, 1, 2, 1]
