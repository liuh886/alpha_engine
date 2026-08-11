from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.strategy_operations import (
    BYD_FAMILY,
    BYD_V13_MODEL,
    QQQ_FAMILY,
    QQQ_V43_MODEL,
    build_operations_payload,
    validate_operations_payload,
    write_operations_payload,
)
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    append_signal_evaluation,
)

FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")
QQQ_MODEL = QQQ_V43_MODEL


def _catalog_with_v43(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "model_family_id": QQQ_FAMILY,
                        "model_version_id": QQQ_V43_MODEL,
                        "run_id": "qqqi_qqq_tqqq_v4_3-through-2026_08_07",
                        "bundle_id": "a" * 64,
                        "manifest_sha256": "b" * 64,
                        "evidence_cutoff": "2026-08-07",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _by_model(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    records = payload["records"]
    assert isinstance(records, list)
    return {str(row["model_version_id"]): row for row in records if isinstance(row, dict)}


def _factor(factor_id: str, value: float, *, role: str = "state_input") -> dict[str, object]:
    return {
        "factor_id": factor_id,
        "value": value,
        "unit": "ratio",
        "source": "test",
        "source_date": "2026-08-07",
        "freshness": "current",
        "decision_role": role,
    }


def _qqq_signal() -> dict[str, object]:
    return {
        "schema_version": "strategy_signal_v1",
        "model_version_id": QQQ_MODEL,
        "model_family_id": QQQ_FAMILY,
        "signal_date": "2026-08-07",
        "market_cutoff": "US close 2026-08-07",
        "current_weights": {"QQQ": 1.0},
        "target_weights": {"QQQ": 1.0},
        "changed": False,
        "should_alert": False,
        "turnover_units": 0.0,
        "estimated_transaction_cost": 0.0,
        "execution_time": "next_eligible_open",
        "reason_code": "state1_qqq",
        "research_only": True,
        "trade_ready": False,
        "factor_freshness_ok": True,
        "factor_evidence": [
            _factor("strategy.qqq.rsi14", 53.0),
            _factor("strategy.qqq.strong_defense", 0.0),
        ],
        "model_identity": {"formal_model_id": QQQ_MODEL},
    }


def _v43_signal() -> dict[str, object]:
    signal = _qqq_signal()
    signal["model_version_id"] = QQQ_V43_MODEL
    signal["target_weights"] = {"QQQ": 0.5, "SGOV": 0.5}
    signal["changed"] = True
    signal["should_alert"] = True
    signal["reason_code"] = "state0_base_defense"
    signal["model_identity"] = {"formal_model_id": QQQ_V43_MODEL}
    return signal


def _byd_signal() -> dict[str, object]:
    return {
        "schema_version": "strategy_signal_v1",
        "model_version_id": BYD_V13_MODEL,
        "model_family_id": BYD_FAMILY,
        "signal_date": "2026-08-10",
        "market_cutoff": "CN close 2026-08-10",
        "current_weights": {"002594.SZ": 0.75, "515180.SH": 0.25},
        "target_weights": {"002594.SZ": 0.75, "515180.SH": 0.25},
        "changed": False,
        "should_alert": False,
        "turnover_units": 0.0,
        "estimated_transaction_cost": 0.0,
        "execution_time": "next_eligible_open",
        "reason_code": "base_75_25",
        "research_only": True,
        "trade_ready": False,
        "factor_freshness_ok": True,
        "factor_evidence": [
            _factor("strategy.byd.recovery_event", 0.0),
            _factor("strategy.byd.low_vol_confirmation", 0.0),
        ],
        "model_identity": {"formal_model_id": BYD_V13_MODEL},
    }


def _append(root: Path, model: str, signal: dict[str, object]) -> None:
    append_signal_evaluation(
        ledger_root=root / model,
        model_version_id=model,
        signal=signal,
        delivery_status="not_required",
        workflow_run_id="12345",
        commit_sha="a" * 40,
        created_at_utc="2026-08-08T00:00:00Z",
    )


def test_operations_payload_matches_current_formal_catalog(tmp_path: Path) -> None:
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    validate_operations_payload(payload)
    catalog = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
    assert set(_by_model(payload)) == {
        str(row["model_version_id"]) for row in catalog["records"]
    }


def test_missing_supported_ledger_is_awaiting_observation(tmp_path: Path) -> None:
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    by_model = _by_model(payload)
    assert by_model["us_x1_2"]["status"] == "awaiting_observation"
    assert by_model["cn_x1_1"]["status"] == "awaiting_observation"
    assert by_model[BYD_V13_MODEL]["status"] == "awaiting_observation"
    assert by_model[QQQ_V43_MODEL]["status"] == "awaiting_observation"


def test_ranker_family_adapter_accepts_current_formal_us_version_without_version_branch(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "model_family_id": "us_ranker",
                        "model_version_id": "us_x1_2",
                        "run_id": "us_x1_2-through-2026_08_10",
                        "bundle_id": "c" * 64,
                        "manifest_sha256": "d" * 64,
                        "evidence_cutoff": "2026-08-10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    signal = {
        "schema_version": "strategy_signal_v1",
        "model_version_id": "us_x1_2",
        "model_family_id": "us_ranker",
        "signal_date": "2026-08-10",
        "market_cutoff": "US close 2026-08-10",
        "current_weights": {"AAPL": 0.5, "MSFT": 0.5},
        "target_weights": {"AAPL": 0.5, "MSFT": 0.5},
        "changed": False,
        "should_alert": False,
        "turnover_units": 0.0,
        "estimated_transaction_cost": 0.0,
        "execution_time": "next_eligible_open",
        "reason_code": "formal_us_x1_2_10_session_rebalance",
        "research_only": True,
        "trade_ready": False,
        "factor_freshness_ok": True,
        "factor_evidence": [_factor("ohlcv.momentum_20", 0.1, role="selected_holding")],
        "model_identity": {"formal_model_id": "us_x1_2"},
    }
    _append(tmp_path / "ledgers", "us_x1_2", signal)

    payload = build_operations_payload(
        formal_catalog=catalog,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-10T00:00:01Z",
    )
    record = _by_model(payload)["us_x1_2"]
    assert record["status"] == "current_no_change"
    assert record["factor_freshness"] == "current"
    assert {row["asset"] for row in record["allocations"]} == {"AAPL", "MSFT"}


def test_qqq_family_adapter_accepts_new_formal_version_without_version_branch(
    tmp_path: Path,
) -> None:
    catalog = _catalog_with_v43(tmp_path)
    ledger_root = tmp_path / "ledgers"
    _append(ledger_root, QQQ_V43_MODEL, _v43_signal())

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
    payload = build_operations_payload(
        formal_catalog=FORMAL_CATALOG,
        ledger_root=tmp_path / "ledgers",
        generated_at="2026-08-08T00:00:00Z",
    )
    output = tmp_path / "operations.json"
    assert write_operations_payload(output, payload) is True
    assert write_operations_payload(output, payload) is False
