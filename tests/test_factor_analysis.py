"""Tests for the framework-neutral Factor IC analysis engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd


def _make_synthetic_factor_data(
    n_dates: int = 60,
    n_stocks: int = 50,
    n_factors: int = 5,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2021-01-01", periods=n_dates, freq="B")
    instruments = [f"STOCK_{i:03d}" for i in range(n_stocks)]
    idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])

    factor_data = {f"factor_{i}": rng.randn(len(idx)) for i in range(n_factors)}
    signal = factor_data["factor_0"] * 0.05 + rng.randn(len(idx)) * 0.02
    return pd.DataFrame(factor_data, index=idx), pd.DataFrame({"label": signal}, index=idx)


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
        payload = result.to_dict()
        assert payload["factor_name"] == "test_factor"
        assert payload["ic"] == 0.035
        assert payload["rank_ic"] == 0.042
        assert payload["ic_ir"] == 2.333
        assert payload["positive_ic_ratio"] == 0.75

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
        payload = report.to_dict()
        assert payload["market"] == "us"
        assert payload["n_periods"] == 48
        assert len(payload["factors"]) == 2
        assert len(payload["top_factors"]) == 1

    def test_decay_point_to_dict(self):
        from src.research.factor_analysis import DecayPoint

        payload = DecayPoint(lag_days=5, ic=0.035).to_dict()
        assert payload["lag_days"] == 5
        assert payload["ic"] == 0.035


class TestComputeFactorIC:
    @patch("src.research.factor_analysis._init_qlib")
    @patch("src.research.factor_analysis._compute_forward_returns")
    @patch("src.research.factor_analysis._load_factor_names")
    @patch("src.research.factor_analysis._load_cached", return_value=None)
    @patch("src.research.factor_analysis._save_cache")
    def test_basic_computation(self, mock_save, mock_cache, mock_names, mock_fwd, mock_init):
        from src.research.factor_analysis import compute_factor_ic

        factor_df, label_df = _make_synthetic_factor_data()
        mock_names.return_value = list(factor_df.columns)
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
        assert report.factors
        assert len(report.top_factors) <= 20
        factor_zero = next(factor for factor in report.factors if factor.factor_name == "factor_0")
        assert factor_zero.ic > 0 or factor_zero.rank_ic > 0

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
        assert not report.factors


class TestComputeFactorDecay:
    @patch("src.research.factor_analysis._init_qlib")
    @patch("src.research.factor_analysis._compute_forward_returns")
    def test_decay_returns_points(self, mock_fwd, mock_init):
        from src.research.factor_analysis import compute_factor_decay

        rng = np.random.RandomState(42)
        dates = pd.bdate_range("2021-01-01", periods=60, freq="B")
        instruments = [f"S{i:03d}" for i in range(20)]
        index = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
        factor_df = pd.DataFrame({"my_factor": rng.randn(len(index))}, index=index)
        mock_fwd.return_value = pd.Series(
            rng.randn(len(index)) * 0.01 + factor_df["my_factor"].values * 0.02,
            index=index,
            name="forward_return",
        )
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
        assert all(point.lag_days == index + 1 for index, point in enumerate(result))
        assert all(isinstance(point.ic, float) for point in result)

    def test_empty_factor_name_returns_empty(self):
        from src.research.factor_analysis import compute_factor_decay

        assert compute_factor_decay(factor_name="") == []


class TestCache:
    def test_cache_roundtrip(self, tmp_path):
        import src.research.factor_analysis as module
        from src.research.factor_analysis import _load_cached, _save_cache

        original_dir = module._CACHE_DIR
        module._CACHE_DIR = tmp_path
        try:
            data = {"market": "us", "test": True, "factors": []}
            _save_cache("us", "2021-01-01", "2024-12-31", data)
            assert _load_cached("us", "2021-01-01", "2024-12-31") == data
        finally:
            module._CACHE_DIR = original_dir

    def test_cache_miss_returns_none(self):
        from src.research.factor_analysis import _load_cached

        assert _load_cached("nonexistent", "2021-01-01", "2024-12-31") is None
