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
    assert len(payload.markets) == 2

    markets = {m.market: m for m in payload.markets}
    assert "us" in markets
    assert "cn" in markets

    us = markets["us"]
    assert us.champion is not None
    assert us.champion["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    assert us.drift["overall_severity"] == "ok"
    assert us.gate_decision["decision"] == "continue"
    assert us.gate_decision["plan_eligible"] is True
    assert us.execution_plan is not None
    assert us.paper_ledger["hash_chain_verified"] is True
    assert us.attribution["reconciliation"]["within_tolerance"] is True

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
    assert len(loaded["markets"]) == 2


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
