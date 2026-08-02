from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pandas as pd

from src.data.fundamentals.event_store import FundamentalEvent, normalize_event_record

CST = timezone(timedelta(hours=8))


def _hash(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _timestamp(date_text: str) -> tuple[str, str]:
    reported = datetime.strptime(date_text, "%Y%m%d").replace(tzinfo=CST)
    available = reported + timedelta(days=1)
    return reported.isoformat(), available.isoformat()


def _period(value: str) -> tuple[int, str, bool]:
    date_value = datetime.strptime(value, "%Y%m%d").date()
    period = {
        3: "Q1",
        6: "Q2",
        9: "Q3",
        12: "FY",
    }.get(date_value.month, "FY")
    return date_value.year, period, period != "FY"


def tushare_indicator_to_events(
    frame: pd.DataFrame,
    *,
    symbol: str,
    ts_code: str,
    exchange: str,
    field_map: Mapping[str, Mapping[str, str]],
    retrieved_at: str,
) -> list[FundamentalEvent]:
    """Normalize Tushare observations for validation, not primary training.

    Downstream model-data profiles must exclude source_provider values prefixed
    with ``tushare_validation_`` from canonical fundamentals. They exist only to
    compare field values and announcement timing against the public primary
    path.
    """

    events: list[FundamentalEvent] = []
    for raw in frame.to_dict(orient="records"):
        announcement = str(raw.get("f_ann_date") or raw.get("ann_date") or "").strip()
        period_end = str(raw.get("end_date") or "").strip()
        if not announcement or not period_end:
            continue
        try:
            reported_at, available_at = _timestamp(announcement)
            fiscal_year, fiscal_period, quarterly = _period(period_end)
        except ValueError:
            continue
        for source_field, definition in field_map.items():
            value = raw.get(source_field)
            if value is None or pd.isna(value):
                continue
            try:
                event = normalize_event_record(
                    {
                        "market": "cn",
                        "symbol": symbol,
                        "exchange": exchange,
                        "entity_id": ts_code,
                        "fiscal_period_end": datetime.strptime(
                            period_end, "%Y%m%d"
                        ).date().isoformat(),
                        "fiscal_year": fiscal_year,
                        "fiscal_period": fiscal_period,
                        "reported_at": reported_at,
                        "available_at": available_at,
                        "filing_type": "PERIODIC_REPORT",
                        "source_provider": "tushare_validation_fina_indicator",
                        "source_document_id": (
                            f"{ts_code}:{announcement}:{period_end}:{source_field}"
                        ),
                        "source_endpoint": "fina_indicator",
                        "field": str(definition["field"]),
                        "value": float(value),
                        "unit": str(definition["unit"]),
                        "currency": str(definition.get("currency", "CNY")),
                        "is_quarterly": quarterly,
                        "is_derived": False,
                        "derivation_rule": "",
                        "revision_sequence": 0,
                        "supersedes_event_id": "",
                        "retrieved_at": retrieved_at,
                        "source_hash": _hash(raw),
                    }
                )
            except (TypeError, ValueError):
                continue
            events.append(event)
    unique = {event.event_id: event for event in events}
    return sorted(
        unique.values(),
        key=lambda event: (
            event.available_at,
            event.symbol,
            event.field,
            event.fiscal_period_end,
        ),
    )
