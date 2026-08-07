from __future__ import annotations

import json
from pathlib import Path

from src.artifacts.strategy_operations import (
    BYD_MODEL,
    QQQ_MODEL,
    build_operations_payload,
    validate_operations_payload,
)
from src.artifacts.strategy_signal_ledger import append_signal_evaluation

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")


def _by_model(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    records = payload["records"]
    assert isinstance(records, list)
    return {str(row["model_version_id"]): row for row in records}


def _qqq_signal(*, changed: bool = True) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "experiment_id": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
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
        "price_context": {"qqq_vs_ma20": 0.01},
        "volatility_context": {
            "vix_close": 16.0,
            "vix_retreat_from_peak": -0.10,
            "vxn_close": 24.0,
            "vxn_retreat_from_peak": -0.08,
        },
    }


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
    assert set(observed) == expected
    assert observed[QQQ_MODEL]["status"] == "awaiting_observation"
    assert observed[BYD_MODEL]["status"] == "awaiting_observation"
    assert observed["us_x1_1"]["status"] == "pipeline_unavailable"
    assert observed["cn_x1_1"]["status"] == "pipeline_unavailable"


def test_qqq_ledger_projects_to_current_target_snapshot(tmp_path: Path) -> None:
    ledger = tmp_path / QQQ_MODEL
    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=QQQ_MODEL,
        signal=_qqq_signal(),
        delivery_status="sent",
        github_issue_number=493,
        telegram_message_id=42,
        workflow_run_id="12345",
        commit_sha="a" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
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
    allocations = qqq["allocations"]
    assert isinstance(allocations, list)
    assert {row["asset"] for row in allocations} == {"QQQI", "QQQ", "TQQQ"}


def test_no_change_and_delivery_failure_are_distinct(tmp_path: Path) -> None:
    ledger = tmp_path / QQQ_MODEL
    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=QQQ_MODEL,
        signal=_qqq_signal(changed=False),
        delivery_status="not_required",
        workflow_run_id="12345",
        commit_sha="b" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:01Z",
    )
    assert _by_model(payload)[QQQ_MODEL]["status"] == "current_no_change"

    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=QQQ_MODEL,
        signal={**_qqq_signal(), "fingerprint": "qqq-failed-delivery"},
        delivery_status="failed",
        delivery_error="telegram_api_rejected",
        workflow_run_id="12346",
        commit_sha="c" * 40,
        created_at_utc="2026-08-08T00:00:02Z",
    )
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:03Z",
    )
    assert _by_model(payload)[QQQ_MODEL]["status"] == "delivery_failed"


def test_tampered_signal_fails_closed_in_operations_read_model(tmp_path: Path) -> None:
    ledger = tmp_path / QQQ_MODEL
    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=QQQ_MODEL,
        signal=_qqq_signal(),
        delivery_status="sent",
        workflow_run_id="12345",
        commit_sha="d" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )
    latest = json.loads((ledger / "latest.json").read_text(encoding="utf-8"))
    latest["signal"]["target_weights"]["QQQ"] = 0.4
    (ledger / "latest.json").write_text(json.dumps(latest), encoding="utf-8")

    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:01Z",
    )
    qqq = _by_model(payload)[QQQ_MODEL]
    assert qqq["status"] == "blocked"
    assert "digest mismatch" in str(qqq["decision_reason"])
