"""Tests for Factor IC Analysis engine and API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------


def _make_synthetic_factor_data(
    n_dates: int = 60,
    n_stocks: int = 50,
    n_factors: int = 5,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create synthetic factor data and label data for testing.

    Returns (factor_df, label_df) with MultiIndex (datetime, instrument).
    """
    rng = np.random.RandomState(seed)

    dates = pd.bdate_range("2021-01-01", periods=n_dates, freq="B")
    instruments = [f"STOCK_{i:03d}" for i in range(n_stocks)]

    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )

    # Generate factor values
    factor_data = {}
    for i in range(n_factors):
        factor_data[f"factor_{i}"] = rng.randn(len(idx))

    # Factor 0 has a real signal: correlated with forward returns
    signal = factor_data["factor_0"] * 0.05 + rng.randn(len(idx)) * 0.02
    factor_df = pd.DataFrame(factor_data, index=idx)
    label_df = pd.DataFrame({"label": signal}, index=idx)

    return factor_df, label_df


# ---------------------------------------------------------------------------
# Unit tests: cross_sectional_ic
# ---------------------------------------------------------------------------


class TestCrossSectionalIC:
    def test_perfect_positive_correlation(self):
        from src.research.factor_analysis import _cross_sectional_ic

        values = pd.Series(np.arange(100, dtype=float))
        returns = pd.Series(np.arange(100, dtype=float))
        pearson, spearman = _cross_sectional_ic(values, returns)
        assert pearson > 0.99
        assert spearman > 0.99

    def test_perfect_negative_correlation(self):
        from src.research.factor_analysis import _cross_sectional_ic

        values = pd.Series(np.arange(100, dtype=float))
        returns = pd.Series(-np.arange(100, dtype=float))
        pearson, spearman = _cross_sectional_ic(values, returns)
        assert pearson < -0.99
        assert spearman < -0.99

    def test_no_correlation(self):
        from src.research.factor_analysis import _cross_sectional_ic

        rng = np.random.RandomState(99)
        values = pd.Series(rng.randn(200))
        returns = pd.Series(rng.randn(200))
        pearson, spearman = _cross_sectional_ic(values, returns)
        assert abs(pearson) < 0.3
        assert abs(spearman) < 0.3

    def test_too_few_samples_returns_nan(self):
        from src.research.factor_analysis import _cross_sectional_ic

        values = pd.Series([1.0, 2.0])
        returns = pd.Series([1.0, 2.0])
        pearson, spearman = _cross_sectional_ic(values, returns)
        assert np.isnan(pearson)
        assert np.isnan(spearman)


# ---------------------------------------------------------------------------
# Unit tests: data classes
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_factor_ic_result_to_dict(self):
        from src.research.factor_analysis import FactorICResult

        result = FactorICResult(
            factor_name="test_factor",
            ic=0.035,
            rank_ic=0.042,
            ic_std=0.015,
            ic_ir=2.333,
            positive_ic_ratio=0.75,
            t_stat=3.456,
        )
        d = result.to_dict()
        assert d["factor_name"] == "test_factor"
        assert d["ic"] == 0.035
        assert d["rank_ic"] == 0.042
        assert d["ic_ir"] == 2.333
        assert d["positive_ic_ratio"] == 0.75

    def test_factor_analysis_report_to_dict(self):
        from src.research.factor_analysis import FactorAnalysisReport, FactorICResult

        factors = [
            FactorICResult("f1", 0.03, 0.04, 0.01, 3.0, 0.7, 5.0),
            FactorICResult("f2", -0.02, -0.025, 0.02, -1.0, 0.3, -2.0),
        ]
        report = FactorAnalysisReport(
            market="us",
            date_range=("2021-01-01", "2024-12-31"),
            forward_days=10,
            n_periods=48,
            factors=factors,
            top_factors=factors[:1],
            generated_at="2024-01-01T00:00:00",
        )
        d = report.to_dict()
        assert d["market"] == "us"
        assert d["n_periods"] == 48
        assert len(d["factors"]) == 2
        assert len(d["top_factors"]) == 1

    def test_decay_point_to_dict(self):
        from src.research.factor_analysis import DecayPoint

        dp = DecayPoint(lag_days=5, ic=0.035)
        d = dp.to_dict()
        assert d["lag_days"] == 5
        assert d["ic"] == 0.035


