"""Tests for StockDecisionEngine — the per-stock decision support system."""

from __future__ import annotations

import math
from unittest.mock import patch

import pandas as pd
import pytest

from src.strategies.stock_decision_engine import (
    DEFAULT_DECISION_CONFIG,
    FactorSnapshot,
    PriceTargets,
    StockDecision,
    StockDecisionEngine,
    StrategyRecommendation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    return StockDecisionEngine()


@pytest.fixture
def sample_pred_score():
    """Cross-sectional model scores for 10 stocks."""
    instruments = ["AAPL", "NVDA", "MSFT", "TSLA", "META", "AMZN", "GOOG", "NFLX", "AMD", "INTC"]
    scores = [0.62, 0.71, 0.31, -0.15, 0.45, 0.22, 0.18, -0.05, 0.55, -0.10]
    return pd.Series(scores, index=instruments)


@pytest.fixture
def sample_rank_map():
    """Rank map matching sample_pred_score (sorted descending)."""
    return {
        "NVDA": 0, "AAPL": 1, "AMD": 2, "META": 3, "MSFT": 4,
        "AMZN": 5, "GOOG": 6, "NFLX": 7, "INTC": 8, "TSLA": 9,
    }


# ---------------------------------------------------------------------------
# StockDecision dataclass tests
# ---------------------------------------------------------------------------


class TestStockDecision:
    def test_to_dict_basic(self):
        d = StockDecision(
            symbol="AAPL",
            signal="BUY",
            confidence=0.78,
            score=0.62,
            rank=2,
            reasons=["test reason"],
            factor_snapshot={},
            guardrail_status={},
            risk_flags=[],
            timestamp="2026-06-17",
        )
        result = d.to_dict()
        assert result["symbol"] == "AAPL"
        assert result["signal"] == "BUY"
        assert result["confidence"] == 0.78
        assert result["score"] == 0.62
        assert result["rank"] == 2
        assert result["reasons"] == ["test reason"]

    def test_to_dict_nan_score(self):
        d = StockDecision(
            symbol="TSLA",
            signal="HOLD",
            confidence=0.5,
            score=float("nan"),
            rank=None,
        )
        result = d.to_dict()
        assert result["score"] is None

    def test_factor_snapshot_serialization(self):
        snap = FactorSnapshot(
            name="mom_20d",
            expression="$close/Ref($close,20)-1",
            value=0.12,
            z_score=1.8,
            percentile=92.0,
            category="momentum",
        )
        d = StockDecision(
            symbol="AAPL",
            signal="BUY",
            confidence=0.7,
            score=0.5,
            rank=1,
            factor_snapshot={"mom_20d": snap},
        )
        result = d.to_dict()
        assert "mom_20d" in result["factor_snapshot"]
        assert result["factor_snapshot"]["mom_20d"]["z_score"] == 1.8


# ---------------------------------------------------------------------------
# Engine evaluation tests (mocked Qlib)
# ---------------------------------------------------------------------------


class TestEngineEvaluation:
    """Test the decision engine with mocked Qlib data."""

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_buy_signal_top_rank_positive_score(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """Stock with top rank and positive score should get BUY signal."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        decision = engine.evaluate(
            symbol="NVDA",
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "BUY"
        assert decision.symbol == "NVDA"
        assert decision.rank == 0
        assert decision.score > 0
        assert decision.confidence > 0.5

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_sell_signal_negative_score_bottom_rank(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """Stock with bottom rank and negative score should get SELL signal."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        decision = engine.evaluate(
            symbol="TSLA",
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "SELL"
        assert decision.rank == 9  # bottom
        assert decision.score < 0

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_hold_signal_mid_rank(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score
    ):
        """Stock with mid-range rank and small positive score should get HOLD."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        # Create a larger rank_map where MSFT is at rank 30 (beyond buy_rank_topk=20)
        large_rank_map = {f"STOCK_{i}": i for i in range(50)}
        large_rank_map["MSFT"] = 30

        # Adjust score to be slightly positive (above sell threshold but not triggering BUY)
        adjusted_score = sample_pred_score.copy()
        adjusted_score["MSFT"] = 0.05

        decision = engine.evaluate(
            symbol="MSFT",
            pred_score=adjusted_score,
            rank_map=large_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "HOLD"
        assert decision.rank == 30

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_sell_on_guardrail_failure(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """Stock failing guardrails should get SELL even with good rank."""
        mock_guardrails.return_value = {
            "overall_passed": False,
            "liquidity": {"passed": False, "reason": "Low liquidity", "metric": 500000},
        }
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        decision = engine.evaluate(
            symbol="NVDA",  # top rank
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "SELL"
        assert any("护栏拦截" in r for r in decision.reasons)

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_sell_on_ma_cross_under(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """Stock with MA cross-under should get SELL."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = "📉 MA60 死叉 — 价格 140.00 < MA60 150.00（偏离 -6.7%）"
        mock_factors.return_value = ({}, [])

        decision = engine.evaluate(
            symbol="AAPL",
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "SELL"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_sell_on_risk_flags(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """Stock with stop-loss risk flag should get SELL."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        held_positions = {
            "AAPL": {
                "entry_price": 180.0,
                "current_price": 150.0,  # -16.7% loss
                "peak_price": 190.0,
                "weight": 0.2,
            }
        }

        decision = engine.evaluate(
            symbol="AAPL",
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            held_positions=held_positions,
            include_factors=False,
        )

        assert decision.signal == "SELL"
        assert "stop_loss" in decision.risk_flags


# ---------------------------------------------------------------------------
# Confidence computation tests
# ---------------------------------------------------------------------------


class TestConfidence:
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_confidence_range(self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map):
        """Confidence should always be between 0.1 and 0.95."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        for symbol in sample_pred_score.index:
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=sample_pred_score,
                rank_map=sample_rank_map,
                market="us",
                include_factors=False,
            )
            assert 0.1 <= decision.confidence <= 0.95, f"{symbol}: {decision.confidence}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    def test_higher_confidence_for_top_rank(
        self, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """Top-ranked stock should have higher confidence than bottom-ranked."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])

        top = engine.evaluate("NVDA", sample_pred_score, sample_rank_map, "us", include_factors=False)
        bottom = engine.evaluate("TSLA", sample_pred_score, sample_rank_map, "us", include_factors=False)

        assert top.confidence > bottom.confidence


# ---------------------------------------------------------------------------
# FactorSnapshot tests
# ---------------------------------------------------------------------------


class TestFactorSnapshot:
    def test_to_dict(self):
        snap = FactorSnapshot(
            name="test_factor",
            expression="$close/Ref($close,10)-1",
            value=0.05,
            z_score=1.2,
            percentile=85.0,
            category="momentum",
        )
        d = snap.to_dict()
        assert d["name"] == "test_factor"
        assert d["value"] == 0.05
        assert d["z_score"] == 1.2
        assert d["percentile"] == 85.0

    def test_none_values(self):
        snap = FactorSnapshot(name="empty", expression="")
        d = snap.to_dict()
        assert d["value"] is None
        assert d["z_score"] is None
        assert d["percentile"] is None


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_config_keys(self):
        expected_keys = {
            "extension_threshold", "vol_threshold", "min_liquidity",
            "sell_ma_window", "buy_rank_topk", "sell_rank_threshold",
            "buy_score_threshold", "sell_score_threshold",
            "factor_z_extreme",
            "weight_model", "weight_guardrail", "weight_factor", "weight_trend",
        }
        assert expected_keys.issubset(set(DEFAULT_DECISION_CONFIG.keys()))

    def test_custom_config_override(self):
        engine = StockDecisionEngine(config={"buy_rank_topk": 10})
        assert engine.config["buy_rank_topk"] == 10
        # Other defaults should be preserved
        assert engine.config["sell_rank_threshold"] == DEFAULT_DECISION_CONFIG["sell_rank_threshold"]


# ---------------------------------------------------------------------------
# Strategy recommendation tests (P1-1)
# ---------------------------------------------------------------------------


class TestStrategyRecommendation:
    def test_to_dict(self):
        rec = StrategyRecommendation(
            name="dual_layer",
            display_name="Dual Layer Strategy",
            reason="多因子信号丰富",
            confidence=0.85,
        )
        d = rec.to_dict()
        assert d["name"] == "dual_layer"
        assert d["display_name"] == "Dual Layer Strategy"
        assert d["confidence"] == 0.85

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_buy_signal_gets_recommendation(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """BUY signal should include a strategy recommendation."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        decision = engine.evaluate(
            symbol="NVDA",
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "BUY"
        assert decision.recommended_strategy is not None
        assert decision.recommended_strategy.name in ("biweekly_trend", "dual_layer", "weekly_quant_rating")
        assert 0 < decision.recommended_strategy.confidence <= 1

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_hold_signal_no_recommendation(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score
    ):
        """HOLD signal should not include a strategy recommendation."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        large_rank_map = {f"STOCK_{i}": i for i in range(50)}
        large_rank_map["MSFT"] = 30
        adjusted_score = sample_pred_score.copy()
        adjusted_score["MSFT"] = 0.05

        decision = engine.evaluate(
            symbol="MSFT",
            pred_score=adjusted_score,
            rank_map=large_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.signal == "HOLD"
        assert decision.recommended_strategy is None


# ---------------------------------------------------------------------------
# Price targets tests (P1-2)
# ---------------------------------------------------------------------------


class TestPriceTargets:
    def test_to_dict(self):
        pt = PriceTargets(
            current_price=185.50,
            buy_range_low=183.00,
            buy_range_high=188.00,
            stop_loss_price=178.00,
            target_price=197.00,
            atr_20=3.50,
            support=180.00,
            resistance=192.00,
        )
        d = pt.to_dict()
        assert d["current_price"] == 185.50
        assert d["buy_range_low"] == 183.00
        assert d["stop_loss_price"] == 178.00
        assert d["target_price"] == 197.00
        assert d["atr_20"] == 3.50

    def test_none_values(self):
        pt = PriceTargets()
        d = pt.to_dict()
        assert d["current_price"] is None
        assert d["stop_loss_price"] is None

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_buy_signal_includes_price_targets(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine, sample_pred_score, sample_rank_map
    ):
        """BUY signal should include price targets when available."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = PriceTargets(
            current_price=185.0,
            buy_range_low=183.0,
            buy_range_high=187.0,
            stop_loss_price=179.0,
            target_price=196.0,
        )

        decision = engine.evaluate(
            symbol="NVDA",
            pred_score=sample_pred_score,
            rank_map=sample_rank_map,
            market="us",
            include_factors=False,
        )

        assert decision.price_targets is not None
        assert decision.price_targets.buy_range_low == 183.0
        assert decision.price_targets.stop_loss_price == 179.0

    def test_decision_to_dict_includes_new_fields(self):
        """StockDecision.to_dict() should include recommended_strategy and price_targets."""
        rec = StrategyRecommendation("dual_layer", "Dual Layer", "test", 0.8)
        pt = PriceTargets(current_price=100.0, stop_loss_price=95.0)
        d = StockDecision(
            symbol="TEST",
            signal="BUY",
            confidence=0.7,
            score=0.5,
            rank=1,
            recommended_strategy=rec,
            price_targets=pt,
        ).to_dict()

        assert "recommended_strategy" in d
        assert d["recommended_strategy"]["name"] == "dual_layer"
        assert "price_targets" in d
        assert d["price_targets"]["stop_loss_price"] == 95.0
