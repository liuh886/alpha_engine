"""T49.1: Model-bound factor attribution tests.

Verify the maintained attribution engine's observation policy, regularization,
and model/data identity metadata. The retired factor API router is not part of
the current application surface and is intentionally not recreated here.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# _estimate_factor_model: min_observations enforcement
# ---------------------------------------------------------------------------


def test_estimate_factor_model_enforces_min_observations():
    """Returns zero betas when observations are below the minimum."""
    from src.research.factor_attribution import _estimate_factor_model

    idx = [f"2021-{m:02d}-01" for m in range(1, 6)]
    portfolio = pd.Series([0.01, -0.02, 0.03, 0.01, 0.02], index=idx)
    factors = pd.DataFrame({"momentum": [0.02, 0.01, -0.01, 0.03, 0.01]}, index=idx)

    betas, r2, residuals = _estimate_factor_model(
        portfolio, factors, min_observations=10
    )
    assert len(betas) == 1
    assert betas[0] == 0.0
    assert r2 == 0.0
    assert len(residuals) == 0


def test_estimate_factor_model_passes_with_enough_observations():
    """Returns non-zero betas when observations meet the minimum."""
    from src.research.factor_attribution import _estimate_factor_model

    np.random.seed(42)
    n = 24
    idx = [f"2021-{m:02d}-01" for m in range(1, n + 1)]
    factor_ret = np.random.randn(n) * 0.02
    portfolio_ret = 0.5 * factor_ret + np.random.randn(n) * 0.005
    portfolio = pd.Series(portfolio_ret, index=idx)
    factors = pd.DataFrame({"f1": factor_ret}, index=idx)

    betas, r2, residuals = _estimate_factor_model(
        portfolio, factors, min_observations=12
    )
    assert len(betas) == 1
    assert abs(betas[0]) > 0
    assert r2 > 0
    assert len(residuals) == n


# ---------------------------------------------------------------------------
# _estimate_factor_model: ridge regularization
# ---------------------------------------------------------------------------


def test_estimate_factor_model_ridge_returns_valid_betas():
    """Ridge regularization produces finite betas even with collinear factors."""
    from src.research.factor_attribution import _estimate_factor_model

    np.random.seed(42)
    n = 24
    idx = [f"2021-{m:02d}-01" for m in range(1, n + 1)]
    base = np.random.randn(n) * 0.02
    f1 = base + np.random.randn(n) * 0.001
    f2 = base + np.random.randn(n) * 0.001
    portfolio_ret = 0.3 * f1 + 0.2 * f2 + np.random.randn(n) * 0.005
    portfolio = pd.Series(portfolio_ret, index=idx)
    factors = pd.DataFrame({"f1": f1, "f2": f2}, index=idx)

    betas, r2, _residuals = _estimate_factor_model(
        portfolio, factors, min_observations=12, regularization="ridge"
    )
    assert len(betas) == 2
    assert all(np.isfinite(b) for b in betas)
    assert r2 > 0


# ---------------------------------------------------------------------------
# AttributionReport: observation metadata fields
# ---------------------------------------------------------------------------


def test_attribution_report_includes_observation_metadata():
    """AttributionReport.to_dict() includes all T49.1 metadata fields."""
    from src.research.factor_attribution import (
        AttributionReport,
        FactorContribution,
    )

    report = AttributionReport(
        strategy_name="test",
        market="us",
        period="2021-01-01 to 2022-01-01",
        total_return=0.15,
        benchmark_return=0.10,
        excess_return=0.05,
        factor_contributions=[
            FactorContribution(
                factor_name="momentum",
                factor_expression="Ref($close, -20)/$close - 1",
                factor_ic=0.05,
                factor_return=0.03,
                return_contribution_pct=60.0,
                risk_contribution_pct=45.0,
                exposure=1.2,
            )
        ],
        unexplained_return=0.02,
        factor_coverage=60.0,
        attribution_confidence=0.65,
        observation_count=12,
        observation_window="12 monthly periods",
        methodology="OLS",
        n_factors=1,
        model_version_id="mv_abc123",
        data_snapshot_id="ds_xyz789",
        confidence_note="Low confidence: only 12 monthly observations.",
    )
    result = report.to_dict()
    assert result["observation_count"] == 12
    assert result["observation_window"] == "12 monthly periods"
    assert result["methodology"] == "OLS"
    assert result["n_factors"] == 1
    assert result["model_version_id"] == "mv_abc123"
    assert result["data_snapshot_id"] == "ds_xyz789"
    assert "Low confidence" in result["confidence_note"]


def test_attribution_report_defaults_observation_fields():
    """Default AttributionReport has empty observation metadata."""
    from src.research.factor_attribution import AttributionReport

    report = AttributionReport(
        strategy_name="default",
        market="us",
        period="2021-01-01 to 2022-01-01",
        total_return=0.0,
        benchmark_return=0.0,
        excess_return=0.0,
        factor_contributions=[],
        unexplained_return=0.0,
        factor_coverage=0.0,
        attribution_confidence=0.0,
    )
    result = report.to_dict()
    assert result["observation_count"] == 0
    assert result["methodology"] == "OLS"
    assert result["n_factors"] == 0
    assert result["model_version_id"] is None
    assert result["confidence_note"] == ""
