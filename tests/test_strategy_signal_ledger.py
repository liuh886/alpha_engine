from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    append_signal_evaluation,
    read_latest_evaluation,
)
from src.factors.strategy_snapshot import build_strategy_factor_snapshot

MODEL = "qqqi_qqq_tqqq_v4_3"


def _signal(
    *,
    signal_date: str = "2026-08-12",
    fingerprint: str = "decision-a",
    target_state: int = 1,
) -> dict[str, object]:
    signal: dict[str, object] = {
        "schema_version": "2.0",
        "model_id": MODEL,
        "research_only": True,
        "trade_ready": False,
        "should_alert": target_state != 0,
        "fingerprint": fingerprint,
        "signal_date": signal_date,
        "latest_data_date": signal_date,
        "data_freshness_ok": True,
        "execution_time": "next_session_open",
        "current_state": 0,
        "target_state": target_state,
        "current_weights": {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0},
        "target_weights": (
            {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0}
            if target_state
            else {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0}
        ),
        "turnover_units": 1.0 if target_state else 0.0,
        "estimated_transaction_cost": 0.001 if target_state else 0.0,
        "decision_reason": "test",
        "decision_reason_label": "Test",
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
    factor_evidence = build_strategy_factor_snapshot(
        model_family_id="qqq_rotation",
        signal=signal,
    )
    signal["factor_evidence"] = factor_evidence
    signal["factor_freshness_ok"] = factor_evidence["freshness"] == "current"
    return signal


def _seal(
    ledger: Path,
    signal: dict[str, object],
    *,
    run_id: str = "seal-1",
    created_at: str = "2026-08-13T00:00:00Z",
) -> Path:
    return append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=MODEL,
        signal=signal,
        delivery_status="pending",
        workflow_run_id=run_id,
        commit_sha="a" * 40,
        created_at_utc=created_at,
    )


def _deliver(
    ledger: Path,
    signal: dict[str, object],
    *,
    status: str,
    run_id: str,
    created_at: str,
    issue_number: int | None = None,
    message_id: int | None = None,
    error: str | None = None,
) -> Path:
    return append_signal_evaluation(
        ledger_root=ledger,
        model_version_id=MODEL,
        signal=signal,
        delivery_status=status,
        github_issue_number=issue_number,
        telegram_message_id=message_id,
        delivery_error=error,
        workflow_run_id=run_id,
        commit_sha="b" * 40,
        created_at_utc=created_at,
    )


def test_same_model_and_signal_date_has_exactly_one_canonical_decision(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / MODEL
    signal = _signal()
    first = _seal(ledger, signal, run_id="seal-1")
    second = _seal(ledger, signal, run_id="seal-2")

    assert first == second
    records = list((ledger / "records").glob("*.json"))
    assert records == [ledger / "records" / "2026-08-12.json"]
    assert json.loads((ledger / "manifest.json").read_text())["canonical_identity"] == (
        "model_version_id+signal_date"
    )


def test_same_model_and_signal_date_with_different_decision_fails_closed(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / MODEL
    _seal(ledger, _signal(fingerprint="decision-a", target_state=1))

    with pytest.raises(StrategySignalLedgerError, match="canonical decision conflict"):
        _seal(
            ledger,
            _signal(fingerprint="decision-b", target_state=0),
            run_id="seal-2",
        )

    assert len(list((ledger / "records").glob("*.json"))) == 1


def test_older_signal_cannot_move_latest_backward(tmp_path: Path) -> None:
    ledger = tmp_path / MODEL
    _seal(ledger, _signal(signal_date="2026-08-13", fingerprint="new"))

    with pytest.raises(StrategySignalLedgerError, match="out-of-order signal decision"):
        _seal(
            ledger,
            _signal(signal_date="2026-08-12", fingerprint="old"),
            run_id="seal-old",
        )

    latest = read_latest_evaluation(ledger, model_version_id=MODEL)
    assert latest is not None
    assert latest["signal_date"] == "2026-08-13"


def test_delivery_requires_a_previously_sealed_decision(tmp_path: Path) -> None:
    ledger = tmp_path / MODEL
    with pytest.raises(StrategySignalLedgerError, match="sealed canonical decision"):
        _deliver(
            ledger,
            _signal(),
            status="sent",
            run_id="delivery-1",
            created_at="2026-08-13T00:01:00Z",
            issue_number=100,
            message_id=200,
        )


def test_delivery_is_separate_from_immutable_decision(tmp_path: Path) -> None:
    ledger = tmp_path / MODEL
    signal = _signal()
    decision_path = _seal(ledger, signal)

    raw_decision = json.loads(decision_path.read_text())
    assert "delivery" not in raw_decision
    pending = read_latest_evaluation(ledger, model_version_id=MODEL)
    assert pending is not None
    assert pending["delivery"]["status"] == "pending"

    _deliver(
        ledger,
        signal,
        status="sent",
        run_id="delivery-1",
        created_at="2026-08-13T00:01:00Z",
        issue_number=100,
        message_id=200,
    )
    delivered = read_latest_evaluation(ledger, model_version_id=MODEL)
    assert delivered is not None
    assert delivered["delivery"] == {
        "status": "sent",
        "github_issue_number": 100,
        "telegram_message_id": 200,
        "error": None,
    }
    assert "delivery" not in json.loads(decision_path.read_text())


def test_failed_delivery_can_retry_but_terminal_delivery_cannot_drift(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / MODEL
    signal = _signal()
    _seal(ledger, signal)
    _deliver(
        ledger,
        signal,
        status="failed",
        run_id="delivery-1",
        created_at="2026-08-13T00:01:00Z",
        issue_number=100,
        error="telegram_api_rejected",
    )
    _deliver(
        ledger,
        signal,
        status="sent",
        run_id="delivery-2",
        created_at="2026-08-13T00:02:00Z",
        issue_number=100,
        message_id=200,
    )

    latest = read_latest_evaluation(ledger, model_version_id=MODEL)
    assert latest is not None
    assert latest["delivery"]["status"] == "sent"

    with pytest.raises(StrategySignalLedgerError, match="delivery already finalized"):
        _deliver(
            ledger,
            signal,
            status="sent",
            run_id="delivery-3",
            created_at="2026-08-13T00:03:00Z",
            issue_number=100,
            message_id=201,
        )
