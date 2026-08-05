"""Canonical PIT company-information event validation and identity."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVENT_FAMILIES = {
    "earnings_forecast",
    "preliminary_earnings",
    "buyback",
    "restricted_unlock",
    "holding_change",
    "dividend",
}
EVENT_STAGES = {
    "forecast_initial",
    "forecast_revision",
    "flash_initial",
    "flash_revision",
    "plan",
    "approval",
    "first_execution",
    "progress",
    "completion",
    "scheduled",
    "executed",
    "increase_plan",
    "decrease_plan",
    "increase_execution",
    "decrease_execution",
    "distribution_plan",
    "distribution_execution",
}
RECONCILIATION_STATUSES = {
    "source_only",
    "reconciled",
    "conflict",
    "missing_primary",
}
AVAILABILITY_STATUSES = {
    "usable",
    "partial",
    "provider_failed",
    "unresolved",
}


@dataclass(frozen=True)
class CompanyInformationEvent:
    """One source-bound, revision-aware company information observation."""

    market: str
    symbol: str
    exchange: str
    entity_id: str
    event_family: str
    event_stage: str
    fiscal_period_end: str
    announced_at: str
    first_eligible_session: str
    effective_date: str
    payload_schema: str
    payload_json: str
    source_provider: str
    source_document_id: str
    source_endpoint: str
    retrieved_at: str
    source_hash: str
    revision_sequence: int
    supersedes_event_id: str
    confidence: float
    reconciliation_status: str
    availability_status: str
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def payload(self) -> dict[str, Any]:
        parsed = json.loads(self.payload_json)
        if not isinstance(parsed, dict):
            raise ValueError("payload_json must decode to a mapping")
        return parsed


def _text(record: Mapping[str, Any], key: str, *, required: bool = True) -> str:
    value = str(record.get(key, "")).strip()
    if required and not value:
        raise ValueError(f"company information event requires non-empty {key}")
    return value


def _date(record: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = _text(record, key, required=required)
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date") from exc


def _timestamp(record: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = _text(record, key, required=required)
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{key} must include a timezone offset")
    return parsed.isoformat()


def _canonical_payload(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must contain valid JSON") from exc
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ValueError("event payload must be a mapping")
    return json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_company_information_event_id(record: Mapping[str, Any]) -> str:
    identity = {
        "market": str(record["market"]).lower(),
        "symbol": str(record["symbol"]).upper(),
        "entity_id": str(record["entity_id"]),
        "event_family": str(record["event_family"]).lower(),
        "event_stage": str(record["event_stage"]).lower(),
        "fiscal_period_end": str(record.get("fiscal_period_end", "")),
        "announced_at": str(record["announced_at"]),
        "source_document_id": str(record["source_document_id"]),
        "revision_sequence": int(record["revision_sequence"]),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_company_information_event(
    record: Mapping[str, Any],
) -> CompanyInformationEvent:
    market = _text(record, "market").lower()
    if market != "cn":
        raise ValueError("company information event v1 currently supports market='cn'")
    symbol = _text(record, "symbol").upper().zfill(6)
    if len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("CN symbol must be a six-digit code")
    exchange = _text(record, "exchange").upper()
    entity_id = _text(record, "entity_id")
    event_family = _text(record, "event_family").lower()
    if event_family not in EVENT_FAMILIES:
        raise ValueError(f"unsupported event_family: {event_family}")
    event_stage = _text(record, "event_stage").lower()
    if event_stage not in EVENT_STAGES:
        raise ValueError(f"unsupported event_stage: {event_stage}")

    fiscal_period_end = _date(record, "fiscal_period_end")
    if event_family in {"earnings_forecast", "preliminary_earnings"} and not fiscal_period_end:
        raise ValueError("earnings events require fiscal_period_end")
    announced_at = _timestamp(record, "announced_at", required=True)
    first_eligible_session = _date(record, "first_eligible_session")
    effective_date = _date(record, "effective_date")
    if effective_date and effective_date < announced_at[:10]:
        raise ValueError("effective_date cannot precede announced_at")
    if first_eligible_session and first_eligible_session <= announced_at[:10]:
        raise ValueError("first_eligible_session must be strictly after announced_at date")

    payload_schema = _text(record, "payload_schema")
    payload_json = _canonical_payload(record.get("payload_json", record.get("payload", {})))
    source_provider = _text(record, "source_provider")
    source_document_id = _text(record, "source_document_id")
    source_endpoint = _text(record, "source_endpoint")
    retrieved_at = _timestamp(record, "retrieved_at", required=True)
    source_hash = _text(record, "source_hash").lower()
    if not _SHA256.fullmatch(source_hash):
        raise ValueError("source_hash must be a SHA-256 digest")

    revision_sequence = int(record.get("revision_sequence", -1))
    if revision_sequence < 0:
        raise ValueError("revision_sequence must be >= 0")
    supersedes_event_id = _text(record, "supersedes_event_id", required=False).lower()
    if revision_sequence == 0 and supersedes_event_id:
        raise ValueError("initial event cannot supersede another event")
    if revision_sequence > 0 and not supersedes_event_id:
        raise ValueError("revised event must identify superseded event")
    if supersedes_event_id and not _SHA256.fullmatch(supersedes_event_id):
        raise ValueError("supersedes_event_id must be a SHA-256 digest")

    confidence = float(record.get("confidence", 0.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    reconciliation_status = _text(record, "reconciliation_status").lower()
    if reconciliation_status not in RECONCILIATION_STATUSES:
        raise ValueError("unsupported reconciliation_status")
    availability_status = _text(record, "availability_status").lower()
    if availability_status not in AVAILABILITY_STATUSES:
        raise ValueError("unsupported availability_status")
    if reconciliation_status == "reconciled" and availability_status != "usable":
        raise ValueError("reconciled event must be usable")
    if reconciliation_status != "reconciled" and availability_status == "usable":
        raise ValueError("only reconciled events may be marked usable")

    normalized: dict[str, Any] = {
        "market": market,
        "symbol": symbol,
        "exchange": exchange,
        "entity_id": entity_id,
        "event_family": event_family,
        "event_stage": event_stage,
        "fiscal_period_end": fiscal_period_end,
        "announced_at": announced_at,
        "first_eligible_session": first_eligible_session,
        "effective_date": effective_date,
        "payload_schema": payload_schema,
        "payload_json": payload_json,
        "source_provider": source_provider,
        "source_document_id": source_document_id,
        "source_endpoint": source_endpoint,
        "retrieved_at": retrieved_at,
        "source_hash": source_hash,
        "revision_sequence": revision_sequence,
        "supersedes_event_id": supersedes_event_id,
        "confidence": confidence,
        "reconciliation_status": reconciliation_status,
        "availability_status": availability_status,
    }
    event_id = build_company_information_event_id(normalized)
    supplied = _text(record, "event_id", required=False).lower()
    if supplied and supplied != event_id:
        raise ValueError("event_id does not match canonical company information event")
    normalized["event_id"] = event_id
    return CompanyInformationEvent(**normalized)
