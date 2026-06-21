"""T49.1: Model-bound factor attribution tests.

Verify that attribution accepts and enforces model version / data snapshot
identities, minimum-observation policies, and regularization options.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# _estimate_factor_model: min_observations enforcement
# ---------------------------------------------------------------------------


def test_estimate_factor_model_enforces_min_observations():
    """Returns zero betas when observations are below the minimum."""
    from src.research.factor_attribution import _estimate_factor_model

    # 5 periods, min_observations=10 → should fail
    idx = [f"2021-{m:02d}-01" for m in range(1, 6)]
    portfolio = pd.Series([0.01, -0.02, 0.03, 0.01, 0.02], index=idx)
    factors = pd.DataFrame({"momentum": [0.02, 0.01, -0.01, 0.03, 0.01]}, index=idx)

    betas, r2, residuals = _estimate_factor_model(portfolio, factors, min_observations=10)
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
    # Portfolio = 0.5 * factor + noise
    portfolio_ret = 0.5 * factor_ret + np.random.randn(n) * 0.005
    portfolio = pd.Series(portfolio_ret, index=idx)
    factors = pd.DataFrame({"f1": factor_ret}, index=idx)

    betas, r2, residuals = _estimate_factor_model(portfolio, factors, min_observations=12)
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
    # Two nearly identical factors
    f1 = base + np.random.randn(n) * 0.001
    f2 = base + np.random.randn(n) * 0.001
    portfolio_ret = 0.3 * f1 + 0.2 * f2 + np.random.randn(n) * 0.005
    portfolio = pd.Series(portfolio_ret, index=idx)
    factors = pd.DataFrame({"f1": f1, "f2": f2}, index=idx)

    betas, r2, residuals = _estimate_factor_model(
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
    d = report.to_dict()
    assert d["observation_count"] == 12
    assert d["observation_window"] == "12 monthly periods"
    assert d["methodology"] == "OLS"
    assert d["n_factors"] == 1
    assert d["model_version_id"] == "mv_abc123"
    assert d["data_snapshot_id"] == "ds_xyz789"
    assert "Low confidence" in d["confidence_note"]


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
    d = report.to_dict()
    assert d["observation_count"] == 0
    assert d["methodology"] == "OLS"
    assert d["n_factors"] == 0
    assert d["model_version_id"] is None
    assert d["confidence_note"] == ""


# ---------------------------------------------------------------------------
# API contract: AttributionRequest validation
# ---------------------------------------------------------------------------


def test_attribution_request_accepts_model_version_id():
    """AttributionRequest accepts and validates model_version_id."""
    from src.api.routers.factors import AttributionRequest

    req = AttributionRequest(
        market="us",
        model_version_id="mv_test123",
        min_observations=24,
        regularization="ridge",
    )
    assert req.model_version_id == "mv_test123"
    assert req.min_observations == 24
    assert req.regularization == "ridge"


def test_attribution_request_rejects_invalid_regularization():
    """AttributionRequest rejects unknown regularization values."""
    from src.api.routers.factors import AttributionRequest

    with pytest.raises(Exception):  # Pydantic validation error
        AttributionRequest(market="us", regularization="lasso")


def test_attribution_request_min_observations_bounds():
    """min_observations is clamped to [3, 120]."""
    from src.api.routers.factors import AttributionRequest

    with pytest.raises(Exception):
        AttributionRequest(market="us", min_observations=2)
    with pytest.raises(Exception):
        AttributionRequest(market="us", min_observations=121)


def test_attribution_request_default_min_observations():
    """Default min_observations is 12."""
    from src.api.routers.factors import AttributionRequest

    req = AttributionRequest(market="us")
    assert req.min_observations == 12
