from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from src.data.fundamentals.event_store import FundamentalEvent, normalize_event_record

SEC_DATA_ROOT = "https://data.sec.gov"


class SecCompanyFactsError(ValueError):
    pass


@dataclass
class SecCompanyFactsClient:
    user_agent: str
    timeout_seconds: float = 30.0
    data_root: str = SEC_DATA_ROOT

    def fetch_companyfacts(self, cik: str) -> dict[str, Any]:
        normalized = str(cik).strip().zfill(10)
        url = f"{self.data_root.rstrip('/')}/api/xbrl/companyfacts/CIK{normalized}.json"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SecCompanyFactsError(
                f"SEC companyfacts HTTP {exc.code} for CIK{normalized}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise SecCompanyFactsError(
                f"SEC companyfacts request failed for CIK{normalized}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SecCompanyFactsError("SEC companyfacts payload must be a mapping")
        time.sleep(0.11)
        return payload


def _source_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _availability(filed: str) -> tuple[str, str]:
    filed_date = datetime.strptime(filed, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    reported_at = filed_date.isoformat()
    available_at = (filed_date + timedelta(days=1)).isoformat()
    return reported_at, available_at


def _fiscal_period(row: Mapping[str, Any]) -> tuple[int, str, bool]:
    fy = int(row.get("fy") or str(row.get("end", ""))[:4])
    fp = str(row.get("fp") or "FY").upper()
    quarterly = fp in {"Q1", "Q2", "Q3"}
    return fy, fp, quarterly


def companyfacts_to_events(
    payload: Mapping[str, Any],
    *,
    symbol: str,
    cik: str,
    exchange: str,
    field_map: Mapping[str, Mapping[str, str]],
    retrieved_at: str,
) -> list[FundamentalEvent]:
    """Convert official SEC company facts into conservative PIT events."""

    entity_cik = str(payload.get("cik") or cik).strip().zfill(10)
    facts = payload.get("facts", {})
    if not isinstance(facts, dict):
        raise SecCompanyFactsError("SEC companyfacts facts must be a mapping")
    taxonomy = facts.get("us-gaap", {})
    if not isinstance(taxonomy, dict):
        return []

    events: list[FundamentalEvent] = []
    for concept, definition in field_map.items():
        concept_payload = taxonomy.get(concept)
        if not isinstance(concept_payload, dict):
            continue
        units = concept_payload.get("units", {})
        if not isinstance(units, dict):
            continue
        expected_unit = str(definition.get("unit", ""))
        preferred_units = [expected_unit, "USD", "USD/shares", "shares", "pure"]
        selected_rows: list[dict[str, Any]] = []
        selected_unit = ""
        for unit in preferred_units:
            rows = units.get(unit)
            if isinstance(rows, list) and rows:
                selected_rows = [row for row in rows if isinstance(row, dict)]
                selected_unit = unit
                break
        for row in selected_rows:
            form = str(row.get("form", "")).upper()
            filed = str(row.get("filed", ""))
            end = str(row.get("end", ""))
            accession = str(row.get("accn", ""))
            if form not in {"10-Q", "10-K", "20-F", "40-F", "6-K"}:
                continue
            if not filed or not end or not accession or row.get("val") is None:
                continue
            try:
                reported_at, available_at = _availability(filed)
                fiscal_year, fiscal_period, is_quarterly = _fiscal_period(row)
                event = normalize_event_record(
                    {
                        "market": "us",
                        "symbol": symbol,
                        "exchange": exchange,
                        "entity_id": f"CIK{entity_cik}",
                        "fiscal_period_end": end,
                        "fiscal_year": fiscal_year,
                        "fiscal_period": fiscal_period,
                        "reported_at": reported_at,
                        "available_at": available_at,
                        "filing_type": form,
                        "source_provider": "sec_companyfacts",
                        "source_document_id": accession,
                        "source_endpoint": f"api/xbrl/companyfacts/CIK{entity_cik}.json",
                        "field": str(definition["field"]),
                        "value": float(row["val"]),
                        "unit": selected_unit or expected_unit,
                        "currency": str(definition.get("currency", "USD")),
                        "is_quarterly": is_quarterly,
                        "is_derived": False,
                        "derivation_rule": "",
                        "revision_sequence": 0,
                        "supersedes_event_id": "",
                        "retrieved_at": retrieved_at,
                        "source_hash": _source_hash(row),
                    }
                )
            except (ValueError, TypeError):
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
