from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.downside_volatility_veto_experiment import (
    build_downside_volatility_features,
    generate_downside_volatility_veto_states,
)
from src.research.vix_rotation_experiment import VixRotationConfig


def test_downside_volatility_uses_only_negative_returns() -> None:
    index = pd.date_range("2020-01-01", periods=20, freq="B")
    close = pd.Series(
        [100.0, 101.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0, 105.0, 104.0,
         106.0, 105.0, 107.0, 106.0, 108.0, 107.0, 109.0, 108.0, 110.0, 109.0],
        index=index,
    )
    features = build_downside_volatility_features(
        close,
        lookback_sessions=3,
        threshold_window_sessions=6,
        threshold_quantile=0.80,
        minimum_threshold_history_sessions=3,
    )
    assert features["qqq_downside_volatility"].dropna().ge(0.0).all()
    positive_only = pd.Series(np.arange(1.0, 21.0), index=index)
    positive_features = build_downside_volatility_features(
        positive_only,
        lookback_sessions=3,
        threshold_window_sessions=6,
        threshold_quantile=0.80,
        minimum_threshold_history_sessions=3,
    )
    assert positive_features["qqq_downside_volatility"].dropna().eq(0.0).all()


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
            "qqq_downside_volatility_stress": [False, True, False, True, False, False],
        },
        index=index,
    )


def test_downside_stress_vetoes_entry_and_exits_existing_leverage() -> None:
    states = generate_downside_volatility_veto_states(
        _prepared(), VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].tolist() == [1, 1, 2, 1, 2, 2]
    assert states["decision_reason"].iloc[3] == (
        "exit_partial_tqqq_downside_volatility_stress"
    )


def test_vix_exit_remains_immediate() -> None:
    prepared = _prepared().copy()
    prepared.loc[prepared.index[3], "qqq_downside_volatility_stress"] = False
    prepared.loc[prepared.index[3], "vix_stress"] = True
    states = generate_downside_volatility_veto_states(
        prepared, VixRotationConfig(leveraged_tqqq_weight=0.75)
    )
    assert states["decision_state"].iloc[3] == 1
    assert states["decision_reason"].iloc[3] == "exit_partial_tqqq_vix_or_ma20"
