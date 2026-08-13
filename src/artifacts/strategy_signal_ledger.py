"""Append-only governed signal decision and delivery ledger."""

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
DELIVERY_SCHEMA_VERSION = "strategy_signal_delivery_v1"
MANIFEST_SCHEMA_VERSION = "strategy_signal_ledger_v1"
DELIVERY_STATUSES = {
    "failed",
    "not_required",
    "sent",
    "skipped_not_configured",
}
TERMINAL_DELIVERY_STATUSES = {
    "not_required",
    "sent",
    "skipped_not_configured",
}


class StrategySignalLedgerError(ValueError):
    """Raised when a governed signal transaction violates the ledger contract."""


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
    if not isinstance(value, (str, int, float)):
        raise StrategySignalLedgerError(f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise StrategySignalLedgerError(f"{label} must be an integer") from exc


def _signal_copy(signal: Mapping[str, Any]) -> dict[str, Any]:
    # Rendered prose is delivery material, not part of the canonical decision.
    return {
        str(key): value
        for key, value in signal.items()
        if key not in {"markdown", "telegram_text"}
    }


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategySignalLedgerError(f"invalid ledger JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise StrategySignalLedgerError(f"ledger JSON root must be an object: {path}")
    return payload


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


def _normalize_signal(
    signal: Mapping[str, Any],
) -> tuple[str, str, str, dict[str, Any], str]:
    signal_date = _required_string(signal.get("signal_date"), label="signal.signal_date")
    fingerprint = _required_string(signal.get("fingerprint"), label="signal.fingerprint")
    latest_data_date = _required_string(
        signal.get("latest_data_date")
        or signal.get("latest_data_date_at_creation")
        or signal_date,
        label="signal.latest_data_date",
    )
    if signal.get("research_only") is not True or signal.get("trade_ready") is not False:
        raise StrategySignalLedgerError(
            "signal must remain research_only=true and trade_ready=false"
        )
    _validate_factor_evidence(signal, latest_data_date)
    normalized_signal = _signal_copy(signal)
    signal_sha256 = hashlib.sha256(canonical_json_bytes(normalized_signal)).hexdigest()
    return signal_date, latest_data_date, fingerprint, normalized_signal, signal_sha256


def _validate_decision_record(
    payload: Mapping[str, Any],
    *,
    path: Path,
    model_version_id: str,
) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StrategySignalLedgerError(f"unsupported ledger schema: {path}")
    if payload.get("model_version_id") != model_version_id:
        raise StrategySignalLedgerError(f"ledger model identity mismatch: {path}")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise StrategySignalLedgerError(f"ledger research boundary mismatch: {path}")
    signal = payload.get("signal")
    if not isinstance(signal, dict):
        raise StrategySignalLedgerError(f"ledger signal is missing: {path}")
    signal_date = _required_string(payload.get("signal_date"), label="ledger.signal_date")
    if signal.get("signal_date") != signal_date:
        raise StrategySignalLedgerError(f"ledger signal date mismatch: {path}")
    expected_signal_sha = _required_string(
        payload.get("signal_sha256"),
        label="ledger.signal_sha256",
    )
    actual_signal_sha = hashlib.sha256(canonical_json_bytes(signal)).hexdigest()
    if expected_signal_sha != actual_signal_sha:
        raise StrategySignalLedgerError(f"ledger signal digest mismatch: {path}")
    if signal.get("fingerprint") != payload.get("fingerprint"):
        raise StrategySignalLedgerError(f"ledger fingerprint mismatch: {path}")
    latest_data_date = _required_string(
        payload.get("latest_data_date"),
        label="ledger.latest_data_date",
    )
    _validate_factor_evidence(signal, latest_data_date)
    return dict(payload)


def _record_paths_for_date(
    ledger_root: Path,
    *,
    model_version_id: str,
    signal_date: str,
) -> list[Path]:
    records = ledger_root / "records"
    if not records.is_dir():
        return []
    matches: list[Path] = []
    for path in sorted(records.glob("*.json")):
        payload = _json_object(path)
        if payload.get("signal_date") != signal_date:
            continue
        _validate_decision_record(
            payload,
            path=path,
            model_version_id=model_version_id,
        )
        matches.append(path)
    return matches


def _raw_latest_decision(
    ledger_root: Path,
    *,
    model_version_id: str,
) -> dict[str, Any] | None:
    path = ledger_root / "latest.json"
    if not path.is_file():
        return None
    return _validate_decision_record(
        _json_object(path),
        path=path,
        model_version_id=model_version_id,
    )


def _decision_record_bytes(payload: Mapping[str, Any]) -> bytes:
    # Delivery fields in historical records are not part of decision identity.
    decision = dict(payload)
    decision.pop("delivery", None)
    return canonical_json_bytes(decision)


def _write_manifest(
    ledger_root: Path,
    *,
    model_version_id: str,
    latest: Mapping[str, Any],
) -> None:
    records = ledger_root / "records"
    record_sha256 = hashlib.sha256(_decision_record_bytes(latest)).hexdigest()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "canonical_identity": "model_version_id+signal_date",
        "latest_signal_date": latest["signal_date"],
        "latest_data_date": latest["latest_data_date"],
        "latest_fingerprint": latest["fingerprint"],
        "latest_record_sha256": record_sha256,
        "record_count": len(list(records.glob("*.json"))),
        "append_only_records": True,
        "research_only": True,
        "trade_ready": False,
    }
    (ledger_root / "manifest.json").write_bytes(canonical_json_bytes(manifest))


def seal_signal_decision(
    *,
    ledger_root: Path,
    model_version_id: str,
    signal: Mapping[str, Any],
    workflow_run_id: str,
    commit_sha: str,
    created_at_utc: str,
) -> Path:
    """Seal exactly one canonical decision for ``model_version_id + signal_date``."""

    model_version_id = _required_string(model_version_id, label="model_version_id")
    workflow_run_id = _required_string(workflow_run_id, label="workflow_run_id")
    commit_sha = _required_string(commit_sha, label="commit_sha")
    created_at_utc = _required_string(created_at_utc, label="created_at_utc")
    (
        signal_date,
        latest_data_date,
        fingerprint,
        normalized_signal,
        signal_sha256,
    ) = _normalize_signal(signal)

    latest = _raw_latest_decision(ledger_root, model_version_id=model_version_id)
    if latest is not None and str(latest["signal_date"]) > signal_date:
        raise StrategySignalLedgerError(
            "out-of-order signal decision: "
            f"latest={latest['signal_date']} incoming={signal_date}"
        )

    same_date = _record_paths_for_date(
        ledger_root,
        model_version_id=model_version_id,
        signal_date=signal_date,
    )
    if len(same_date) > 1:
        raise StrategySignalLedgerError(
            "canonical decision conflict: multiple records already exist for "
            f"{model_version_id} {signal_date}"
        )
    if same_date:
        existing_path = same_date[0]
        existing = _validate_decision_record(
            _json_object(existing_path),
            path=existing_path,
            model_version_id=model_version_id,
        )
        if (
            existing.get("fingerprint") == fingerprint
            and existing.get("signal_sha256") == signal_sha256
            and existing.get("signal") == normalized_signal
        ):
            if latest is None or latest.get("signal_date") == signal_date:
                (ledger_root / "latest.json").write_bytes(
                    canonical_json_bytes(existing)
                )
                _write_manifest(
                    ledger_root,
                    model_version_id=model_version_id,
                    latest=existing,
                )
            return existing_path
        raise StrategySignalLedgerError(
            "canonical decision conflict: same model and signal_date produced a "
            f"different decision for {model_version_id} {signal_date}"
        )

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "signal_date": signal_date,
        "latest_data_date": latest_data_date,
        "fingerprint": fingerprint,
        "signal_sha256": signal_sha256,
        "signal": normalized_signal,
        "workflow": {
            "run_id": workflow_run_id,
            "commit_sha": commit_sha,
        },
        "created_at_utc": created_at_utc,
        "research_only": True,
        "trade_ready": False,
    }
    record_bytes = canonical_json_bytes(record)
    records = ledger_root / "records"
    records.mkdir(parents=True, exist_ok=True)
    record_path = records / f"{signal_date}.json"
    if record_path.exists():
        raise StrategySignalLedgerError(f"canonical record path already exists: {record_path}")
    record_path.write_bytes(record_bytes)
    (ledger_root / "latest.json").write_bytes(record_bytes)
    _write_manifest(
        ledger_root,
        model_version_id=model_version_id,
        latest=record,
    )
    return record_path


