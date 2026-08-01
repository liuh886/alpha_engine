"""Canonical corporate-action event validation and identity."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
EVENT_TYPES = {
    "cash_dividend",
    "stock_dividend",
    "split",
    "reverse_split",
    "rights_issue",
    "secondary_issuance",
    "ticker_change",
    "exchange_change",
    "merger",
    "acquisition",
    "spin_off",
    "delisting",
    "suspension",
    "resumption",
    "etf_distribution",
    "etf_split",
}
RECONCILIATION_STATUSES = {
    "unverified",
    "source_only",
    "reconciled",
    "conflict",
    "not_applicable",
}


@dataclass(frozen=True)
class CorporateActionEvent:
    """One source-bound corporate-action observation."""

    market: str
    symbol: str
    exchange: str
    entity_id: str
    event_type: str
    announced_at: str
    ex_date: str
    record_date: str
    pay_date: str
    effective_date: str
    cash_amount: float | None
    currency: str
    split_ratio: float | None
    stock_dividend_ratio: float | None
    rights_ratio: float | None
    rights_price: float | None
    shares_before: float | None
    shares_after: float | None
    old_symbol: str
    new_symbol: str
    source_provider: str
    source_document_id: str
    source_endpoint: str
    retrieved_at: str
    source_hash: str
    revision_sequence: int
    supersedes_event_id: str
    confidence: float
    reconciliation_status: str
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(record: dict[str, Any], key: str, *, required: bool = True) -> str:
    value = str(record.get(key, "")).strip()
    if required and not value:
        raise ValueError(f"corporate action requires non-empty {key}")
    return value


def _optional_date(record: dict[str, Any], key: str) -> str:
    value = str(record.get(key, "")).strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date") from exc


def _optional_timestamp(record: dict[str, Any], key: str) -> str:
    value = str(record.get(key, "")).strip()
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO timestamp") from exc


def _optional_float(record: dict[str, Any], key: str) -> float | None:
    value = record.get(key)
    if value in (None, ""):
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    return parsed


def build_corporate_action_id(record: dict[str, Any]) -> str:
    identity = {
        "market": str(record["market"]).lower(),
        "symbol": str(record["symbol"]).upper(),
        "entity_id": str(record["entity_id"]),
        "event_type": str(record["event_type"]),
        "effective_date": str(record["effective_date"]),
        "ex_date": str(record.get("ex_date", "")),
        "source_provider": str(record["source_provider"]),
        "source_document_id": str(record["source_document_id"]),
        "revision_sequence": int(record["revision_sequence"]),
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_corporate_action(record: dict[str, Any]) -> CorporateActionEvent:
    market = _text(record, "market").lower()
    if market not in {"us", "cn"}:
        raise ValueError("market must be 'us' or 'cn'")
    symbol = _text(record, "symbol").upper()
    exchange = _text(record, "exchange").upper()
    entity_id = _text(record, "entity_id")
    event_type = _text(record, "event_type").lower()
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")

    announced_at = _optional_timestamp(record, "announced_at")
    ex_date = _optional_date(record, "ex_date")
    record_date = _optional_date(record, "record_date")
    pay_date = _optional_date(record, "pay_date")
    effective_date = _optional_date(record, "effective_date")
    if not effective_date:
        effective_date = ex_date
    if not effective_date:
        raise ValueError("corporate action requires effective_date or ex_date")

    cash_amount = _optional_float(record, "cash_amount")
    split_ratio = _optional_float(record, "split_ratio")
    stock_dividend_ratio = _optional_float(record, "stock_dividend_ratio")
    rights_ratio = _optional_float(record, "rights_ratio")
    rights_price = _optional_float(record, "rights_price")
    shares_before = _optional_float(record, "shares_before")
    shares_after = _optional_float(record, "shares_after")
    currency = _text(record, "currency", required=False).upper()

    if event_type in {"cash_dividend", "etf_distribution"}:
        if cash_amount is None or cash_amount < 0:
            raise ValueError("cash distribution requires non-negative cash_amount")
        if not currency:
            raise ValueError("cash distribution requires currency")
    if event_type in {"split", "reverse_split", "etf_split"}:
        if split_ratio is None or split_ratio <= 0:
            raise ValueError("split event requires positive split_ratio")
    if event_type == "stock_dividend":
        if stock_dividend_ratio is None or stock_dividend_ratio < 0:
            raise ValueError("stock dividend requires stock_dividend_ratio")
    if event_type == "rights_issue":
        if rights_ratio is None or rights_ratio < 0 or rights_price is None:
            raise ValueError("rights issue requires ratio and price")
    old_symbol = _text(record, "old_symbol", required=False).upper()
    new_symbol = _text(record, "new_symbol", required=False).upper()
    if event_type == "ticker_change" and (not old_symbol or not new_symbol):
        raise ValueError("ticker change requires old_symbol and new_symbol")

    source_provider = _text(record, "source_provider")
    source_document_id = _text(record, "source_document_id")
    source_endpoint = _text(record, "source_endpoint")
    retrieved_at = _optional_timestamp(record, "retrieved_at")
    if not retrieved_at:
        raise ValueError("retrieved_at is required")
    source_hash = _text(record, "source_hash").lower()
    if not _SHA256.fullmatch(source_hash):
        raise ValueError("source_hash must be a SHA-256 digest")

    revision_sequence = int(record.get("revision_sequence", -1))
    if revision_sequence < 0:
        raise ValueError("revision_sequence must be >= 0")
    supersedes_event_id = _text(
        record,
        "supersedes_event_id",
        required=False,
    ).lower()
    if revision_sequence == 0 and supersedes_event_id:
        raise ValueError("initial event cannot supersede another event")
    if supersedes_event_id and not _SHA256.fullmatch(supersedes_event_id):
        raise ValueError("supersedes_event_id must be a SHA-256 digest")

    confidence = float(record.get("confidence", 0.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    reconciliation_status = _text(record, "reconciliation_status").lower()
    if reconciliation_status not in RECONCILIATION_STATUSES:
        raise ValueError("unsupported reconciliation_status")

    normalized: dict[str, Any] = {
        "market": market,
        "symbol": symbol,
        "exchange": exchange,
        "entity_id": entity_id,
        "event_type": event_type,
        "announced_at": announced_at,
        "ex_date": ex_date,
        "record_date": record_date,
        "pay_date": pay_date,
        "effective_date": effective_date,
        "cash_amount": cash_amount,
        "currency": currency,
        "split_ratio": split_ratio,
        "stock_dividend_ratio": stock_dividend_ratio,
        "rights_ratio": rights_ratio,
        "rights_price": rights_price,
        "shares_before": shares_before,
        "shares_after": shares_after,
        "old_symbol": old_symbol,
        "new_symbol": new_symbol,
        "source_provider": source_provider,
        "source_document_id": source_document_id,
        "source_endpoint": source_endpoint,
        "retrieved_at": retrieved_at,
        "source_hash": source_hash,
        "revision_sequence": revision_sequence,
        "supersedes_event_id": supersedes_event_id,
        "confidence": confidence,
        "reconciliation_status": reconciliation_status,
    }
    event_id = build_corporate_action_id(normalized)
    supplied = _text(record, "event_id", required=False).lower()
    if supplied and supplied != event_id:
        raise ValueError("event_id does not match canonical corporate action")
    normalized["event_id"] = event_id
    return CorporateActionEvent(**normalized)
