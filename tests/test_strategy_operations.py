from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.strategy_operations import (
    build_operations_payload,
    validate_operations_payload,
    write_operations_payload,
)
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    record_signal_delivery,
    seal_signal_decision,
)
from src.factors.library import load_factor_library
from src.factors.ranker_snapshot import build_ranker_factor_snapshot
from src.factors.strategy_snapshot import build_strategy_factor_snapshot

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")
FACTOR_LIBRARY = Path("configs/factor_libraries/ohlcv.yaml")
QQQ_MODEL = "qqqi_qqq_tqqq_v4_3"
BYD_MODEL = "byd_v1_3_recovery_event_low_vol_confirmation_v1"
US_MODEL = "us_x1_3"
CN_MODEL = "cn_x1_1"


def _by_model(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    records = payload["records"]
    assert isinstance(records, list)
    return {str(row["model_version_id"]): row for row in records}


def _factorized(signal: dict[str, object], family: str) -> dict[str, object]:
    factor_evidence = build_strategy_factor_snapshot(
        model_family_id=family,
        signal=signal,
    )
    return {
        **signal,
        "factor_evidence": factor_evidence,
        "factor_freshness_ok": factor_evidence["freshness"] == "current",
    }


def _qqq_signal(*, changed: bool = True) -> dict[str, object]:
    signal: dict[str, object] = {
        "schema_version": "2.0",
        "model_id": QQQ_MODEL,
        "research_only": True,
        "trade_ready": False,
        "should_alert": changed,
        "fingerprint": "qqq-test-fingerprint",
        "signal_date": "2026-08-07",
        "latest_data_date": "2026-08-07",
        "data_freshness_ok": True,
        "execution_time": "next_session_open",
        "current_state": 0,
        "target_state": 1 if changed else 0,
        "current_weights": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
        "target_weights": (
            {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0}
            if changed
            else {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0}
        ),
        "turnover_units": 1.0 if changed else 0.0,
        "estimated_transaction_cost": 0.001 if changed else 0.0,
        "decision_reason": "enter_qqq_early_repair_vix_easing" if changed else "hold",
        "decision_reason_label": "QQQ repair with easing volatility" if changed else "Hold",
        "price_context": {
            "qqq_vs_ma20": 0.01,
            "qqq_vs_ma200": 0.10,
            "stress_price_failure": False,
            "long_break": False,
        },
        "volatility_context": {
            "vix_close": 16.0,
            "vix_q_normal": 18.0,
            "vix_q_stress": 22.0,
            "vix_regime": "calm",
            "vix_stress": False,
            "vix_easing": True,
            "vix_normalized": True,
            "vxn_close": 24.0,
            "vxn_q_normal": 25.0,
            "vxn_q_stress": 29.0,
            "vxn_regime": "calm",
            "vxn_stress": False,
        },
    }
    return _factorized(signal, "qqq_rotation")


def _ranker_signal(
    *,
    family: str,
    group: str,
    current: dict[str, float],
    target: dict[str, float],
    risk_on: bool | None = None,
) -> dict[str, object]:
    factors = load_factor_library(FACTOR_LIBRARY).factors_for_groups([group])
    factor_evidence = build_ranker_factor_snapshot(
        model_family_id=family,
        signal_date="2026-08-07",
        latest_data_date="2026-08-07",
        factor_values={
            definition.factor_id: float(index + 1) / 100.0
            for index, definition in enumerate(factors)
        },
        factor_references={},
        data_freshness_ok=True,
    )
    changed = current != target
    return {
        "model_family_id": family,
        "research_only": True,
        "trade_ready": False,
        "should_alert": changed,
        "fingerprint": f"{family}-test-fingerprint",
        "signal_date": "2026-08-07",
        "latest_data_date": "2026-08-07",
        "data_freshness_ok": True,
        "current_weights": current,
        "target_weights": target,
        "turnover_units": 0.5 if changed else 0.0,
        "estimated_transaction_cost": 0.001 if changed else 0.0,
        "reason_code": f"{family}_10_session_rebalance",
        "diagnostics": ({"risk_on": risk_on} if risk_on is not None else {}),
        "factor_evidence": factor_evidence,
        "factor_freshness_ok": True,
    }


def _seal_and_deliver(
    ledger: Path,
    model: str,
    signal: dict[str, object],
    *,
    delivery_status: str = "sent",
    github_issue_number: int | None = None,
    telegram_message_id: int | None = None,
) -> None:
    seal_signal_decision(
        ledger_root=ledger,
        model_version_id=model,
        signal=signal,
        workflow_run_id="seal-12345",
        commit_sha="a" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )
    record_signal_delivery(
        ledger_root=ledger,
        model_version_id=model,
        signal=signal,
        delivery_status=delivery_status,
        github_issue_number=github_issue_number,
        telegram_message_id=telegram_message_id,
        workflow_run_id="delivery-12345",
        commit_sha="b" * 40,
        created_at_utc="2026-08-08T00:00:01Z",
    )


def test_formal_catalog_drives_exact_operations_membership(tmp_path: Path) -> None:
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:00Z",
    )
    validate_operations_payload(payload)
    observed = _by_model(payload)
    formal = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    expected = {row["model_version_id"] for row in formal["records"]}
    assert payload["schema_version"] == "2.2.0"
    assert set(observed) == expected
    assert {str(row["strategy_id"]) for row in observed.values()} == {
        "qqq_rotation",
        "us_x",
        "cn_x",
        "byd",
    }
    assert all("current_operations_access" not in row for row in observed.values())
    assert all(row["status"] == "awaiting_observation" for row in observed.values())
    assert observed[US_MODEL]["decision_cadence"] == "Every 10 provider sessions"
    assert observed[CN_MODEL]["decision_cadence"] == "Every 10 provider sessions"
    assert observed[CN_MODEL]["model_version_id"] == "cn_x1_1"
    assert "cn_x1_2" not in observed


