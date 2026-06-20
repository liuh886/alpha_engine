from __future__ import annotations

import json

from src.execution.engine import StrategyExecutionEngine
from src.execution.models import (
    ExecutionConfig,
    ExecutionRequest,
    MarketDataSnapshot,
    OrderSide,
    PortfolioState,
    RiskPolicy,
    SignalFrame,
)


def test_execution_result_is_json_serializable_and_stable():
    request = ExecutionRequest(
        signals=SignalFrame(
            asof_date="2026-06-19",
            scores={"AAA": 0.8, "BBB": 0.4, "CCC": 0.2},
        ),
        portfolio=PortfolioState(cash=1000.0, positions={"CCC": 0.15}),
        market=MarketDataSnapshot(tradable={"AAA": True, "BBB": True, "CCC": True}),
        risk_policy=RiskPolicy(max_position_weight=0.2),
        config=ExecutionConfig(topk=2),
    )

    result = StrategyExecutionEngine().execute(request)

    assert result.plan.target_weights == {"AAA": 0.2, "BBB": 0.2}
    assert {(order.instrument, order.side) for order in result.orders} == {
        ("AAA", OrderSide.BUY),
        ("BBB", OrderSide.BUY),
        ("CCC", OrderSide.SELL),
    }
    assert result.risk_violations == []
    json.dumps(result.to_dict())


def test_execution_engine_respects_tradability_and_topk():
    request = ExecutionRequest(
        signals=SignalFrame(
            asof_date="2026-06-19",
            scores={"AAA": 0.9, "BBB": 0.8, "CCC": 0.7},
        ),
        portfolio=PortfolioState(cash=1000.0),
        market=MarketDataSnapshot(tradable={"AAA": False, "BBB": True, "CCC": True}),
        risk_policy=RiskPolicy(max_position_weight=0.15),
        config=ExecutionConfig(topk=1),
    )

    result = StrategyExecutionEngine().execute(request)

    assert result.plan.target_weights == {"BBB": 0.15}
    assert len(result.orders) == 1
    assert result.orders[0].instrument == "BBB"


def test_execution_engine_reports_short_position_violation():
    request = ExecutionRequest(
        signals=SignalFrame(asof_date="2026-06-19", scores={"AAA": 1.0}),
        portfolio=PortfolioState(cash=1000.0, positions={"SHORT": -0.1}),
        market=MarketDataSnapshot(),
        risk_policy=RiskPolicy(allow_shorts=False),
    )

    result = StrategyExecutionEngine().execute(request)

    assert any(v.code == "short_position" for v in result.risk_violations)


# ---------------------------------------------------------------------------
# H4: Golden harness — deterministic fixtures for reproducible execution tests
# ---------------------------------------------------------------------------


# Canonical fixtures: scores, positions, tradability, risk config
GOLDEN_SCORES = {"TOP_A": 0.95, "TOP_B": 0.80, "TOP_C": 0.60, "MID_D": 0.40, "LOW_E": 0.10}
GOLDEN_POSITIONS = {"TOP_A": 0.10, "OLD_F": 0.15}  # OLD_F not in signals → should be sold
GOLDEN_TRADABLE = {k: True for k in GOLDEN_SCORES}
GOLDEN_TRADABLE["OLD_F"] = True
GOLDEN_RISK = RiskPolicy(max_position_weight=0.20, allow_shorts=False)
GOLDEN_CONFIG = ExecutionConfig(topk=3, rebalance=True)


