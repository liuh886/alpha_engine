from __future__ import annotations

import json
from pathlib import Path

from src.artifacts.strategy_operations import build_operations_payload, validate_operations_payload
from src.artifacts.strategy_signal_ledger import append_signal_evaluation

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")
QQQ_MODEL = "qqqi_qqq_tqqq_v4_2"
QQQ_V43_MODEL = "qqqi_qqq_tqqq_v4_3"
BYD_MODEL = "byd_v1_2_convex_momentum_budget_v1"


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


def _v43_signal() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "model_id": QQQ_V43_MODEL,
        "research_only": True,
        "trade_ready": False,
        "should_alert": True,
        "fingerprint": "qqq-v43-test-fingerprint",
        "signal_date": "2026-08-07",
        "latest_data_date": "2026-08-07",
        "data_freshness_ok": True,
        "execution_time": "next_session_open",
        "current_formal_state": 0,
        "target_formal_state": 0,
        "current_overlay": "strong_defense",
        "target_overlay": "base",
        "current_weights": {"QQQI": 0.5, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.5},
        "target_weights": {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0},
        "turnover_units": 1.0,
        "estimated_transaction_cost": 0.001,
        "panic_repair_active": False,
        "strong_defense": False,
        "ma200_falling": True,
        "fast_price_vol_repair": True,
        "rsi_14": 44.2,
        "fear_greed_score": 38.0,
        "context": {
            "qqq_close": 710.0,
            "ma20": 705.0,
            "ma200": 640.0,
            "vix_close": 16.2,
            "vxn_close": 24.1,
        },
    }


def _catalog_with_v43(tmp_path: Path) -> Path:
    payload = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    for record in payload["records"]:
        if record["model_family_id"] != "qqq_rotation":
            continue
        record["model_version_id"] = QQQ_V43_MODEL
        record["run_id"] = "qqqi_qqq_tqqq_v4_3-promotion-test"
        record["manifest_path"] = (
            "qqq_rotation/qqqi_qqq_tqqq_v4_3/"
            "qqqi_qqq_tqqq_v4_3-promotion-test/manifest.json"
        )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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


def test_qqq_family_adapter_accepts_new_formal_version_without_version_branch(tmp_path: Path) -> None:
    catalog = _catalog_with_v43(tmp_path)
    ledger_root = tmp_path / "ledgers"
    append_signal_evaluation(
        ledger_root=ledger_root / QQQ_V43_MODEL,
        model_version_id=QQQ_V43_MODEL,
        signal=_v43_signal(),
        delivery_status="sent",
        workflow_run_id="54321",
        commit_sha="e" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )

    payload = build_operations_payload(
        formal_catalog=catalog,
        ledger_root=ledger_root,
        generated_at="2026-08-08T00:00:01Z",
    )
    qqq = _by_model(payload)[QQQ_V43_MODEL]
    assert qqq["status"] == "target_pending_execution"
    assert qqq["factor_freshness"] == "current"
    assert "SGOV" in {row["asset"] for row in qqq["allocations"]}
    assert "base" in str(qqq["state_label"])
    assert {row["label"] for row in qqq["drivers"]} >= {"RSI(14)", "Strong defense"}


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
