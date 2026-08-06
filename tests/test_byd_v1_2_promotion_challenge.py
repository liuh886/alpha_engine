from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_v1_2_promotion_challenge import (
    EPISODE_BUDGET,
    MAX_INCREMENT,
    ORIGINAL,
    RELATIVE_STRENGTH,
    VOLATILITY_BUDGET,
    build_candidate_decisions,
)


def synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-02", periods=120, freq="B")
    common = pd.DataFrame(
        {
            "market_state": "bull",
            "vol_state": "low",
            "drawdown_252": -0.02,
            "mom_20": 0.05,
            "mom_60": 0.10,
            "byd_open_return": 0.002,
            "etf_open_return": 0.0002,
            "common_open_eligible": True,
        },
        index=index,
    )
    signals = pd.DataFrame({"base_byd_weight": 1.0}, index=index)
    return common, signals


def test_structural_candidates_preserve_frozen_state_and_exposure_cap() -> None:
    common, signals = synthetic_inputs()
    decisions, diagnostics = build_candidate_decisions(common, signals)

    for decision in decisions.values():
        assert np.allclose(decision.sum(axis=1), 1.0)
        assert decision["byd_weight"].max() <= 1.0 + MAX_INCREMENT + 1e-12
        assert decision["etf_weight"].min() >= 0.0

    assert decisions[ORIGINAL]["byd_weight"].eq(1.125).all()
    assert decisions[EPISODE_BUDGET]["byd_weight"].iloc[:20].eq(1.125).all()
    assert decisions[EPISODE_BUDGET]["byd_weight"].iloc[20:].eq(1.0).all()
    assert decisions[VOLATILITY_BUDGET]["byd_weight"].between(1.0, 1.125).all()
    assert diagnostics["trend_expansion_active"].all()


def test_relative_strength_candidate_waits_for_fixed_lookback() -> None:
    common, signals = synthetic_inputs()
    decisions, _ = build_candidate_decisions(common, signals)
    weights = decisions[RELATIVE_STRENGTH]["byd_weight"]

    assert weights.iloc[:59].eq(1.0).all()
    assert weights.iloc[59:].eq(1.125).all()


def test_defense_state_never_uses_financing() -> None:
    common, signals = synthetic_inputs()
    signals["base_byd_weight"] = 0.75
    decisions, diagnostics = build_candidate_decisions(common, signals)

    assert not diagnostics["trend_expansion_active"].any()
    for decision in decisions.values():
        assert decision["byd_weight"].eq(0.75).all()
        assert decision["etf_weight"].eq(0.25).all()
        assert decision["cash_weight"].eq(0.0).all()
