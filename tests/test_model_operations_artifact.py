"""Tests for Model Operations artifact and read model (T47.8)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.artifacts.model_operations import (
    ModelOperationsError,
    SCHEMA_VERSION,
    build_market_operations_snapshot,
    build_model_operations_payload,
    validate_model_operations_payload,
    write_model_operations_payload,
)
from src.portfolio.operations_gates import GateFacts


def test_build_model_operations_payload_defaults() -> None:
    payload = build_model_operations_payload(asof_date="2026-09-18")
    assert payload.schema_version == SCHEMA_VERSION
    assert payload.research_only is True
    assert payload.trade_ready is False
    assert payload.markets == []
    as_dict = payload.to_dict()
    assert as_dict["digest"] != ""
    validate_model_operations_payload(as_dict)


def test_validate_model_operations_payload_rejects_invalid() -> None:
    payload = build_model_operations_payload().to_dict()

    # Reject trade_ready = True
    invalid_trade = dict(payload)
    invalid_trade["trade_ready"] = True
    with pytest.raises(ModelOperationsError, match="trade_ready must be false"):
        validate_model_operations_payload(invalid_trade)

    # Reject unsupported schema
    invalid_schema = dict(payload)
    invalid_schema["schema_version"] = "v0"
    with pytest.raises(ModelOperationsError, match="Unsupported schema_version"):
        validate_model_operations_payload(invalid_schema)

    # Reject missing markets
    invalid_markets = dict(payload)
    invalid_markets["markets"] = "invalid"
    with pytest.raises(ModelOperationsError, match="markets must be a list"):
        validate_model_operations_payload(invalid_markets)


def test_write_model_operations_payload_roundtrip(tmp_path: Path) -> None:
    payload = build_model_operations_payload(asof_date="2026-09-18")
    out_file = tmp_path / "model_operations" / "operations_summary.json"
    written = write_model_operations_payload(payload, out_file)
    assert written.exists()

    loaded = json.loads(written.read_text(encoding="utf-8"))
    validate_model_operations_payload(loaded)
    assert loaded["schema_version"] == SCHEMA_VERSION
    assert loaded["markets"] == []


def test_fail_closed_gate_when_drift_critical() -> None:
    # Severe drift scenario
    critical_facts = GateFacts(
        data_freshness_status="current",
        data_age_days=1.0,
        artifact_status="verified",
        previous_verified_champion_id="previous_verified",
        current_drawdown=-0.05,
        risk_limit_breached=False,
        signal_qualified=True,
        signal_sample_count=50,
        drift_severity="critical",
        paper_excess_return=-0.05,
    )
    snap = build_market_operations_snapshot("us", gate_facts=critical_facts)
    assert snap.gate_decision["decision"] in ("demote", "rollback", "retrain", "stop")
    assert snap.gate_decision["plan_eligible"] is False
    # When plan_eligible is False, no active execution plan should be materialized
    assert snap.execution_plan is None


def test_missing_inputs_do_not_create_orders_or_passing_metrics(tmp_path: Path, monkeypatch) -> None:
    import src.artifacts.model_operations as module
    def forbidden(*args, **kwargs):
        raise AssertionError("read model must not construct a paper ledger")
    monkeypatch.setattr(module, "PaperTradingLedger", forbidden)
    snapshot = build_market_operations_snapshot("us")
    assert snapshot.champion is None
    assert snapshot.challenger is None
    assert snapshot.execution_plan is None
    assert snapshot.gate_decision["plan_eligible"] is False
    assert snapshot.drift["checks"] == []
    assert snapshot.paper_ledger["availability_status"] == "absent"
    assert snapshot.attribution["availability_status"] == "absent"