class TestExecutionGoldenHarness:
    """Golden tests: deterministic inputs → deterministic outputs."""

    def test_golden_topk_selection(self):
        """Top-3 by score should be TOP_A, TOP_B, TOP_C with equal weights."""
        request = ExecutionRequest(
            signals=SignalFrame(asof_date="2026-06-19", scores=GOLDEN_SCORES),
            portfolio=PortfolioState(cash=1.0),
            market=MarketDataSnapshot(tradable=GOLDEN_TRADABLE),
            risk_policy=GOLDEN_RISK,
            config=GOLDEN_CONFIG,
        )
        result = StrategyExecutionEngine().execute(request)

        # Exactly 3 positions
        assert len(result.plan.target_weights) == 3
        # Correct instruments
        assert set(result.plan.target_weights.keys()) == {"TOP_A", "TOP_B", "TOP_C"}
        # Each weight ≤ max_position_weight (0.20)
        for w in result.plan.target_weights.values():
            assert w <= 0.20 + 1e-9

    def test_golden_sell_unscored_position(self):
        """OLD_F has no score → should generate a SELL order."""
        request = ExecutionRequest(
            signals=SignalFrame(asof_date="2026-06-19", scores=GOLDEN_SCORES),
            portfolio=PortfolioState(cash=1.0, positions=GOLDEN_POSITIONS),
            market=MarketDataSnapshot(tradable=GOLDEN_TRADABLE),
            risk_policy=GOLDEN_RISK,
            config=GOLDEN_CONFIG,
        )
        result = StrategyExecutionEngine().execute(request)

        sell_instruments = {o.instrument for o in result.orders if o.side == OrderSide.SELL}
        assert "OLD_F" in sell_instruments

    def test_golden_tradability_blocks_buy(self):
        """Untradable instrument should be excluded from target weights."""
        tradable = dict(GOLDEN_TRADABLE)
        tradable["TOP_A"] = False  # Block top scorer

        request = ExecutionRequest(
            signals=SignalFrame(asof_date="2026-06-19", scores=GOLDEN_SCORES),
            portfolio=PortfolioState(cash=1.0),
            market=MarketDataSnapshot(tradable=tradable),
            risk_policy=GOLDEN_RISK,
            config=GOLDEN_CONFIG,
        )
        result = StrategyExecutionEngine().execute(request)

        assert "TOP_A" not in result.plan.target_weights
        # TOP_B, TOP_C, MID_D should be selected (next 3 by score)
        assert set(result.plan.target_weights.keys()) == {"TOP_B", "TOP_C", "MID_D"}

    def test_golden_deterministic_output(self):
        """Same inputs must produce identical outputs across runs."""
        request = ExecutionRequest(
            signals=SignalFrame(asof_date="2026-06-19", scores=GOLDEN_SCORES),
            portfolio=PortfolioState(cash=1.0, positions=GOLDEN_POSITIONS),
            market=MarketDataSnapshot(tradable=GOLDEN_TRADABLE),
            risk_policy=GOLDEN_RISK,
            config=GOLDEN_CONFIG,
        )

        result1 = StrategyExecutionEngine().execute(request)
        result2 = StrategyExecutionEngine().execute(request)

        assert result1.plan.target_weights == result2.plan.target_weights
        assert len(result1.orders) == len(result2.orders)
        for o1, o2 in zip(result1.orders, result2.orders):
            assert o1.instrument == o2.instrument
            assert o1.side == o2.side
            assert abs(o1.target_weight - o2.target_weight) < 1e-10

    def test_golden_json_roundtrip(self):
        """Execution result must survive JSON serialization."""
        import json

        request = ExecutionRequest(
            signals=SignalFrame(asof_date="2026-06-19", scores=GOLDEN_SCORES),
            portfolio=PortfolioState(cash=1.0, positions=GOLDEN_POSITIONS),
            market=MarketDataSnapshot(tradable=GOLDEN_TRADABLE),
            risk_policy=GOLDEN_RISK,
            config=GOLDEN_CONFIG,
        )
        result = StrategyExecutionEngine().execute(request)

        serialized = json.dumps(result.to_dict())
        deserialized = json.loads(serialized)

        assert deserialized["plan"]["target_weights"] == {
            k: round(v, 6) for k, v in result.plan.target_weights.items()
        }
        assert len(deserialized["orders"]) == len(result.orders)
