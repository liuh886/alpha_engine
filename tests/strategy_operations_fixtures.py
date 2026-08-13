from __future__ import annotations

import json
from pathlib import Path

from src.artifacts.strategy_signal_ledger import append_signal_evaluation
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


def by_model(payload: dict[str, object]) -> dict[str, dict[str, object]]:
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


def qqq_signal(*, changed: bool = True) -> dict[str, object]:
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


def v43_signal() -> dict[str, object]:
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


def ranker_signal(
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


def catalog_matching_active(tmp_path: Path) -> Path:
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


def catalog_with_v43(tmp_path: Path) -> Path:
    base = catalog_matching_active(tmp_path)
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


def append_evaluation(
    ledger: Path,
    model: str,
    signal: dict[str, object],
    *,
    delivery_status: str = "sent",
    github_issue_number: int | None = None,
    telegram_message_id: int | None = None,
) -> None:
    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=model,
        signal=signal,
        delivery_status="pending",
        workflow_run_id="12345",
        commit_sha="a" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )
    append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=model,
        signal=signal,
        delivery_status=delivery_status,
        github_issue_number=github_issue_number,
        telegram_message_id=telegram_message_id,
        workflow_run_id="12345",
        commit_sha="a" * 40,
        created_at_utc="2026-08-08T00:00:01Z",
    )
