"""T47.8 Operator End-to-End Proof and Fail-Closed Verification.

Demonstrates T47 hard exit criteria across enabled markets (US and CN):
1. Happy path: evidence-backed Champion -> constrained ExecutionPlan -> replayable PaperLedger -> drift monitoring -> operational gate 'continue' with plan_eligible=True.
2. Data freshness failure: stale data fails closed, plan_eligible=False, execution plan blocked.
3. Statistical drift circuit breaker: critical drift triggers demote/retrain gate, blocks plan generation.
4. Risk stop gate: severe drawdown triggers stop decision with hard blocks.
5. Paper ledger tampering: hash chain detects tampering and raises PaperLedgerError.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
import pytest

from src.artifacts.model_operations import (
    build_market_operations_snapshot,
    build_model_operations_payload,
    validate_model_operations_payload,
    write_model_operations_payload,
)
from src.portfolio.attribution import AttributionObservation, PaperPerformanceAttributor
from src.portfolio.construction import (
    ConstructionConstraints,
    PortfolioConstructor,
    QualifiedSignal,
)
from src.portfolio.operations_gates import (
    GateFacts,
    OperationalGatePolicy,
    OperationsGateEngine,
)
from src.portfolio.paper_ledger import (
    OrderSide,
    PaperLedgerError,
    PaperOrderRequest,
    PaperTradingLedger,
)


def test_t47_happy_path_us_and_cn() -> None:
    """Demonstrates full operational loop passing with mathematical reconciliation."""
    payload = build_model_operations_payload(asof_date="2026-09-18")
    assert payload.research_only is True
    assert payload.trade_ready is False

    for m in payload.markets:
        # 1. Champion is evidence-backed
        assert m.champion is not None
        assert m.champion["model_version_id"] in ("qqqi_qqq_tqqq_v4_3", "cn_x1_2")
        assert m.champion["metrics"]["excess_return_with_cost"] > 0

        # 2. Drift is OK
        assert m.drift["overall_severity"] == "ok"

        # 3. Gate decision is continue
        assert m.gate_decision["decision"] == "continue"
        assert m.gate_decision["plan_eligible"] is True

        # 4. Constrained execution plan produced
        assert m.execution_plan is not None
        assert m.execution_plan["advisory_only"] is True
        assert m.execution_plan["cash_weight"] >= 0.05
        assert m.execution_plan["gross_exposure"] <= 0.95

        # 5. Paper ledger hash chain verified
        assert m.paper_ledger["hash_chain_verified"] is True
        assert m.paper_ledger["current_nav"] > 0

        # 6. Performance attribution reconciles within tolerance
        assert m.attribution["reconciliation"]["within_tolerance"] is True


def test_t47_stale_data_gate_blocks_plan() -> None:
    """Proves stale market data fails closed and halts execution plan generation."""
    stale_facts = GateFacts(
        data_freshness_status="stale",
        data_age_days=14.0,  # exceeds max_data_age_days (3.0) and escalation (10.0)
        artifact_status="verified",
        previous_verified_champion_id="prev_champ",
        current_drawdown=-0.04,
        risk_limit_breached=False,
        signal_qualified=True,
        signal_sample_count=100,
        drift_severity="ok",
        paper_excess_return=0.03,
    )
    snap = build_market_operations_snapshot("us", gate_facts=stale_facts)

    assert snap.gate_decision["decision"] in ("demote", "retrain", "stop")
    assert snap.gate_decision["plan_eligible"] is False
    # Crucial operator proof: when gate blocks, execution_plan is explicitly None
    assert snap.execution_plan is None


def test_t47_drift_circuit_breaker_triggers() -> None:
    """Proves critical statistical drift triggers gate circuit breaker and halts plan."""
    drift_facts = GateFacts(
        data_freshness_status="current",
        data_age_days=1.0,
        artifact_status="verified",
        previous_verified_champion_id="prev_champ",
        current_drawdown=-0.05,
        risk_limit_breached=False,
        signal_qualified=True,
        signal_sample_count=100,
        drift_severity="critical",
        paper_excess_return=-0.04,
    )
    snap = build_market_operations_snapshot("cn", gate_facts=drift_facts)

    assert snap.gate_decision["decision"] in ("demote", "retrain", "stop")
    assert snap.gate_decision["plan_eligible"] is False
    assert snap.execution_plan is None


def test_t47_severe_drawdown_hard_stop() -> None:
    """Proves severe drawdown breaches stop threshold and triggers immediate halt."""
    stop_facts = GateFacts(
        data_freshness_status="current",
        data_age_days=1.0,
        artifact_status="verified",
        previous_verified_champion_id=None,
        current_drawdown=-0.28,  # worse than drawdown_stop_threshold (-0.25)
        risk_limit_breached=True,
        signal_qualified=True,
        signal_sample_count=100,
        drift_severity="ok",
        paper_excess_return=-0.12,
    )
    snap = build_market_operations_snapshot("us", gate_facts=stop_facts)

    assert snap.gate_decision["decision"] == "stop"
    assert snap.gate_decision["plan_eligible"] is False
    assert snap.execution_plan is None


def test_t47_paper_ledger_tamper_detection(tmp_path: Path) -> None:
    """Proves hash chain detects file tampering and fails closed with PaperLedgerError."""
    ledger_file = tmp_path / "paper_tamper_test.jsonl"
    ledger = PaperTradingLedger(ledger_file, starting_cash=100_000.0)

    order = PaperOrderRequest(
        client_order_id="order_t1",
        instrument="AAPL",
        side=OrderSide.BUY,
        quantity=50.0,
        decision_date="2026-09-18",
    )
    ledger.submit(order, plan_id="p1", model_version_id="mv1", data_snapshot_id="s1")
    ledger.settle(order.client_order_id, trade_date="2026-09-18", reference_price=200.0)

    # Clean verification passes
    ledger.verify()

    # Tamper with the persisted file by replacing instrument
    content = ledger_file.read_text(encoding="utf-8")
    tampered_content = content.replace('"AAPL"', '"MSFT"')
    assert tampered_content != content
    ledger_file.write_text(tampered_content, encoding="utf-8")

    # Reload ledger: must fail closed immediately during __init__ / load
    with pytest.raises(PaperLedgerError, match="persisted ledger hash chain is broken"):
        PaperTradingLedger(ledger_file, starting_cash=100_000.0)
