from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE,
    FULL_INCREMENT_MOMENTUM,
    MAX_FINANCED_INCREMENT,
    build_decisions,
    momentum_scale,
)


def synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2024-01-02", periods=80, freq="B")
    common = pd.DataFrame(
        {
            "market_state": "bull",
            "vol_state": "low",
            "drawdown_252": -0.02,
            "mom_20": np.linspace(0.0, 0.20, len(index)),
            "mom_60": 0.10,
            "byd_open_return": 0.001,
            "etf_open_return": 0.0002,
            "common_open_eligible": True,
        },
        index=index,
    )
    signals = pd.DataFrame({"base_byd_weight": 1.0}, index=index)
    return common, signals


def test_scale_is_bounded_monotonic_and_convex() -> None:
    momentum = pd.Series([-0.05, 0.0, 0.075, 0.15, 0.30])
    scale = momentum_scale(momentum)

    assert scale.iloc[0] == 0.0
    assert scale.iloc[1] == 0.0
    assert np.isclose(scale.iloc[2], 0.5**4)
    assert scale.iloc[3] == 1.0
    assert scale.iloc[4] == 1.0
    assert scale.is_monotonic_increasing


def test_candidate_preserves_original_state_and_exposure_cap() -> None:
    common, signals = synthetic_inputs()
    decisions, diagnostics = build_decisions(common, signals)
    candidate = decisions[CANDIDATE]

    assert np.allclose(candidate.sum(axis=1), 1.0)
    assert candidate["byd_weight"].max() <= 1.0 + MAX_FINANCED_INCREMENT
    assert candidate["etf_weight"].min() >= 0.0
    assert candidate["cash_weight"].min() >= -MAX_FINANCED_INCREMENT
    assert diagnostics["financed_increment"].between(
        0.0, MAX_FINANCED_INCREMENT
    ).all()
    full_scale = common["mom_20"].ge(FULL_INCREMENT_MOMENTUM)
    assert diagnostics.loc[full_scale, "financed_increment"].eq(
        MAX_FINANCED_INCREMENT
    ).all()


def test_defense_state_has_no_financing() -> None:
    common, signals = synthetic_inputs()
    signals["base_byd_weight"] = 0.75
    decisions, diagnostics = build_decisions(common, signals)

    assert not diagnostics["trend_expansion_active"].any()
    candidate = decisions[CANDIDATE]
    assert candidate["byd_weight"].eq(0.75).all()
    assert candidate["etf_weight"].eq(0.25).all()
    assert candidate["cash_weight"].eq(0.0).all()


def test_invalid_scale_parameters_fail_closed() -> None:
    momentum = pd.Series([0.1])
    for full_momentum, power in ((0.0, 4.0), (0.15, 0.0), (-0.1, 4.0)):
        try:
            momentum_scale(
                momentum,
                full_increment_momentum=full_momentum,
                convex_power=power,
            )
        except ValueError:
            continue
        raise AssertionError("invalid convex-momentum parameter was accepted")
