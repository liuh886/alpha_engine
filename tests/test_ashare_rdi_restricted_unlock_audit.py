"""Read-only restricted_unlock coverage audit; synthetic fixtures only."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.company_events.ashare_primary_announcements import (
    cninfo_primary_announcements_to_events,
)
from src.data.company_events.event_store import normalize_company_information_event
from src.research.ashare_rdi.restricted_unlock_audit import (
    adapter_capability_audit,
    audit_restricted_unlock_records,
    build_receipt,
)

SESSIONS = ["2024-01-15", "2024-01-16", "2024-01-17", "2024-01-18"]
POOL_SHA = "c" * 64


def _canonical(**overrides: object) -> dict[str, object]:
    payload = {
        "title": "关于首次公开发行限售股份上市流通的公告",
        "announcement_id": "ann-1",
        "primary_link": "https://www.cninfo.com.cn/ann-1",
        "amendment_absence_checked": True,
    }
    payload.update(overrides.pop("payload", {}))  # type: ignore[arg-type]
    record: dict[str, object] = {
        "market": "cn",
        "symbol": "000001",
        "exchange": "SZSE",
        "entity_id": "CN:SZSE:000001",
        "event_family": "restricted_unlock",
        "event_stage": "scheduled",
        "fiscal_period_end": "",
        "announced_at": "2024-01-15T00:00:00+08:00",
        "first_eligible_session": "2024-01-17",
        "effective_date": "2024-01-18",
        "payload_schema": "cninfo_restricted_unlock_announcement_v1",
        "payload": payload,
        "source_provider": "cninfo_via_akshare",
        "source_document_id": "doc-1",
        "source_endpoint": "stock_zh_a_disclosure_report_cninfo",
        "retrieved_at": "2024-01-16T09:00:00+08:00",
        "source_hash": "a" * 64,
        "revision_sequence": 0,
        "supersedes_event_id": "",
        "confidence": 1.0,
        "reconciliation_status": "reconciled",
        "availability_status": "usable",
    }
    record.update(overrides)
    normalized = normalize_company_information_event(record).to_dict()
    for extra in ("available_at", "story_id"):
        if extra in record:
            normalized[extra] = record[extra]
    return normalized


def _complete() -> dict[str, object]:
    record = _canonical()
    record["available_at"] = "2024-01-15T16:30:00+08:00"
    record["story_id"] = "story-1"
    return record


def _manifest() -> dict[str, object]:
    return {
        "pool_id": "cn_selected_equities_v3",
        "pool_sha256": POOL_SHA,
        "period_start": "2024-01-01",
        "cutoff": "2024-01-31",
        "pit_membership_verified": True,
    }


def _coverage(sessions: list[str], *, verified: bool = True) -> list[dict[str, object]]:
    return [
        {
            "session": session,
            "family": "restricted_unlock",
            "state": "verified" if verified else "unknown",
            "source_id": "cninfo-archive",
            "source_sha256": "b" * 64,
            "point_in_time_archive_verified": verified,
        }
        for session in sessions
    ]


def _audit(records, **overrides):
    values = {
        "sessions": SESSIONS,
        "coverage_rows": _coverage(SESSIONS),
        "archive_manifest": _manifest(),
        "declared_universe": "cn_selected_equities_v3",
        "declared_pool_symbols": ["000001"],
        "declared_pool_sha256": POOL_SHA,
        "declared_start": "2024-01-01",
        "declared_cutoff": "2024-01-31",
    }
    values.update(overrides)
    return audit_restricted_unlock_records(records, **values)


def test_empty_archive_is_blocked_and_missing_is_not_zero() -> None:
    result = _audit([], coverage_rows=[], archive_manifest=None)

    assert result["status"] == "BLOCKED"
    assert result["record_inventory"]["archive_present"] is False
    assert result["record_inventory"]["valid_restricted_unlock_records"] == 0
    assert all(
        field["status"] == "missing"
        for field in result["required_fields"].values()
    )
    assert any(
        gap["field"] == "event_archive" for gap in result["gaps"]
    )


def test_complete_synthetic_archive_can_be_ready() -> None:
    result = _audit([_complete()])

    assert result["status"] == "READY"
    assert all(
        field["status"] == "evidenced"
        for field in result["required_fields"].values()
    )
    assert result["record_inventory"]["duplicate_event_ids"] == []


def test_adapter_shaped_records_are_blocked_with_exact_field_gaps() -> None:
    frame = pd.DataFrame(
        {
            "代码": ["000001"],
            "公告标题": ["首次公开发行限售股份上市流通公告"],
            "公告时间": ["2024-01-15"],
            "announcementId": ["ann-1"],
            "orgId": ["org-1"],
            "公告链接": ["https://www.cninfo.com.cn/ann-1"],
        }
    )
    events = cninfo_primary_announcements_to_events(
        frame,
        family="restricted_unlock",
        sessions=SESSIONS,
        retrieved_at="2024-01-16T09:00:00+08:00",
        allowed_symbols=["000001"],
    )
    result = _audit([event.to_dict() for event in events])

    assert result["status"] == "BLOCKED"
    fields = result["required_fields"]
    assert fields["original_announcement_identity"]["status"] == "evidenced"
    assert fields["source_evidence_hash"]["status"] == "evidenced"
    for name in (
        "first_public_availability",
        "story_identity_and_dedup",
        "effective_unlock_session",
        "amendment_chain",
        "as_of_known_future_schedule",
    ):
        assert fields[name]["status"] == "missing", name


def test_duplicate_event_identity_is_not_story_deduplication() -> None:
    record = _complete()
    result = _audit([record, dict(record)])

    assert result["status"] == "BLOCKED"
    assert len(result["record_inventory"]["duplicate_event_ids"]) == 1
    assert (
        result["required_fields"]["story_identity_and_dedup"]["status"]
        == "missing"
    )


def test_unverified_coverage_blocks_even_with_complete_records() -> None:
    result = _audit(
        [_complete()],
        coverage_rows=_coverage(SESSIONS, verified=False),
    )

    assert result["status"] == "BLOCKED"
    assert (
        result["required_fields"]["per_session_completeness_or_absence"]["status"]
        == "missing"
    )
    assert result["per_session_coverage"]["usable_cells"] == 0
    assert any(
        gap["field"] == "per_session_completeness_or_absence"
        for gap in result["gaps"]
    )


def test_manifest_without_pit_membership_is_not_universe_evidence() -> None:
    manifest = _manifest()
    manifest["pit_membership_verified"] = False
    result = _audit([_complete()], archive_manifest=manifest)

    assert result["status"] == "BLOCKED"
    field = result["required_fields"]["declared_universe_era_pit_membership"]
    assert field["status"] == "missing"
    assert "pit_membership_not_verified" in field["failures"]


def test_records_outside_declared_universe_are_rejected_as_coverage() -> None:
    result = _audit([_complete()], declared_pool_symbols=["600000"])

    field = result["required_fields"]["declared_universe_era_pit_membership"]
    assert field["status"] == "missing"
    assert any(
        failure.startswith("records_outside_declared_universe")
        for failure in field["failures"]
    )


def test_non_restricted_unlock_records_are_ignored_not_counted() -> None:
    buyback = _canonical(event_family="buyback", event_stage="plan")
    result = _audit([buyback])

    assert result["record_inventory"]["valid_restricted_unlock_records"] == 0
    assert result["record_inventory"]["ignored_records"][0]["reason"].startswith(
        "unsupported_family:buyback"
    )


def test_adapter_capability_audit_only_flags_present_tokens() -> None:
    text = (
        'story_id\n'
        'def _timestamp(date_text: str) -> str:\n'
        '"effective_date": effective_date,\n'
        '"revision_sequence": revision,\n'
    )
    observations = {
        row["id"]: row for row in adapter_capability_audit(text)["observations"]
    }

    assert observations["story_identity_not_represented"]["detected"] is False
    assert observations["effective_unlock_session_not_parsed"]["detected"] is False
    assert observations["amendment_chain_not_represented"]["detected"] is False
    assert observations["first_public_availability_not_captured"]["detected"] is True


def test_receipt_builder_is_deterministic_and_blocked() -> None:
    root = Path(__file__).resolve().parents[1]
    kwargs = {
        "records_path": None,
        "coverage_path": None,
        "archive_manifest_path": None,
        "period_start": "2022-01-01",
        "cutoff": "2026-08-03",
        "receipt_date": "2026-11-16",
        "repository_commit": "0" * 40,
    }
    first = build_receipt(root, **kwargs)
    second = build_receipt(root, **kwargs)

    assert first == second
    assert first["status"] == "BLOCKED"
    assert first["research_only"] is True
    assert first["trade_ready"] is False
    assert first["record_inventory"]["archive_present"] is False
    assert any(
        gap["field"] == "event_archive" for gap in first["gaps"]
    )
    assert first["does_not_claim"]
