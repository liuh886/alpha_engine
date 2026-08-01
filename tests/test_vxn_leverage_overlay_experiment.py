from __future__ import annotations

import pandas as pd

from src.research.vix_rotation_experiment import VixRotationConfig
from src.research.vxn_leverage_overlay_experiment import generate_vxn_leverage_veto_states


def _prepared(rows: list[dict[str, object]]) -> pd.DataFrame:
    defaults: dict[str, object] = {
        "long_break": False,
        "vix_stress": False,
        "vix_easing": False,
        "vix_normalized": False,
        "vxn_stress": False,
        "stress_price_failure": False,
        "shock_memory": True,
        "early_repair": False,
        "medium_repair": False,
        "secondary_confirmation": False,
        "below_ma_short_n": False,
    }
    index = pd.bdate_range("2024-01-02", periods=len(rows))
    return pd.DataFrame([{**defaults, **row} for row in rows], index=index)


def test_vxn_does_not_change_initial_qqq_repair() -> None:
    prepared = _prepared(
        [{"early_repair": True, "vix_easing": True, "vxn_stress": True}]
    )
    decisions = generate_vxn_leverage_veto_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1]


def test_vxn_stress_vetoes_leverage_but_not_qqq() -> None:
    prepared = _prepared(
        [
            {"early_repair": True, "vix_easing": True},
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
                "vxn_stress": True,
            },
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
                "vxn_stress": False,
            },
        ]
    )
    decisions = generate_vxn_leverage_veto_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 1, 2]


def test_vxn_stress_exits_only_to_qqq_without_price_failure() -> None:
    prepared = _prepared(
        [
            {"early_repair": True, "vix_easing": True},
            {
                "medium_repair": True,
                "secondary_confirmation": True,
                "vix_normalized": True,
            },
            {"vxn_stress": True},
        ]
    )
    decisions = generate_vxn_leverage_veto_states(prepared, VixRotationConfig())
    assert decisions["decision_state"].tolist() == [1, 2, 1]
    assert "vxn" in decisions["decision_reason"].iloc[-1]
