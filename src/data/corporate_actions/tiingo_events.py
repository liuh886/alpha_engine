from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

import pandas as pd

from src.data.corporate_actions.event_store import (
    CorporateActionEvent,
    normalize_corporate_action,
)


def _hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def tiingo_bars_to_corporate_actions(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    entity_id: str,
    retrieved_at: str,
) -> list[CorporateActionEvent]:
    """Extract only explicit Tiingo action fields; never infer from price jumps."""

    if not {"date", "cash_distribution", "split_factor"}.issubset(frame.columns):
        return []
    actions: list[CorporateActionEvent] = []
    for raw in frame.to_dict(orient="records"):
        date_value = pd.to_datetime(raw.get("date"), errors="coerce")
        if pd.isna(date_value):
            continue
        effective = pd.Timestamp(date_value).date().isoformat()
        cash = pd.to_numeric(raw.get("cash_distribution"), errors="coerce")
        split = pd.to_numeric(raw.get("split_factor"), errors="coerce")
        source_hash = _hash(raw)
        if not pd.isna(cash) and float(cash) != 0.0:
            actions.append(
                normalize_corporate_action(
                    {
                        "market": "us",
                        "symbol": symbol,
                        "exchange": exchange,
                        "entity_id": entity_id,
                        "event_type": "cash_dividend",
                        "announced_at": "",
                        "ex_date": effective,
                        "record_date": "",
                        "pay_date": "",
                        "effective_date": effective,
                        "cash_amount": float(cash),
                        "currency": "USD",
                        "split_ratio": None,
                        "stock_dividend_ratio": None,
                        "rights_ratio": None,
                        "rights_price": None,
                        "shares_before": None,
                        "shares_after": None,
                        "old_symbol": "",
                        "new_symbol": "",
                        "source_provider": "tiingo",
                        "source_document_id": f"tiingo:{symbol}:{effective}:cash",
                        "source_endpoint": f"tiingo/daily/{symbol}/prices",
                        "retrieved_at": retrieved_at,
                        "source_hash": source_hash,
                        "revision_sequence": 0,
                        "supersedes_event_id": "",
                        "confidence": 0.95,
                        "reconciliation_status": "source_only",
                    }
                )
            )
        if not pd.isna(split) and float(split) != 1.0:
            event_type = "split" if float(split) > 1.0 else "reverse_split"
            actions.append(
                normalize_corporate_action(
                    {
                        "market": "us",
                        "symbol": symbol,
                        "exchange": exchange,
                        "entity_id": entity_id,
                        "event_type": event_type,
                        "announced_at": "",
                        "ex_date": effective,
                        "record_date": "",
                        "pay_date": "",
                        "effective_date": effective,
                        "cash_amount": None,
                        "currency": "",
                        "split_ratio": float(split),
                        "stock_dividend_ratio": None,
                        "rights_ratio": None,
                        "rights_price": None,
                        "shares_before": None,
                        "shares_after": None,
                        "old_symbol": "",
                        "new_symbol": "",
                        "source_provider": "tiingo",
                        "source_document_id": f"tiingo:{symbol}:{effective}:split",
                        "source_endpoint": f"tiingo/daily/{symbol}/prices",
                        "retrieved_at": retrieved_at,
                        "source_hash": source_hash,
                        "revision_sequence": 0,
                        "supersedes_event_id": "",
                        "confidence": 0.95,
                        "reconciliation_status": "source_only",
                    }
                )
            )
    unique = {event.event_id: event for event in actions}
    return sorted(
        unique.values(), key=lambda event: (event.effective_date, event.event_type)
    )