def _delivery_receipts(
    ledger_root: Path,
    *,
    decision: Mapping[str, Any],
) -> list[tuple[Path, dict[str, Any]]]:
    signal_date = str(decision["signal_date"])
    root = ledger_root / "deliveries" / signal_date
    if not root.is_dir():
        return []
    receipts: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        payload = _json_object(path)
        if payload.get("schema_version") != DELIVERY_SCHEMA_VERSION:
            raise StrategySignalLedgerError(f"unsupported delivery schema: {path}")
        if payload.get("model_version_id") != decision.get("model_version_id"):
            raise StrategySignalLedgerError(f"delivery model identity mismatch: {path}")
        if payload.get("signal_date") != signal_date:
            raise StrategySignalLedgerError(f"delivery signal date mismatch: {path}")
        if payload.get("fingerprint") != decision.get("fingerprint"):
            raise StrategySignalLedgerError(f"delivery fingerprint mismatch: {path}")
        if payload.get("signal_sha256") != decision.get("signal_sha256"):
            raise StrategySignalLedgerError(f"delivery decision digest mismatch: {path}")
        if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
            raise StrategySignalLedgerError(f"delivery research boundary mismatch: {path}")
        delivery = payload.get("delivery")
        if not isinstance(delivery, Mapping):
            raise StrategySignalLedgerError(f"delivery payload is missing: {path}")
        if delivery.get("status") not in DELIVERY_STATUSES:
            raise StrategySignalLedgerError(f"invalid delivery status: {path}")
        receipts.append((path, payload))
    return receipts


