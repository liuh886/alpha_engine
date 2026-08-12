from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.strategy_operations import (
    StrategyOperationsError,
    build_operations_payload,
    validate_operations_payload,
    write_operations_payload,
)
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    append_signal_evaluation,
)
from src.factors.library import load_factor_library
from src.factors.ranker_snapshot import build_ranker_factor_snapshot
from src.factors.strategy_snapshot import build_strategy_factor_snapshot

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")
FACTOR_LIBRARY = Path("configs/factor_libraries/ohlcv.yaml")
QQQ_MODEL = "qqqi_qqq_tqqq_v4_3"
QQQ_V43_MODEL = "qqqi_qqq_tqqq_v4_3"
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
        "decision_reason": (
            "enter_qqq_early_repair_vix_easing" if changed else "hold"
        ),
        "decision_reason_label": (
            "QQQ repair with easing volatility" if changed else "Hold"
        ),
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


def _v43_signal() -> dict[str, object]:
    signal: dict[str, object] = {
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
        "current_weights": {
            "QQQI": 0.5,
            "QQQ": 0.0,
            "TQQQ": 0.0,
            "SGOV": 0.5,
        },
        "target_weights": {
            "QQQI": 0.5,
            "QQQ": 0.5,
            "TQQQ": 0.0,
            "SGOV": 0.0,
        },
        "turnover_units": 1.0,
        "estimated_transaction_cost": 0.001,
        "panic_repair_active": False,
        "strong_defense": False,
        "ma200_falling": True,
        "fast_price_vol_repair": True,
        "rsi_14": 44.2,
        "fear_greed_score": 38.0,
        "price_context": {
            "qqq_vs_ma20": 710.0 / 705.0 - 1.0,
            "qqq_vs_ma200": 710.0 / 640.0 - 1.0,
            "stress_price_failure": False,
            "long_break": False,
        },
        "context": {
            "qqq_close": 710.0,
            "ma20": 705.0,
            "ma200": 640.0,
            "vix_close": 16.2,
            "vxn_close": 24.1,
            "vix_easing": True,
            "vix_normalized": True,
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
    library = load_factor_library(FACTOR_LIBRARY)
    factors = library.factors_for_groups([group])
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


def _catalog_matching_active(tmp_path: Path) -> Path:
    """Build a catalog with exact active IDs without relabeling repository evidence.

    This is a unit-test fixture only. During a declared model cutover the committed
    catalog intentionally still points to the predecessor until Reviewed Formal
    Refresh creates genuine successor evidence. Strategy Operations must fail
    closed on that committed mismatch; membership behavior is tested separately
    against this synthetic identity-only fixture.
    """
    payload = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    for record in payload["records"]:
        if record.get("model_family_id") != "us_ranker":
            continue
        if record.get("model_version_id") == US_MODEL:
            break
        record["model_version_id"] = US_MODEL
        record["run_id"] = "us_x1_3-synthetic-membership-test"
        record["manifest_path"] = (
            "us_ranker/us_x1_3/us_x1_3-synthetic-membership-test/manifest.json"
        )
    path = tmp_path / "active-catalog.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _catalog_with_v43(tmp_path: Path) -> Path:
    base = _catalog_matching_active(tmp_path)
    payload = json.loads(base.read_text(encoding="utf-8"))
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
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _append(
    ledger: Path,
    model: str,
    signal: dict[str, object],
    *,
    delivery_status: str = "sent",
    fingerprint_suffix: str = "",
) -> None:
    payload = dict(signal)
    if fingerprint_suffix:
        payload["fingerprint"] = f"{payload['fingerprint']}{fingerprint_suffix}"
    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=model,
        signal=payload,
        delivery_status=delivery_status,
        workflow_run_id="12345",
        commit_sha="a" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )


def test_committed_operations_fail_closed_during_declared_model_cutover(
    tmp_path: Path,
) -> None:
    formal = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    formal_ids = {row["model_version_id"] for row in formal["records"]}
    if US_MODEL in formal_ids:
        pytest.skip("reviewed formal x1.3 evidence is already published")
    with pytest.raises(StrategyOperationsError, match="formal catalog"):
        build_operations_payload(
            formal_catalog=FORMAL_CATALOG,
            ledger_root=tmp_path,
            generated_at="2026-08-08T00:00:00Z",
        )


def test_formal_catalog_drives_exact_operations_membership(tmp_path: Path) -> None:
    catalog = _catalog_matching_active(tmp_path)
    payload = build_operations_payload(
        formal_catalog=catalog,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:00Z",
    )
    validate_operations_payload(payload)
    observed = _by_model(payload)
    formal = json.loads(catalog.read_text(encoding="utf-8"))
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
    assert observed[QQQ_MODEL]["status"] == "awaiting_observation"
    assert observed[BYD_MODEL]["status"] == "awaiting_observation"
    assert observed[US_MODEL]["status"] == "awaiting_observation"
    assert observed[CN_MODEL]["status"] == "awaiting_observation"
    assert observed[US_MODEL]["decision_cadence"] == "Every 10 provider sessions"
    assert observed[CN_MODEL]["decision_cadence"] == "Every 10 provider sessions"


def test_ranker_ledgers_project_current_targets(tmp_path: Path) -> None:
    catalog = _catalog_matching_active(tmp_path)
    _append(
        tmp_path / US_MODEL,
        US_MODEL,
        _ranker_signal(
            family="us_ranker",
            group="momentum_volatility_volume",
            current={"A": 1.0},
            target={"A": 0.5, "B": 0.5},
        ),
    )
    _append(
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
        formal_catalog=catalog,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:01Z",
    )
    records = _by_model(payload)
    us = records[US_MODEL]
    cn = records[CN_MODEL]
    assert us["strategy_id"] == "us_x"
    assert cn["strategy_id"] == "cn_x"
    assert us["status"] == "target_pending_execution"
    assert us["state_label"] == "US Top-15 rebalance"
    assert us["factor_freshness"] == "current"
    assert us["source_label"] == "Governed 10-session ranker decision ledger"
    assert cn["status"] == "target_pending_execution"
    assert cn["state_label"] == "CN risk-on · sector 4×1"
    assert cn["factor_freshness"] == "current"


def test_qqq_ledger_projects_canonical_factor_snapshot(tmp_path: Path) -> None:
    catalog = _catalog_matching_active(tmp_path)
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
        formal_catalog=catalog,
        ledger_root=tmp_path,
        generated_at="2026-08-08T00:00:01Z",
    )
    qqq = _by_model(payload)[QQQ_MODEL]
    assert qqq["strategy_id"] == "qqq_rotation"
    assert "current_operations_access" not in qqq
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
    assert all(len(row["implementation_hash"]) == 64 for row in factors)


