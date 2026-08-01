"""Canonical point-in-time fundamental event validation and identity."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class FundamentalEvent:
    """One source-bound, point-in-time fundamental observation."""

    market: str
    symbol: str
    exchange: str
    entity_id: str
    fiscal_period_end: str
    fiscal_year: int
    fiscal_period: str
    reported_at: str
    available_at: str
    filing_type: str
    source_provider: str
    source_document_id: str
    source_endpoint: str
    field: str
    value: float
    unit: str
    currency: str
    is_quarterly: bool
    is_derived: bool
    derivation_rule: str
    revision_sequence: int
    supersedes_event_id: str
    retrieved_at: str
    source_hash: str
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic serialization-ready mapping."""

        return asdict(self)


def _required_text(record: dict[str, Any], key: str) -> str:
    value = str(record.get(key, "")).strip()
    if not value:
        raise ValueError(f"fundamental event requires non-empty {key}")
    return value


def _parse_date(value: Any, key: str) -> str:
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date") from exc


def _parse_timestamp(value: Any, key: str) -> str:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO timestamp") from exc


def _require_bool(record: dict[str, Any], key: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def build_event_id(record: dict[str, Any]) -> str:
    """Build the immutable event identity from source and revision semantics."""

    identity = {
        "market": str(record["market"]).lower(),
        "symbol": str(record["symbol"]).upper(),
        "entity_id": str(record["entity_id"]),
        "fiscal_period_end": str(record["fiscal_period_end"]),
        "reported_at": str(record["reported_at"]),
        "source_provider": str(record["source_provider"]),
        "source_document_id": str(record["source_document_id"]),
        "field": str(record["field"]),
        "unit": str(record["unit"]),
        "currency": str(record["currency"]).upper(),
        "revision_sequence": int(record["revision_sequence"]),
        "is_derived": bool(record["is_derived"]),
        "derivation_rule": str(record.get("derivation_rule", "")),
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_event_record(record: dict[str, Any]) -> FundamentalEvent:
    """Validate and normalize one raw fundamental-event mapping."""

    market = _required_text(record, "market").lower()
    if market not in {"us", "cn"}:
        raise ValueError("market must be 'us' or 'cn'")

    symbol = _required_text(record, "symbol").upper()
    exchange = _required_text(record, "exchange").upper()
    entity_id = _required_text(record, "entity_id")
    fiscal_period_end = _parse_date(record.get("fiscal_period_end"), "fiscal_period_end")

    fiscal_year = int(record.get("fiscal_year", 0))
    if fiscal_year < 1900:
        raise ValueError("fiscal_year must be >= 1900")
    fiscal_period = _required_text(record, "fiscal_period").upper()

    reported_at = _parse_timestamp(record.get("reported_at"), "reported_at")
    available_at = _parse_timestamp(record.get("available_at"), "available_at")
    if datetime.fromisoformat(available_at) < datetime.fromisoformat(reported_at):
        raise ValueError("available_at cannot precede reported_at")

    filing_type = _required_text(record, "filing_type").upper()
    source_provider = _required_text(record, "source_provider")
    source_document_id = _required_text(record, "source_document_id")
    source_endpoint = _required_text(record, "source_endpoint")
    field = _required_text(record, "field")

    value = float(record.get("value"))
    if not math.isfinite(value):
        raise ValueError("value must be finite")
    unit = _required_text(record, "unit")
    currency = _required_text(record, "currency").upper()

    is_quarterly = _require_bool(record, "is_quarterly")
    is_derived = _require_bool(record, "is_derived")
    derivation_rule = str(record.get("derivation_rule", "")).strip()
    if is_derived and not derivation_rule:
        raise ValueError("derived events require derivation_rule")
    if not is_derived and derivation_rule:
        raise ValueError("source facts cannot declare derivation_rule")

    revision_sequence = int(record.get("revision_sequence", -1))
    if revision_sequence < 0:
        raise ValueError("revision_sequence must be >= 0")
    supersedes_event_id = str(record.get("supersedes_event_id", "")).strip().lower()
    if revision_sequence == 0 and supersedes_event_id:
        raise ValueError("initial events cannot supersede another event")
    if supersedes_event_id and not _SHA256.fullmatch(supersedes_event_id):
        raise ValueError("supersedes_event_id must be a SHA-256 hex digest")

    retrieved_at = _parse_timestamp(record.get("retrieved_at"), "retrieved_at")
    source_hash = _required_text(record, "source_hash").lower()
    if not _SHA256.fullmatch(source_hash):
        raise ValueError("source_hash must be a SHA-256 hex digest")

    normalized: dict[str, Any] = {
        "market": market,
        "symbol": symbol,
        "exchange": exchange,
        "entity_id": entity_id,
        "fiscal_period_end": fiscal_period_end,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "reported_at": reported_at,
        "available_at": available_at,
        "filing_type": filing_type,
        "source_provider": source_provider,
        "source_document_id": source_document_id,
        "source_endpoint": source_endpoint,
        "field": field,
        "value": value,
        "unit": unit,
        "currency": currency,
        "is_quarterly": is_quarterly,
        "is_derived": is_derived,
        "derivation_rule": derivation_rule,
        "revision_sequence": revision_sequence,
        "supersedes_event_id": supersedes_event_id,
        "retrieved_at": retrieved_at,
        "source_hash": source_hash,
    }
    expected_event_id = build_event_id(normalized)
    supplied_event_id = str(record.get("event_id", "")).strip().lower()
    if supplied_event_id and supplied_event_id != expected_event_id:
        raise ValueError("event_id does not match canonical event identity")
    normalized["event_id"] = expected_event_id
    return FundamentalEvent(**normalized)