def record_signal_delivery(
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
    """Append a delivery receipt for an already sealed canonical decision."""

    model_version_id = _required_string(model_version_id, label="model_version_id")
    delivery_status = _required_string(delivery_status, label="delivery_status")
    if delivery_status not in DELIVERY_STATUSES:
        raise StrategySignalLedgerError(
            f"delivery_status must be one of {sorted(DELIVERY_STATUSES)}"
        )
    workflow_run_id = _required_string(workflow_run_id, label="workflow_run_id")
    commit_sha = _required_string(commit_sha, label="commit_sha")
    created_at_utc = _required_string(created_at_utc, label="created_at_utc")
    signal_date, _, fingerprint, normalized_signal, signal_sha256 = _normalize_signal(signal)

    latest = _raw_latest_decision(ledger_root, model_version_id=model_version_id)
    if latest is None:
        raise StrategySignalLedgerError("delivery requires a sealed canonical decision")
    if latest.get("signal_date") != signal_date:
        raise StrategySignalLedgerError(
            "delivery can only bind the latest canonical decision: "
            f"latest={latest.get('signal_date')} incoming={signal_date}"
        )
    if (
        latest.get("fingerprint") != fingerprint
        or latest.get("signal_sha256") != signal_sha256
        or latest.get("signal") != normalized_signal
    ):
        raise StrategySignalLedgerError(
            "delivery signal does not match the sealed canonical decision"
        )

    delivery = {
        "status": delivery_status,
        "github_issue_number": github_issue_number,
        "telegram_message_id": telegram_message_id,
        "error": delivery_error,
    }
    receipts = _delivery_receipts(ledger_root, decision=latest)
    for path, existing in receipts:
        existing_delivery = existing["delivery"]
        if existing_delivery.get("status") in TERMINAL_DELIVERY_STATUSES:
            if dict(existing_delivery) == delivery:
                return path
            raise StrategySignalLedgerError(
                "delivery already finalized for canonical decision: "
                f"{model_version_id} {signal_date}"
            )

    receipt: dict[str, Any] = {
        "schema_version": DELIVERY_SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "signal_date": signal_date,
        "fingerprint": fingerprint,
        "signal_sha256": signal_sha256,
        "delivery": delivery,
        "workflow": {
            "run_id": workflow_run_id,
            "commit_sha": commit_sha,
        },
        "created_at_utc": created_at_utc,
        "research_only": True,
        "trade_ready": False,
    }
    receipt_bytes = canonical_json_bytes(receipt)
    receipt_dir = ledger_root / "deliveries" / signal_date
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{workflow_run_id}.json"
    if receipt_path.exists():
        if receipt_path.read_bytes() == receipt_bytes:
            return receipt_path
        raise StrategySignalLedgerError(
            f"append-only delivery drift for workflow run: {receipt_path}"
        )
    receipt_path.write_bytes(receipt_bytes)
    return receipt_path


def read_latest_evaluation(
    ledger_root: Path,
    *,
    model_version_id: str,
) -> dict[str, Any] | None:
    decision = _raw_latest_decision(ledger_root, model_version_id=model_version_id)
    if decision is None:
        return None
    result = dict(decision)
    # Historical embedded delivery fields are deliberately ignored. Delivery is
    # a separate side effect and only a hash-bound receipt may project it.
    result["delivery"] = {
        "status": "pending",
        "github_issue_number": None,
        "telegram_message_id": None,
        "error": None,
    }
    result.pop("delivery_workflow", None)
    receipts = _delivery_receipts(ledger_root, decision=decision)
    if receipts:
        _, receipt = max(
            receipts,
            key=lambda item: (
                str(item[1].get("created_at_utc") or ""),
                str(item[1].get("workflow", {}).get("run_id") or ""),
            ),
        )
        result["delivery"] = dict(receipt["delivery"])
        result["delivery_workflow"] = dict(receipt["workflow"])
    return result


def parse_optional_int(value: object, *, label: str) -> int | None:
    """CLI-facing integer parser kept here so workflow adapters share validation."""

    return _optional_int(value, label=label)
