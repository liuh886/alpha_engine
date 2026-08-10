from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    build_decisions as build_v12_decisions,
)
from src.research.byd_v1_3_candidate import (
    BEAR_DEFENSE_BYD,
    MAX_FINANCED_INCREMENT,
    MIN_HOLD_SESSIONS,
    _minimum_hold_targets,
    build_v13_decision,
)


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-02", periods=80, freq="B")
    common = pd.DataFrame(
        {
            "market_state": ["bear"] * 30 + ["bull"] * 50,
            "vol_state": ["low"] * 80,
            "mom_20": [0.05] * 80,
            "mom_60": [0.08] * 80,
            "drawdown_252": [-0.05] * 80,
        },
        index=index,
    )
    base = pd.Series(
        [0.75] * 5 + [1.0] * 10 + [0.75] * 10 + [1.0] * 55,
        index=index,
        dtype=float,
    )
    signals = pd.DataFrame({"base_byd_weight": base}, index=index)
    return common, signals


def test_minimum_hold_delays_fast_reversal() -> None:
    index = pd.date_range("2024-01-02", periods=8, freq="B")
    desired = pd.Series(
        [0.75, 1.0, 1.0, 0.75, 0.75, 0.75, 0.75, 0.75],
        index=index,
    )
    held = _minimum_hold_targets(desired, min_hold_sessions=4)

    assert held.iloc[0] == 0.75
    assert held.iloc[1] == 1.0
    assert held.iloc[2] == 1.0
    assert held.iloc[3] == 1.0
    assert held.iloc[4] == 1.0
    assert held.iloc[5] == 0.75


def test_v13_reuses_exact_v12_decision() -> None:
    common, signals = _fixture()
    expected, _ = build_v12_decisions(common, signals)
    baseline, _, _ = build_v13_decision(common, signals)

    pd.testing.assert_frame_equal(baseline, expected[V12_MODEL_ID])


def test_v13_bear_defense_and_weight_contract() -> None:
    common, signals = _fixture()
    _, candidate, diagnostics = build_v13_decision(common, signals)

    bear_rows = diagnostics["bear_defense_active"]
    assert bear_rows.any()
    assert np.allclose(
        candidate.loc[bear_rows, "byd_weight"], BEAR_DEFENSE_BYD, atol=1e-12
    )
    assert np.allclose(candidate.sum(axis=1), 1.0, atol=1e-12)
    assert candidate["byd_weight"].max() <= 1.0 + MAX_FINANCED_INCREMENT + 1e-12
    assert candidate["byd_weight"].min() >= 0.0
    assert candidate["etf_weight"].min() >= 0.0


def test_frozen_min_hold_is_twenty_sessions() -> None:
    assert MIN_HOLD_SESSIONS == 20