# ---------------------------------------------------------------------------
# Unit tests: compute_factor_ic (with mocked Qlib internals)
# ---------------------------------------------------------------------------


class TestComputeFactorIC:
    @patch("src.research.factor_analysis._init_qlib")
    @patch("src.research.factor_analysis._compute_forward_returns")
    @patch("src.research.factor_analysis._load_factor_names")
    @patch("src.research.factor_analysis._load_cached", return_value=None)
    @patch("src.research.factor_analysis._save_cache")
    def test_basic_computation(
        self,
        mock_save,
        mock_cache,
        mock_names,
        mock_fwd,
        mock_init,
    ):
        """Test compute_factor_ic with a mocked DataHandlerLP."""

        from src.research.factor_analysis import compute_factor_ic

        factor_df, label_df = _make_synthetic_factor_data()
        mock_names.return_value = [c for c in factor_df.columns]
        # _compute_forward_returns returns a Series indexed like the factors
        mock_fwd.return_value = label_df.iloc[:, 0]

        handler_instance = MagicMock()
        handler_instance.fetch.side_effect = lambda col_set="feature": (
            factor_df if col_set == "feature" else label_df
        )

        with patch("qlib.data.dataset.handler.DataHandlerLP", return_value=handler_instance):
            report = compute_factor_ic(
                market="us",
                start_date="2021-01-01",
                end_date="2021-06-30",
                forward_days=10,
                freq="ME",
                use_cache=False,
            )

        assert report.market == "us"
        assert report.n_periods > 0
        assert len(report.factors) > 0
        assert len(report.top_factors) <= 20

        # Factor 0 should have positive IC (it has real signal)
        f0 = next(f for f in report.factors if f.factor_name == "factor_0")
        assert f0.ic > 0 or f0.rank_ic > 0

    @patch("src.research.factor_analysis._init_qlib")
    @patch("src.research.factor_analysis._compute_forward_returns")
    @patch("src.research.factor_analysis._load_factor_names")
    @patch("src.research.factor_analysis._load_cached", return_value=None)
    @patch("src.research.factor_analysis._save_cache")
    def test_empty_data_returns_empty_report(
        self,
        mock_save,
        mock_cache,
        mock_names,
        mock_fwd,
        mock_init,
    ):
        """Test compute_factor_ic with empty factor data."""

        from src.research.factor_analysis import compute_factor_ic

        mock_names.return_value = ["factor_1"]
        mock_fwd.return_value = pd.Series(dtype=float)

        handler_instance = MagicMock()
        handler_instance.fetch.return_value = pd.DataFrame()

        with patch("qlib.data.dataset.handler.DataHandlerLP", return_value=handler_instance):
            report = compute_factor_ic(
                market="us",
                start_date="2021-01-01",
                end_date="2021-06-30",
                use_cache=False,
            )

        assert report.n_periods == 0
        assert len(report.factors) == 0


# ---------------------------------------------------------------------------
# Unit tests: compute_factor_decay (with mocked Qlib internals)
# ---------------------------------------------------------------------------