def test_ranker_ledgers_project_current_targets(tmp_path: Path) -> None:
    _seal_and_deliver(
        tmp_path / US_MODEL,
        US_MODEL,
        _ranker_signal(
            family="us_ranker",
            group="momentum_volatility_volume",
            current={"A": 1.0},
            target={"A": 0.5, "B": 0.5},
        ),
    )
    _seal_and_deliver(
        tmp_path / CN_MODEL,
        CN_MODEL,
        _ranker_signal(
            family="cn_ranker",
            group="cn_balanced_ohlcv",
            current={"000300": 1.0},
            target={"000001": 0.25, "000002": 0.25, "000003": 0.25, "000004": 0.25},
            risk_on=True,
        ),
    )
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:01Z",
    )
    records = _by_model(payload)
    us = records[US_MODEL]
    cn = records[CN_MODEL]
    assert us["status"] == "target_pending_execution"
    assert us["state_label"] == "US Top-15 rebalance"
    assert us["factor_freshness"] == "current"
    assert us["delivery_status"] == "sent"
    assert cn["status"] == "target_pending_execution"
    assert cn["state_label"] == "CN risk-on · sector 4×1"
    assert cn["factor_freshness"] == "current"


def test_qqq_ledger_projects_canonical_factor_snapshot(tmp_path: Path) -> None:
    ledger = tmp_path / QQQ_MODEL
    _seal_and_deliver(
        ledger,
        QQQ_MODEL,
        _qqq_signal(),
        github_issue_number=493,
        telegram_message_id=42,
    )
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:01Z",
    )
    qqq = _by_model(payload)[QQQ_MODEL]
    assert qqq["status"] == "target_pending_execution"
    assert qqq["data_freshness"] == "current"
    assert qqq["factor_freshness"] == "current"
    assert qqq["delivery_status"] == "sent"
    assert qqq["source_href"] == "https://github.com/liuh886/alpha_engine/issues/493"
    factors = qqq["factor_evidence"]
    assert isinstance(factors, list)
    assert {row["factor_id"] for row in factors} == {
        "strategy.qqq.vix_close",
        "strategy.qqq.vxn_close",
        "strategy.qqq.qqq_vs_ma20",
        "strategy.qqq.qqq_vs_ma200",
    }


def test_new_ledger_write_rejects_missing_factor_evidence(tmp_path: Path) -> None:
    signal = _qqq_signal()
    signal.pop("factor_evidence")
    signal.pop("factor_freshness_ok")
    with pytest.raises(StrategySignalLedgerError, match="factor evidence"):
        seal_signal_decision(
            ledger_root=tmp_path / QQQ_MODEL,
            model_version_id=QQQ_MODEL,
            signal=signal,
            workflow_run_id="seal-12345",
            commit_sha="a" * 40,
            created_at_utc="2026-08-08T00:00:00Z",
        )


def test_operations_payload_write_is_idempotent(tmp_path: Path) -> None:
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    output = tmp_path / "operations.json"
    assert write_operations_payload(output, payload) is True
    assert write_operations_payload(output, payload) is False


def test_generated_operations_identity_matches_formal_bundle_catalog(tmp_path: Path) -> None:
    formal = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    operations = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    formal_by_id = {row["model_version_id"]: row for row in formal["records"]}
    operation_by_id = {row["model_version_id"]: row for row in operations["records"]}
    assert set(operation_by_id) == set(formal_by_id)
    for model_id, record in operation_by_id.items():
        catalog_record = formal_by_id[model_id]
        identity = record["source_identity"]
        assert identity["formal_bundle_id"] == catalog_record["bundle_id"]
        assert identity["formal_run_id"] == catalog_record["run_id"]
        assert identity["formal_evidence_cutoff"] == catalog_record["evidence_cutoff"]
