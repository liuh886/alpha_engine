from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.research.distribution_risk_diagnostics import (
    DISTRIBUTION_GROUP,
    DIRECT_SPEARMAN_MIN,
    MIN_POSITIVE_WINDOW_SHARE,
    MIN_STRONG_OUTCOMES,
    PARTIAL_SPEARMAN_MIN,
    _future_drawdown_severity,
    _partial_spearman,
    _tail_spread,
)


def test_phase4_library_contains_only_two_diagnostic_distribution_factors() -> None:
    library = load_factor_library(
        PROJECT_ROOT / "configs/factor_libraries/distribution_risk_research.yaml"
    )
    factors = library.factors_for_groups([DISTRIBUTION_GROUP])

    assert [factor.factor_id for factor in factors] == [
        "distribution_risk_research.ret_skew_20d",
        "distribution_risk_research.ret_kurt_20d",
    ]
    assert factors[0].expression == "Skew($close/Ref($close,1)-1,20)"
    assert factors[1].expression == "Kurt($close/Ref($close,1)-1,20)"
    assert all(factor.status == "candidate" for factor in factors)
    assert all("Ref($close,-" not in factor.expression.replace(" ", "") for factor in factors)


def test_future_drawdown_severity_is_forward_adverse_excursion() -> None:
    close = pd.Series([100.0, 95.0, 90.0, 110.0], index=pd.date_range("2026-01-01", periods=4))

    result = _future_drawdown_severity(close, horizon=2)

    assert result.iloc[0] == pytest.approx(0.10)
    assert result.iloc[1] == pytest.approx(-((90.0 / 95.0) - 1.0))
    assert np.isnan(result.iloc[-1])


def test_partial_spearman_removes_shared_control_and_keeps_incremental_ordering() -> None:
    index = pd.date_range("2024-01-01", periods=120)
    control = pd.Series(np.linspace(-2.0, 2.0, len(index)), index=index)
    incremental = pd.Series(np.sin(np.linspace(0.0, 10.0, len(index))), index=index)
    signal = control + incremental
    outcome = 3.0 * control + 2.0 * incremental
    controls = pd.DataFrame({"control": control})

    value = _partial_spearman(signal, outcome, controls)

    assert value > 0.5


def test_tail_spread_uses_high_risk_minus_low_risk_outcome() -> None:
    index = pd.date_range("2024-01-01", periods=100)
    signal = pd.Series(np.arange(100, dtype=float), index=index)
    outcome = 0.1 * signal

    assert _tail_spread(signal, outcome) > 0.0


def test_phase4_gate_is_explicit_and_not_a_model_promotion_threshold() -> None:
    assert DIRECT_SPEARMAN_MIN == 0.08
    assert PARTIAL_SPEARMAN_MIN == 0.05
    assert MIN_POSITIVE_WINDOW_SHARE == 0.60
    assert MIN_STRONG_OUTCOMES == 2
