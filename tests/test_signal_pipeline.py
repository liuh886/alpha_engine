"""Domain tests for signal grading and stock-decision generation.

Browser endpoints and router-internal prediction loaders were retired with the
legacy Web architecture. Prediction loading belongs to research workflows and
artifact export; this module protects only the reusable signal engines.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_predictions():
    dates = pd.date_range("2025-01-02", periods=100, freq="B")
    instruments = ["000001", "000002", "000003", "000004", "000005"]
    index = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )
    rng = np.random.RandomState(42)
    return pd.DataFrame({"score": rng.randn(len(index))}, index=index)


@pytest.fixture
def signal_engine():
    from src.strategies.signal_grade_engine import SignalGradeEngine

    return SignalGradeEngine(step_size=10)


@pytest.fixture
def decision_engine():
    from src.strategies.stock_decision_engine import StockDecisionEngine

    return StockDecisionEngine()


class TestSignalGradeEngine:
    def test_grades_defined(self, signal_engine):
        from src.strategies.signal_grade_engine import GRADES

        assert len(GRADES) == 6
        assert "AAA" in GRADES
        assert "VVV" in GRADES

    def test_grade_weights_are_symmetric(self, signal_engine):
        from src.strategies.signal_grade_engine import GRADE_WEIGHTS

        assert GRADE_WEIGHTS["AAA"] == 3.0
        assert GRADE_WEIGHTS["VVV"] == -3.0
        assert GRADE_WEIGHTS["AA"] == 2.0
        assert GRADE_WEIGHTS["VV"] == -2.0

    def test_get_grade_returns_valid_record(self, signal_engine, sample_predictions):
        first_date = sample_predictions.index.get_level_values("datetime")[0]
        date_str = first_date.strftime("%Y-%m-%d")

        grade = signal_engine.get_grade_for_date("000001", sample_predictions, date_str)

        assert grade.symbol == "000001"
        assert grade.date == date_str
        assert grade.total_stocks == 5
        assert 0 <= grade.percentile <= 100

    def test_grade_percentile_ordering(self, signal_engine, sample_predictions):
        first_date = sample_predictions.index.get_level_values("datetime")[0]
        date_str = first_date.strftime("%Y-%m-%d")
        grades = [
            signal_engine.get_grade_for_date(symbol, sample_predictions, date_str)
            for symbol in ["000001", "000002", "000003", "000004", "000005"]
        ]
        grades.sort(key=lambda grade: grade.score, reverse=True)

        assert grades[0].percentile >= 80
        assert grades[-1].percentile <= 20

    def test_daily_signal_series(self, signal_engine, sample_predictions):
        series = signal_engine.get_daily_signal_series(
            "000001", sample_predictions, start_date="2025-01-02"
        )

        assert series
        assert all({"date", "percentile", "score"}.issubset(row) for row in series)


class TestStockDecisionEngine:
    def test_decision_has_required_fields(self, decision_engine, sample_predictions):
        pred_score = sample_predictions.xs("000001", level="instrument")["score"]
        rank_map = {"000001": 1, "000002": 2, "000003": 3, "000004": 4, "000005": 5}

        decision = decision_engine.evaluate(
            symbol="000001",
            pred_score=pred_score,
            rank_map=rank_map,
            market="cn",
        )

        assert decision.signal in {"BUY", "HOLD", "SELL"}
        assert hasattr(decision, "confidence")
        assert hasattr(decision, "score")
        assert decision.rank == 1

    def test_rank_identity_is_preserved(self, decision_engine, sample_predictions):
        pred_score = sample_predictions.xs("000003", level="instrument")["score"]
        rank_map = {"000001": 1, "000002": 2, "000003": 3, "000004": 4, "000005": 5}

        decision = decision_engine.evaluate(
            symbol="000003",
            pred_score=pred_score,
            rank_map=rank_map,
            market="cn",
        )

        assert decision.rank == 3