class TestComputeFactorDecay:
    @patch("src.research.factor_analysis._init_qlib")
    @patch("src.research.factor_analysis._compute_forward_returns")
    def test_decay_returns_points(self, mock_fwd, mock_init):

        from src.research.factor_analysis import compute_factor_decay

        rng = np.random.RandomState(42)
        dates = pd.bdate_range("2021-01-01", periods=60, freq="B")
        instruments = [f"S{i:03d}" for i in range(20)]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"]
        )

        factor_df = pd.DataFrame({"my_factor": rng.randn(len(idx))}, index=idx)
        fwd_series = pd.Series(
            rng.randn(len(idx)) * 0.01 + factor_df["my_factor"].values * 0.02,
            index=idx,
            name="forward_return",
        )
        mock_fwd.return_value = fwd_series

        handler_instance = MagicMock()
        handler_instance.fetch.return_value = factor_df

        with patch("qlib.data.dataset.handler.DataHandlerLP", return_value=handler_instance):
            result = compute_factor_decay(
                market="us",
                factor_name="my_factor",
                max_lag=5,
                start_date="2021-01-01",
                end_date="2021-06-30",
            )

        assert len(result) == 5
        assert all(dp.lag_days == i + 1 for i, dp in enumerate(result))
        assert all(isinstance(dp.ic, float) for dp in result)

    def test_empty_factor_name_returns_empty(self):
        from src.research.factor_analysis import compute_factor_decay

        result = compute_factor_decay(factor_name="")
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests: cache helpers
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_roundtrip(self, tmp_path):
        import src.research.factor_analysis as mod
        from src.research.factor_analysis import _load_cached, _save_cache

        original_dir = mod._CACHE_DIR
        mod._CACHE_DIR = tmp_path

        try:
            data = {"market": "us", "test": True, "factors": []}
            _save_cache("us", "2021-01-01", "2024-12-31", data)
            loaded = _load_cached("us", "2021-01-01", "2024-12-31")
            assert loaded == data
        finally:
            mod._CACHE_DIR = original_dir

    def test_cache_miss_returns_none(self):
        from src.research.factor_analysis import _load_cached

        result = _load_cached("nonexistent", "2021-01-01", "2024-12-31")
        assert result is None


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestAPIEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api.routers.factors import router

        app = FastAPI()
        # Router already has prefix="/factors", mount at "/api" to match production
        app.include_router(router, prefix="/api")
        return TestClient(app)

    @patch("src.api.routers.factors._load_cached_report")
    def test_get_top_factors_from_cache(self, mock_cache, client):
        mock_cache.return_value = {
            "market": "us",
            "date_range": ["2021-01-01", "2024-12-31"],
            "forward_days": 10,
            "n_periods": 48,
            "factors": [
                {
                    "factor_name": f"f{i}",
                    "ic": 0.01 * i,
                    "rank_ic": 0.012 * i,
                    "ic_std": 0.005,
                    "ic_ir": 2.0,
                    "positive_ic_ratio": 0.7,
                    "t_stat": 3.0,
                }
                for i in range(30)
            ],
            "top_factors": [
                {
                    "factor_name": f"f{i}",
                    "ic": 0.01 * i,
                    "rank_ic": 0.012 * i,
                    "ic_std": 0.005,
                    "ic_ir": 2.0,
                    "positive_ic_ratio": 0.7,
                    "t_stat": 3.0,
                }
                for i in range(20)
            ],
            "generated_at": "2024-01-01T00:00:00",
        }

        resp = client.get("/api/factors/ic/top?market=us&n=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["n"] == 10
        assert len(data["top_factors"]) == 10

    @patch("src.api.routers.factors._load_cached_report")
    def test_get_top_factors_no_cache_computes(self, mock_cache, client):
        mock_cache.return_value = None

        with patch("src.research.factor_analysis.compute_factor_ic") as mock_compute:
            from src.research.factor_analysis import FactorAnalysisReport, FactorICResult

            mock_compute.return_value = FactorAnalysisReport(
                market="us",
                date_range=("2021-01-01", "2024-12-31"),
                forward_days=10,
                n_periods=3,
                factors=[
                    FactorICResult(f"f{i}", 0.01, 0.012, 0.005, 2.0, 0.7, 3.0)
                    for i in range(5)
                ],
                top_factors=[
                    FactorICResult(f"f{i}", 0.01, 0.012, 0.005, 2.0, 0.7, 3.0)
                    for i in range(3)
                ],
                generated_at="2024-01-01T00:00:00",
            )

            resp = client.get("/api/factors/ic/top?market=us&n=3")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["cached"] is False

    def test_invalid_market_returns_422(self, client):
        resp = client.get("/api/factors/ic?market=invalid")
        assert resp.status_code == 422

    def test_decay_missing_factor_returns_422(self, client):
        resp = client.get("/api/factors/decay?market=us")
        assert resp.status_code == 422

    @patch("src.research.factor_analysis.compute_factor_decay")
    def test_decay_endpoint(self, mock_decay, client):
        from src.research.factor_analysis import DecayPoint

        mock_decay.return_value = [
            DecayPoint(lag_days=i, ic=0.05 / i) for i in range(1, 11)
        ]

        resp = client.get("/api/factors/decay?market=us&factor=close&max_lag=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["decay"]) == 10
        assert data["decay"][0]["lag_days"] == 1
