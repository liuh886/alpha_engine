from __future__ import annotations

import pandas as pd

from src.research.vix_rotation_experiment import VixRotationConfig
from src.research.vxn_exit_persistence_experiment import (
    generate_vxn_exit_persistence_states,
)


def _prepared() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=7, freq="B")
    return pd.DataFrame(
        {
            "long_break": [False] * 7,
            "vix_stress": [False] * 7,
            "stress_price_failure": [False] * 7,
            "shock_memory": [True] * 7,
            "early_repair": [True] * 7,
            "vix_easing": [True] * 7,
            "medium_repair": [True] * 7,
            "secondary_confirmation": [True] * 7,
            "vix_normalized": [True] * 7,
            "vxn_stress": [False, False, False, True, False, True, True],
            "below_ma_short_n": [False] * 7,
        },
        index=index,
    )


def test_single_vxn_stress_close_does_not_exit_existing_leverage() -> None:
    states = generate_vxn_exit_persistence_states(
        _prepared(), VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].tolist()[:6] == [1, 2, 2, 2, 2, 2]
    assert states["decision_state"].iloc[6] == 1
    assert states["decision_reason"].iloc[6] == (
        "exit_partial_tqqq_vxn_stress_two_closes"
    )


def test_vxn_stress_still_vetoes_new_leverage_entry_immediately() -> None:
    prepared = _prepared().copy()
    prepared.loc[prepared.index[1], "vxn_stress"] = True
    states = generate_vxn_exit_persistence_states(
        prepared, VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].iloc[0] == 1
    assert states["decision_state"].iloc[1] == 1


def test_vix_stress_exits_existing_leverage_without_waiting() -> None:
    prepared = _prepared().copy()
    prepared.loc[prepared.index[3], "vxn_stress"] = False
    prepared.loc[prepared.index[3], "vix_stress"] = True
    states = generate_vxn_exit_persistence_states(
        prepared, VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].iloc[3] == 1
    assert states["decision_reason"].iloc[3] == "exit_partial_tqqq_vix_or_ma20"


def test_other_persistence_lengths_are_rejected() -> None:
    try:
        generate_vxn_exit_persistence_states(
            _prepared(),
            VixRotationConfig(leveraged_tqqq_weight=0.75),
            persistence_closes=3,
        )
    except ValueError as error:
        assert "exactly two closes" in str(error)
    else:
        raise AssertionError("non-frozen persistence length must fail")
