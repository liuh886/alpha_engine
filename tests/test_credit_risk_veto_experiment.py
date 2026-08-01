from __future__ import annotations

import pandas as pd

from src.research.credit_risk_veto_experiment import (
    build_credit_proxy_features,
    generate_credit_risk_veto_states,
)
from src.research.vix_rotation_experiment import VixRotationConfig


def test_credit_proxy_uses_adjusted_ratio_below_own_ma() -> None:
    index = pd.date_range("2020-01-01", periods=12, freq="B")
    hyg = pd.DataFrame(
        {"date": index, "close": [100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 97]}
    )
    shy = pd.DataFrame({"date": index, "close": [100.0] * 12})
    features, quality = build_credit_proxy_features(
        hyg,
        shy,
        index,
        moving_average_sessions=3,
        minimum_common_sessions=6,
        minimum_coverage_ratio_within_common_span=1.0,
        maximum_absolute_daily_ratio_return=0.20,
    )
    assert quality["quality_passed"]
    assert quality["coverage_ratio_within_common_span"] == 1.0
    assert features["credit_risk_stress"].iloc[-1]


def test_credit_proxy_fails_closed_on_sparse_coverage() -> None:
    index = pd.date_range("2020-01-01", periods=12, freq="B")
    sparse = index.delete([3, 4, 5])
    hyg = pd.DataFrame({"date": sparse, "close": [100.0] * len(sparse)})
    shy = pd.DataFrame({"date": sparse, "close": [100.0] * len(sparse)})
    try:
        build_credit_proxy_features(
            hyg,
            shy,
            index,
            moving_average_sessions=3,
            minimum_common_sessions=6,
            minimum_coverage_ratio_within_common_span=0.90,
            maximum_absolute_daily_ratio_return=0.20,
        )
    except ValueError as error:
        assert "coverage ratio" in str(error)
    else:
        raise AssertionError("sparse credit proxy coverage must fail closed")


def _prepared() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=6, freq="B")
    return pd.DataFrame(
        {
            "long_break": [False] * 6,
            "vix_stress": [False] * 6,
            "stress_price_failure": [False] * 6,
            "shock_memory": [True] * 6,
            "early_repair": [True] * 6,
            "vix_easing": [True] * 6,
            "medium_repair": [True] * 6,
            "secondary_confirmation": [True] * 6,
            "vix_normalized": [True] * 6,
            "vxn_stress": [False] * 6,
            "below_ma_short_n": [False] * 6,
            "credit_risk_stress": [False, True, False, True, False, False],
        },
        index=index,
    )


def test_credit_stress_vetoes_entry_and_exits_existing_leverage() -> None:
    states = generate_credit_risk_veto_states(
        _prepared(), VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].tolist() == [1, 1, 2, 1, 2, 2]
    assert states["decision_reason"].iloc[3] == "exit_partial_tqqq_credit_risk_stress"


def test_vxn_exit_remains_immediate() -> None:
    prepared = _prepared().copy()
    prepared.loc[prepared.index[3], "credit_risk_stress"] = False
    prepared.loc[prepared.index[3], "vxn_stress"] = True
    states = generate_credit_risk_veto_states(
        prepared, VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].iloc[3] == 1
    assert states["decision_reason"].iloc[3] == "exit_partial_tqqq_vxn_stress"
