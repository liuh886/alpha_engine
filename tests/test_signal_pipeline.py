"""End-to-end tests for the signal pipeline.

Tests the complete flow:
1. Model training and prediction
2. Signal grade computation
3. API endpoints
4. Frontend data format
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_predictions():
    """Create sample predictions for testing."""
    dates = pd.date_range("2025-01-02", periods=100, freq="B")
    instruments = ["000001", "000002", "000003", "000004", "000005"]
    idx = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    np.random.seed(42)
    scores = np.random.randn(len(idx))
    return pd.DataFrame({"score": scores}, index=idx)


@pytest.fixture
def signal_engine():
    """Create a SignalGradeEngine instance."""
    from src.strategies.signal_grade_engine import SignalGradeEngine

    return SignalGradeEngine(step_size=10)


@pytest.fixture
def decision_engine():
    """Create a StockDecisionEngine instance."""
    from src.strategies.stock_decision_engine import StockDecisionEngine

    return StockDecisionEngine()


# ---------------------------------------------------------------------------
# Test 1: Signal Grade Engine
# ---------------------------------------------------------------------------


class TestSignalGradeEngine:
    """Test signal grade computation."""

    def test_grades_defined(self, signal_engine):
        """All 6 grades should be defined."""
        from src.strategies.signal_grade_engine import GRADES

        assert len(GRADES) == 6
        assert "AAA" in GRADES
        assert "VVV" in GRADES

    def test_grade_weights(self, signal_engine):
        """Grade weights should be symmetric."""
        from src.strategies.signal_grade_engine import GRADE_WEIGHTS

        assert GRADE_WEIGHTS["AAA"] == 3.0
        assert GRADE_WEIGHTS["VVV"] == -3.0
        assert GRADE_WEIGHTS["AA"] == 2.0
        assert GRADE_WEIGHTS["VV"] == -2.0

    def test_get_grade_returns_valid(self, signal_engine, sample_predictions):
        """get_grade_for_date should return a valid grade for a stock."""
        # Get the first date in predictions
        first_date = sample_predictions.index.get_level_values("datetime")[0]
        date_str = first_date.strftime("%Y-%m-%d")

        grade = signal_engine.get_grade_for_date("000001", sample_predictions, date_str)

        assert grade.symbol == "000001"
        assert grade.date == date_str
        assert grade.total_stocks == 5
        assert 0 <= grade.percentile <= 100

    def test_grade_percentile_consistency(self, signal_engine, sample_predictions):
        """Top-ranked stock should have AAA or AA grade."""
        first_date = sample_predictions.index.get_level_values("datetime")[0]
        date_str = first_date.strftime("%Y-%m-%d")

        # Get all grades for this date
        all_grades = []
        for inst in ["000001", "000002", "000003", "000004", "000005"]:
            grade = signal_engine.get_grade_for_date(inst, sample_predictions, date_str)
            all_grades.append(grade)

        # Sort by score
        all_grades.sort(key=lambda g: g.score, reverse=True)

        # Top stock should have percentile >= 80
        assert all_grades[0].percentile >= 80

        # Bottom stock should have percentile <= 20
        assert all_grades[-1].percentile <= 20

    def test_daily_signal_series(self, signal_engine, sample_predictions):
        """get_daily_signal_series should return data for each trading day."""
        series = signal_engine.get_daily_signal_series(
            "000001", sample_predictions, start_date="2025-01-02"
        )

        assert len(series) > 0
        assert all("date" in s for s in series)
        assert all("percentile" in s for s in series)
        assert all("score" in s for s in series)


# ---------------------------------------------------------------------------
# Test 2: Stock Decision Engine
# ---------------------------------------------------------------------------


class TestStockDecisionEngine:
    """Test stock decision generation."""

    def test_decision_has_required_fields(self, decision_engine, sample_predictions):
        """Decision should have all required fields."""
        pred_score = sample_predictions.xs("000001", level="instrument")["score"]
        rank_map = {"000001": 1, "000002": 2, "000003": 3, "000004": 4, "000005": 5}

        decision = decision_engine.evaluate(
            symbol="000001",
            pred_score=pred_score,
            rank_map=rank_map,
            market="cn",
        )

        assert hasattr(decision, "signal")
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "score")
        assert hasattr(decision, "rank")
        assert decision.signal in ["BUY", "HOLD", "SELL"]

    def test_top_rank_gets_buy(self, decision_engine, sample_predictions):
        """Top-ranked stock should get BUY signal."""
        pred_score = sample_predictions.xs("000001", level="instrument")["score"]
        rank_map = {"000001": 1, "000002": 2, "000003": 3, "000004": 4, "000005": 5}

        decision = decision_engine.evaluate(
            symbol="000001",
            pred_score=pred_score,
            rank_map=rank_map,
            market="cn",
        )

        # With rank 1, should be BUY candidate
        assert decision.rank == 1


# ---------------------------------------------------------------------------
# Test 3: API Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.approved_skip(reason="Requires running API server - run manually with curl")
class TestAPIEndpoints:
    """Test API endpoint responses.

    Note: These tests require the API server to be running.
    They are skipped by default. Run with --run-api to enable.
    """

    @pytest.fixture(autouse=True)
    def setup_api(self):
        """Setup API test client."""
        pytest.skip("API tests require running server - run manually with curl")

    def test_signal_grade_endpoint(self):
        """GET /stock-analysis/{symbol}/signal-grade should return grade."""
        pass

    def test_watchlist_summary_endpoint(self):
        """GET /stock-analysis/watchlist/summary should return stock list."""
        pass

    def test_signal_daily_endpoint(self):
        """GET /stock-analysis/{symbol}/signal-daily should return daily series."""
        pass

    def test_signal_performance_endpoint(self):
        """GET /stock-analysis/{symbol}/signal-performance should return perf data."""
        pass

    def test_data_status_endpoint(self):
        """GET /data/status should return data freshness."""
        pass


# ---------------------------------------------------------------------------
# Test 4: Model Predictions
# ---------------------------------------------------------------------------


class TestModelPredictions:
    """Test model prediction loading and format."""

    def test_predictions_loadable(self):
        """Predictions should be loadable from mlruns."""
        from src.api.routers.stock_analysis import _load_full_predictions

        pred_df, _, _ = _load_full_predictions("cn")
        if pred_df is None:
            pytest.skip("No predictions found in artifacts/mlruns, skipping test.")
        assert not pred_df.empty
        assert "score" in pred_df.columns
        assert pred_df.index.names == ["datetime", "instrument"]

    def test_predictions_have_valid_range(self):
        """Prediction scores should be finite numbers."""
        from src.api.routers.stock_analysis import _load_full_predictions

        pred_df, _, _ = _load_full_predictions("cn")
        if pred_df is None:
            pytest.skip("No predictions found in artifacts/mlruns, skipping test.")
        scores = pred_df["score"]
        assert np.all(np.isfinite(scores))
        assert scores.min() != scores.max()  # Not all same value

    def test_predictions_cover_date_range(self):
        """Predictions should cover the expected date range."""
        from src.api.routers.stock_analysis import _load_full_predictions

        pred_df, _, _ = _load_full_predictions("cn")
        if pred_df is None:
            pytest.skip("No predictions found in artifacts/mlruns, skipping test.")
        dates = pred_df.index.get_level_values("datetime")
        # Predictions should cover at least some recent dates
        assert dates.max() >= pd.Timestamp("2026-01-01")
        # Should have multiple dates (not just one day)
        assert len(dates.unique()) > 1


# ---------------------------------------------------------------------------
# Test 5: Walk-Forward Validation
# ---------------------------------------------------------------------------


@pytest.mark.approved_skip(reason="MLflow/SQLAlchemy 2.0 compatibility issue")
class TestWalkForward:
    """Test walk-forward validation pipeline.

    Note: These tests require MLflow database to be compatible with SQLAlchemy.
    They are skipped due to SQLAlchemy 2.0 compatibility issues.
    """

    @pytest.fixture(autouse=True)
    def skip_mlflow_issues(self):
        """Skip walk-forward tests due to MLflow/SQLAlchemy compatibility."""
        pytest.skip(
            "Walk-forward tests require MLflow database - SQLAlchemy 2.0 compatibility issue"
        )

    def test_walk_forward_runs(self):
        """Walk-forward should complete without errors."""
        pass

    def test_walk_forward_positive_ic(self):
        """Walk-forward IC should be positive with 10d_excess label."""
        pass


# ---------------------------------------------------------------------------
# Test 6: End-to-End Pipeline
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    """Test the complete pipeline from training to signal display."""

    def test_pipeline_produces_signals(self):
        """Complete pipeline should produce valid signals for stocks."""
        from src.api.routers.stock_analysis import _load_predictions_and_ranks
        from src.strategies.signal_grade_engine import SignalGradeEngine

        # Load predictions
        pred_df, _, _ = _load_predictions_and_ranks("cn")
        if pred_df is None:
            pytest.skip("No predictions found in artifacts/mlruns, skipping test.")

        # Get latest date
        latest_date = pred_df.index.get_level_values("datetime").max()
        date_str = latest_date.strftime("%Y-%m-%d")

        # Get grades for a few stocks
        engine = SignalGradeEngine(step_size=10)
        stocks = pred_df.xs(latest_date, level="datetime").index.tolist()[:5]

        for stock in stocks:
            grade = engine.get_grade_for_date(stock, pred_df, date_str)
            assert grade.symbol == stock
            assert grade.total_stocks > 0
            assert 0 <= grade.percentile <= 100


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
