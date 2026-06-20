"""Integration and consistency tests for the decision engine.

P3-1: End-to-end integration tests with mocked Qlib data
P3-3: Consistency tests — verify decision engine aligns with BiweeklyTrendStrategy sell rules
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.strategies.stock_decision_engine import (
    PriceTargets,
    StockDecision,
    StockDecisionEngine,
    StrategyRecommendation,
)

# ---------------------------------------------------------------------------
# P3-1: Integration tests — verify full pipeline produces coherent results
# ---------------------------------------------------------------------------


class TestDecisionIntegration:
    """End-to-end integration tests for the decision engine pipeline."""

    @pytest.fixture
    def engine(self):
        return StockDecisionEngine()

    @pytest.fixture
    def universe_scores(self):
        """A realistic universe of 20 stocks with model scores."""
        instruments = [
            "AAPL", "NVDA", "MSFT", "GOOG", "AMZN", "META", "TSLA", "NFLX",
            "AMD", "INTC", "CRM", "ADBE", "PYPL", "SQ", "SNAP", "UBER",
            "LYFT", "COIN", "RIVN", "LCID",
        ]
        scores = [
            0.62, 0.71, 0.31, 0.18, 0.22, 0.45, -0.15, -0.05,
            0.55, -0.10, 0.28, 0.15, -0.08, 0.05, -0.20, 0.12,
            -0.18, 0.35, -0.25, -0.30,
        ]
        series = pd.Series(scores, index=instruments)
        return series.sort_values(ascending=False)

    @pytest.fixture
    def rank_map(self, universe_scores):
        return {inst: idx for idx, inst in enumerate(universe_scores.index)}

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_buy_signals_have_positive_scores(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails,
        engine, universe_scores, rank_map,
    ):
        """All BUY signals should have positive model scores."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = PriceTargets(
            current_price=100.0, buy_range_low=98.0, buy_range_high=102.0,
            stop_loss_price=95.0, target_price=110.0,
        )

        for symbol in universe_scores.index:
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=universe_scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            if decision.signal == "BUY":
                assert decision.score > 0, f"{symbol} is BUY but score={decision.score}"
                assert decision.confidence > 0.5, f"{symbol} BUY confidence too low: {decision.confidence}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_sell_signals_have_negative_scores_or_risk(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails,
        engine, universe_scores, rank_map,
    ):
        """SELL signals should have negative scores, bottom ranks, or risk flags."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        for symbol in universe_scores.index:
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=universe_scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            if decision.signal == "SELL":
                has_negative = decision.score < 0
                has_bottom_rank = decision.rank is not None and decision.rank >= engine.config["sell_rank_threshold"]
                has_risk = len(decision.risk_flags) > 0
                has_guardrail_fail = not decision.guardrail_status.get("overall_passed", True)
                assert has_negative or has_bottom_rank or has_risk or has_guardrail_fail, \
                    f"{symbol} is SELL but score={decision.score}, rank={decision.rank}, flags={decision.risk_flags}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_buy_signals_have_strategy_recommendation(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails,
        engine, universe_scores, rank_map,
    ):
        """All BUY signals should have a strategy recommendation."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = PriceTargets(current_price=100.0)

        buy_count = 0
        for symbol in universe_scores.index:
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=universe_scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            if decision.signal == "BUY":
                buy_count += 1
                assert decision.recommended_strategy is not None, \
                    f"{symbol} is BUY but has no strategy recommendation"
                assert decision.recommended_strategy.name in (
                    "biweekly_trend", "dual_layer", "weekly_quant_rating"
                )

        assert buy_count > 0, "Expected at least one BUY signal in the test universe"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_buy_signals_have_price_targets(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails,
        engine, universe_scores, rank_map,
    ):
        """All BUY signals should have price targets when available."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = PriceTargets(
            current_price=185.0, buy_range_low=183.0, buy_range_high=187.0,
            stop_loss_price=179.0, target_price=196.0, atr_20=3.5,
        )

        for symbol in universe_scores.index:
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=universe_scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            if decision.signal == "BUY":
                assert decision.price_targets is not None, \
                    f"{symbol} is BUY but has no price targets"
                assert decision.price_targets.stop_loss_price is not None
                assert decision.price_targets.target_price is not None

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_signal_distribution_is_reasonable(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails,
        engine, universe_scores, rank_map,
    ):
        """Signal distribution should be reasonable — not all BUY or all SELL."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        counts = {"BUY": 0, "HOLD": 0, "SELL": 0}
        for symbol in universe_scores.index:
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=universe_scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            counts[decision.signal] += 1

        # Should have at least some of each signal type
        assert counts["BUY"] > 0, f"Expected some BUY signals, got {counts}"
        assert counts["SELL"] > 0, f"Expected some SELL signals, got {counts}"
        # BUY and SELL should each be less than 80% of total
        total = sum(counts.values())
        assert counts["BUY"] / total < 0.8, f"Too many BUY signals: {counts}"
        assert counts["SELL"] / total < 0.8, f"Too many SELL signals: {counts}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_decision_to_dict_is_json_serializable(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails,
        engine, universe_scores, rank_map,
    ):
        """All decision fields should be JSON-serializable."""
        import json

        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = PriceTargets(current_price=100.0, stop_loss_price=95.0)

        for symbol in ["AAPL", "TSLA"]:  # test one BUY and one SELL candidate
            decision = engine.evaluate(
                symbol=symbol,
                pred_score=universe_scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            d = decision.to_dict()
            # Should not raise
            serialized = json.dumps(d, default=str)
            assert len(serialized) > 0


# ---------------------------------------------------------------------------
# P3-3: Consistency tests — decision engine vs BiweeklyTrendStrategy sell rules
# ---------------------------------------------------------------------------


class TestDecisionConsistency:
    """Verify that the decision engine's sell signals are consistent with
    BiweeklyTrendStrategy's sell rules.

    The strategy sells when:
    1. close < MA(sell_ma_window)  (MA cross-under)
    2. rank >= sell_rank_threshold  (rank drop)
    3. score < sell_score_threshold (score threshold)
    4. stop_loss / trailing_stop triggered

    The engine should also return SELL for these conditions.
    """

    @pytest.fixture
    def engine(self):
        return StockDecisionEngine()

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_sell_on_ma_cross_under_consistent(
        self, mock_pt, mock_factors, mock_guardrails, engine,
    ):
        """If close < MA60, both strategy and engine should sell."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        # Mock MA signal returning cross-under
        with patch.object(engine, "_check_ma_signal", return_value="📉 MA60 死叉 — 价格 140.00 < MA60 150.00"):
            scores = pd.Series([0.5], index=["AAPL"])
            rank_map = {"AAPL": 0}

            decision = engine.evaluate(
                symbol="AAPL",
                pred_score=scores,
                rank_map=rank_map,
                market="us",
                include_factors=False,
            )
            assert decision.signal == "SELL", f"Expected SELL on MA cross-under, got {decision.signal}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_sell_on_rank_drop_consistent(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine,
    ):
        """If rank >= sell_rank_threshold, both strategy and engine should sell."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        # Create universe where AAPL is at rank 60 (>= sell_rank_threshold=50)
        instruments = [f"STOCK_{i}" for i in range(60)] + ["AAPL"]
        scores = pd.Series([0.5] * 60 + [0.05], index=instruments)
        rank_map = {inst: idx for idx, inst in enumerate(scores.sort_values(ascending=False).index)}

        decision = engine.evaluate(
            symbol="AAPL",
            pred_score=scores,
            rank_map=rank_map,
            market="us",
            include_factors=False,
        )
        # AAPL should be at the bottom rank
        assert decision.rank is not None and decision.rank >= 50
        assert decision.signal == "SELL", f"Expected SELL for bottom rank, got {decision.signal}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_sell_on_guardrail_failure_consistent(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine,
    ):
        """If guardrails fail, both strategy and engine should not buy."""
        mock_guardrails.return_value = {
            "overall_passed": False,
            "liquidity": {"passed": False, "reason": "Low liquidity", "metric": 500000},
        }
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        scores = pd.Series([0.7], index=["NVDA"])
        rank_map = {"NVDA": 0}

        decision = engine.evaluate(
            symbol="NVDA",
            pred_score=scores,
            rank_map=rank_map,
            market="us",
            include_factors=False,
        )
        assert decision.signal == "SELL", f"Expected SELL on guardrail failure, got {decision.signal}"

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_sell_on_stop_loss_consistent(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine,
    ):
        """If stop-loss is triggered, engine should return SELL."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = None

        scores = pd.Series([0.5], index=["AAPL"])
        rank_map = {"AAPL": 0}

        held_positions = {
            "AAPL": {
                "entry_price": 180.0,
                "current_price": 150.0,  # -16.7% loss, triggers -10% stop
                "peak_price": 190.0,
                "weight": 0.2,
            }
        }

        decision = engine.evaluate(
            symbol="AAPL",
            pred_score=scores,
            rank_map=rank_map,
            market="us",
            held_positions=held_positions,
            include_factors=False,
        )
        assert decision.signal == "SELL"
        assert "stop_loss" in decision.risk_flags

    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_guardrails")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._check_ma_signal")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._analyze_factors")
    @patch("src.strategies.stock_decision_engine.StockDecisionEngine._compute_price_targets")
    def test_buy_requires_positive_score_and_top_rank(
        self, mock_pt, mock_factors, mock_ma, mock_guardrails, engine,
    ):
        """BUY should only occur with positive score AND top rank."""
        mock_guardrails.return_value = {"overall_passed": True}
        mock_ma.return_value = None
        mock_factors.return_value = ({}, [])
        mock_pt.return_value = PriceTargets(current_price=100.0)

        scores = pd.Series([0.5], index=["AAPL"])
        rank_map = {"AAPL": 0}

        decision = engine.evaluate(
            symbol="AAPL",
            pred_score=scores,
            rank_map=rank_map,
            market="us",
            include_factors=False,
        )
        assert decision.signal == "BUY"
        assert decision.score > 0
        assert decision.rank is not None and decision.rank < engine.config["buy_rank_topk"]


# ---------------------------------------------------------------------------
# Data class serialization tests
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify all data classes serialize correctly for API responses."""

    def test_full_decision_serialization(self):
        """A fully populated StockDecision should serialize without errors."""
        import json

        rec = StrategyRecommendation("dual_layer", "Dual Layer", "test reason", 0.85)
        pt = PriceTargets(
            current_price=185.5, buy_range_low=183.0, buy_range_high=188.0,
            stop_loss_price=178.0, target_price=197.0, atr_20=3.5,
            support=180.0, resistance=192.0,
        )
        decision = StockDecision(
            symbol="AAPL",
            signal="BUY",
            confidence=0.78,
            score=0.62,
            rank=2,
            reasons=["✅ 模型分数 +0.6200 为正", "📋 推荐策略: Dual Layer"],
            factor_snapshot={"mom_20d": {
                "name": "mom_20d", "expression": "$close/Ref($close,20)-1",
                "value": 0.12, "z_score": 1.8, "percentile": 92.0, "category": "momentum",
            }},
            guardrail_status={
                "overall_passed": True,
                "extension": {"passed": True, "metric": 0.08},
                "liquidity": {"passed": True, "metric": 2100000000},
            },
            risk_flags=[],
            timestamp="2026-06-17",
            recommended_strategy=rec,
            price_targets=pt,
        )

        d = decision.to_dict()
        serialized = json.dumps(d, default=str)
        parsed = json.loads(serialized)

        assert parsed["symbol"] == "AAPL"
        assert parsed["signal"] == "BUY"
        assert parsed["recommended_strategy"]["name"] == "dual_layer"
        assert parsed["price_targets"]["stop_loss_price"] == 178.0
        assert len(parsed["reasons"]) == 2
