"""Append-only governed signal-evaluation ledger shared by formal strategies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.factors.strategy_snapshot import (
    StrategyFactorSnapshotError,
    validate_strategy_factor_snapshot,
)

SCHEMA_VERSION = "strategy_signal_evaluation_v1"
MANIFEST_SCHEMA_VERSION = "strategy_signal_ledger_v1"


class StrategySignalLedgerError(ValueError):
    """Raised when a signal evaluation violates the ledger contract."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _required_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrategySignalLedgerError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_int(value: object, *, label: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise StrategySignalLedgerError(f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise StrategySignalLedgerError(f"{label} must be an integer") from exc


def _signal_copy(signal: Mapping[str, Any]) -> dict[str, Any]:
    # Rendered prose is delivery material, not part of the machine read model.
    return {
        str(key): value for key, value in signal.items() if key not in {"markdown", "telegram_text"}
    }


def _validate_factor_evidence(signal: Mapping[str, Any], latest_data_date: str) -> None:
    factor_evidence = signal.get("factor_evidence")
    try:
        validate_strategy_factor_snapshot(factor_evidence)
    except StrategyFactorSnapshotError as exc:
        raise StrategySignalLedgerError(f"invalid signal factor evidence: {exc}") from exc
    if not isinstance(factor_evidence, Mapping):
        raise StrategySignalLedgerError("signal factor evidence must be an object")
    if factor_evidence.get("observation_cutoff") != latest_data_date:
        raise StrategySignalLedgerError(
            "factor observation cutoff must match signal latest_data_date"
        )
    factor_current = factor_evidence.get("freshness") == "current"
    if signal.get("factor_freshness_ok") is not factor_current:
        raise StrategySignalLedgerError(
            "signal.factor_freshness_ok must match factor evidence freshness"
        )
    if signal.get("data_freshness_ok") is True and not factor_current:
        raise StrategySignalLedgerError(
            "fresh data cannot publish a stale or blocked factor snapshot"
        )


def append_signal_evaluation(
    *,
    ledger_root: Path,
    model_version_id: str,
    signal: Mapping[str, Any],
    delivery_status: str,
    workflow_run_id: str,
    commit_sha: str,
    created_at_utc: str,
    github_issue_number: int | None = None,
    telegram_message_id: int | None = None,
    delivery_error: str | None = None,
) -> Path:
    """Persist one immutable evaluation and atomically advance ``latest.json``."""

    model_version_id = _required_string(model_version_id, label="model_version_id")
    signal_date = _required_string(signal.get("signal_date"), label="signal.signal_date")
    fingerprint = _required_string(signal.get("fingerprint"), label="signal.fingerprint")
    latest_data_date = _required_string(
        signal.get("latest_data_date") or signal.get("latest_data_date_at_creation") or signal_date,
        label="signal.latest_data_date",
    )
    delivery_status = _required_string(delivery_status, label="delivery_status")
    workflow_run_id = _required_string(workflow_run_id, label="workflow_run_id")
    commit_sha = _required_string(commit_sha, label="commit_sha")
    created_at_utc = _required_string(created_at_utc, label="created_at_utc")

    if signal.get("research_only") is not True or signal.get("trade_ready") is not False:
        raise StrategySignalLedgerError(
            "signal must remain research_only=true and trade_ready=false"
        )
    _validate_factor_evidence(signal, latest_data_date)

    normalized_signal = _signal_copy(signal)
    signal_sha256 = hashlib.sha256(canonical_json_bytes(normalized_signal)).hexdigest()
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "signal_date": signal_date,
        "latest_data_date": latest_data_date,
        "fingerprint": fingerprint,
        "signal_sha256": signal_sha256,
        "signal": normalized_signal,
        "delivery": {
            "status": delivery_status,
            "github_issue_number": github_issue_number,
            "telegram_message_id": telegram_message_id,
            "error": delivery_error,
        },
        "workflow": {
            "run_id": workflow_run_id,
            "commit_sha": commit_sha,
        },
        "created_at_utc": created_at_utc,
        "research_only": True,
        "trade_ready": False,
    }
    record_bytes = canonical_json_bytes(record)
    record_sha256 = hashlib.sha256(record_bytes).hexdigest()

    records = ledger_root / "records"
    records.mkdir(parents=True, exist_ok=True)
    record_path = records / f"{signal_date}-{fingerprint}.json"
    if record_path.exists() and record_path.read_bytes() != record_bytes:
        raise StrategySignalLedgerError(f"append-only signal drift: {record_path}")
    record_path.write_bytes(record_bytes)

    latest_path = ledger_root / "latest.json"
    latest_path.write_bytes(record_bytes)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "latest_signal_date": signal_date,
        "latest_data_date": latest_data_date,
        "latest_fingerprint": fingerprint,
        "latest_record_sha256": record_sha256,
        "record_count": len(list(records.glob("*.json"))),
        "append_only_records": True,
        "research_only": True,
        "trade_ready": False,
    }
    (ledger_root / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return record_path


def read_latest_evaluation(ledger_root: Path, *, model_version_id: str) -> dict[str, Any] | None:
    path = ledger_root / "latest.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StrategySignalLedgerError(f"ledger latest record must be an object: {path}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StrategySignalLedgerError(f"unsupported ledger schema: {path}")
    if payload.get("model_version_id") != model_version_id:
        raise StrategySignalLedgerError(f"ledger model identity mismatch: {path}")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise StrategySignalLedgerError(f"ledger research boundary mismatch: {path}")
    signal = payload.get("signal")
    if not isinstance(signal, dict):
        raise StrategySignalLedgerError(f"ledger signal is missing: {path}")
    expected_signal_sha = payload.get("signal_sha256")
    actual_signal_sha = hashlib.sha256(canonical_json_bytes(signal)).hexdigest()
    if expected_signal_sha != actual_signal_sha:
        raise StrategySignalLedgerError(f"ledger signal digest mismatch: {path}")
    factor_evidence = signal.get("factor_evidence")
    if factor_evidence is not None:
        try:
            validate_strategy_factor_snapshot(factor_evidence)
        except StrategyFactorSnapshotError as exc:
            raise StrategySignalLedgerError(
                f"ledger factor evidence is invalid: {path}: {exc}"
            ) from exc
    return payload


def parse_optional_int(value: object, *, label: str) -> int | None:
    """CLI-facing integer parser kept here so workflow adapters share validation."""

    return _optional_int(value, label=label)
