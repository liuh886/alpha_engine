from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

import pandas as pd

from src.data.corporate_actions.event_store import (
    CorporateActionEvent,
    normalize_corporate_action,
)


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def yfinance_actions_to_corporate_actions(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    entity_id: str,
    retrieved_at: str,
) -> list[CorporateActionEvent]:
    """Convert Yahoo explicit dividend/split rows; never infer from prices."""

    if frame is None or frame.empty:
        return []
    source = frame.copy().reset_index()
    date_column = next(
        (name for name in ("Date", "date", "index") if name in source.columns),
        None,
    )
    if date_column is None:
        return []
    events: list[CorporateActionEvent] = []
    for raw in source.to_dict(orient="records"):
        parsed = pd.to_datetime(raw.get(date_column), errors="coerce", utc=True)
        if pd.isna(parsed):
            continue
        effective_date = parsed.date().isoformat()
        announced_at = datetime.combine(
            parsed.date(), datetime.min.time(), tzinfo=timezone.utc
        ).isoformat()
        dividend = pd.to_numeric(raw.get("Dividends", raw.get("dividends", 0.0)), errors="coerce")
        split = pd.to_numeric(
            raw.get("Stock Splits", raw.get("stock splits", 0.0)), errors="coerce"
        )
        common = {
            "market": "us",
            "symbol": symbol,
            "exchange": exchange,
            "entity_id": entity_id,
            "announced_at": announced_at,
            "ex_date": effective_date,
            "record_date": "",
            "pay_date": "",
            "effective_date": effective_date,
            "currency": "USD",
            "old_symbol": "",
            "new_symbol": "",
            "source_provider": "yfinance_actions",
            "source_document_id": f"yahoo:{symbol}:{effective_date}",
            "source_endpoint": "Ticker.actions",
            "retrieved_at": retrieved_at,
            "revision_sequence": 0,
            "supersedes_event_id": "",
            "confidence": 0.8,
            "reconciliation_status": "source_only",
        }
        if pd.notna(dividend) and float(dividend) > 0:
            payload = {
                **common,
                "event_type": "cash_dividend",
                "cash_amount": float(dividend),
                "split_ratio": None,
                "stock_dividend_ratio": None,
                "rights_ratio": None,
                "rights_price": None,
                "shares_before": None,
                "shares_after": None,
                "source_hash": _hash({"row": raw, "kind": "cash_dividend"}),
            }
            events.append(normalize_corporate_action(payload))
        if pd.notna(split) and float(split) > 0:
            payload = {
                **common,
                "event_type": "split" if float(split) >= 1 else "reverse_split",
                "cash_amount": None,
                "split_ratio": float(split),
                "stock_dividend_ratio": None,
                "rights_ratio": None,
                "rights_price": None,
                "shares_before": None,
                "shares_after": None,
                "source_hash": _hash({"row": raw, "kind": "split"}),
            }
            events.append(normalize_corporate_action(payload))
    unique = {event.event_id: event for event in events}
    return sorted(unique.values(), key=lambda event: (event.effective_date, event.event_type))


def fetch_yfinance_actions(symbol: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except Exception as exc:
        raise RuntimeError(f"yfinance import failed: {exc}") from exc
    frame = yf.Ticker(symbol).actions
    return frame.copy() if frame is not None else pd.DataFrame()