def test_qqq_family_adapter_accepts_new_formal_version_without_version_branch(
    tmp_path: Path,
) -> None:
    catalog = _catalog_with_v43(tmp_path)
    ledger_root = tmp_path / "ledgers"
    _append(ledger_root / QQQ_V43_MODEL, QQQ_V43_MODEL, _v43_signal())

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
    factor_ids = {row["factor_id"] for row in qqq["factor_evidence"]}
    assert {"strategy.qqq.rsi14", "strategy.qqq.strong_defense"} <= factor_ids


def test_new_ledger_write_rejects_missing_factor_evidence(tmp_path: Path) -> None:
    signal = _qqq_signal()
    signal.pop("factor_evidence")
    signal.pop("factor_freshness_ok")
    with pytest.raises(StrategySignalLedgerError, match="factor evidence"):
        append_signal_evaluation(
            ledger_root=tmp_path / QQQ_MODEL,
            model_version_id=QQQ_MODEL,
            signal=signal,
            delivery_status="not_required",
            workflow_run_id="12345",
            commit_sha="a" * 40,
            created_at_utc="2026-08-08T00:00:00Z",
        )


def test_operations_payload_write_is_idempotent(tmp_path: Path) -> None:
    catalog = _catalog_matching_active(tmp_path)
    payload = build_operations_payload(
        formal_catalog=catalog,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    output = tmp_path / "operations.json"
    assert write_operations_payload(output, payload) is True
    assert write_operations_payload(output, payload) is False


def test_generated_operations_identity_matches_formal_bundle_catalog(tmp_path: Path) -> None:
    catalog = _catalog_matching_active(tmp_path)
    formal = json.loads(catalog.read_text(encoding="utf-8"))
    operations = build_operations_payload(
        formal_catalog=catalog,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    formal_by_id = {row["model_version_id"]: row for row in formal["records"]}
    operation_by_id = {
        row["model_version_id"]: row for row in operations["records"]
    }
    assert set(operation_by_id) == set(formal_by_id)
    for model_id, record in operation_by_id.items():
        catalog_record = formal_by_id[model_id]
        identity = record["source_identity"]
        assert identity["formal_bundle_id"] == catalog_record["bundle_id"]
        assert identity["formal_run_id"] == catalog_record["run_id"]
        assert identity["formal_evidence_cutoff"] == catalog_record["evidence_cutoff"]
