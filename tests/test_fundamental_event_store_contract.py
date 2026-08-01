import json
from pathlib import Path

import pytest

from scripts.data.audit_fundamental_coverage import audit
from src.data.fundamentals import build_event_id, normalize_event_record


def _event(symbol: str = "000001") -> dict:
    return {
        "market": "cn",
        "symbol": symbol,
        "exchange": "SZ",
        "entity_id": f"cn:{symbol}",
        "fiscal_period_end": "2025-12-31",
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "reported_at": "2026-03-20T18:00:00+08:00",
        "available_at": "2026-03-20T18:00:00+08:00",
        "filing_type": "ANNUAL_REPORT",
        "source_provider": "tushare",
        "source_document_id": f"income:{symbol}:20251231:0",
        "source_endpoint": "income",
        "field": "revenue",
        "value": 123456789.0,
        "unit": "CNY",
        "currency": "CNY",
        "is_quarterly": False,
        "is_derived": False,
        "derivation_rule": "",
        "revision_sequence": 0,
        "supersedes_event_id": "",
        "retrieved_at": "2026-08-01T12:00:00+00:00",
        "source_hash": "a" * 64,
        "event_id": "",
    }


def test_event_identity_is_deterministic() -> None:
    first = normalize_event_record(_event())
    second = normalize_event_record(_event())

    assert first == second
    assert first.event_id == build_event_id(first.to_dict())
    assert len(first.event_id) == 64


def test_event_rejects_availability_before_public_report() -> None:
    payload = _event()
    payload["available_at"] = "2026-03-19T18:00:00+08:00"

    with pytest.raises(ValueError, match="available_at cannot precede"):
        normalize_event_record(payload)


def test_source_fact_cannot_hide_a_derivation() -> None:
    payload = _event()
    payload["derivation_rule"] = "revenue - cost_of_revenue"

    with pytest.raises(ValueError, match="source facts cannot"):
        normalize_event_record(payload)


def test_derived_event_requires_a_rule() -> None:
    payload = _event()
    payload["is_derived"] = True

    with pytest.raises(ValueError, match="derived events require"):
        normalize_event_record(payload)


def test_coverage_report_enumerates_all_selected_candidates(tmp_path: Path) -> None:
    event = normalize_event_record(_event()).to_dict()
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")

    report = audit(Path.cwd(), market="cn", events_path=events)

    assert report["pool_id"] == "cn_selected_equities_v3"
    assert report["candidate_count"] == 130
    assert report["reported_candidate_count"] == 130
    assert report["complete_candidate_enumeration"] is True
    assert report["symbols_with_events"] == 1
    assert report["symbols_without_events"] == 129
    assert report["coverage"]["000001"]["event_count"] == 1
    assert report["coverage"]["000063"]["status"] == "no_events"


def test_coverage_rejects_symbols_outside_selected_pool(tmp_path: Path) -> None:
    event = normalize_event_record(_event("999999")).to_dict()
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside selected pool"):
        audit(Path.cwd(), market="cn", events_path=events)
