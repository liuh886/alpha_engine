"""Fail-closed shared research gates and paper-ledger integrity checks.

These test reusable research components, not the active five-strategy daily loop.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from src.portfolio.operations_gates import (
    GateFacts,
    OperationsGateEngine,
)
from src.portfolio.paper_ledger import (
    OrderSide,
    PaperLedgerError,
    PaperOrderRequest,
    PaperTradingLedger,
)


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
    decision = OperationsGateEngine().evaluate(
        market="us", model_version_id="fixture-model", facts=stale_facts
    )

    assert decision.decision in ("demote", "retrain", "stop")
    assert decision.plan_eligible is False
    assert decision.hard_blocks


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
    decision = OperationsGateEngine().evaluate(
        market="cn", model_version_id="fixture-model", facts=drift_facts
    )

    assert decision.decision in ("demote", "retrain", "stop")
    assert decision.plan_eligible is False
    assert decision.hard_blocks


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
    decision = OperationsGateEngine().evaluate(
        market="us", model_version_id="fixture-model", facts=stop_facts
    )

    assert decision.decision == "stop"
    assert decision.plan_eligible is False
    assert decision.hard_blocks


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
