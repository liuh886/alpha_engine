from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from src.data.company_events.ashare_earnings_events import (
    cninfo_disclosure_index,
    eastmoney_earnings_forecast_to_events,
    eastmoney_preliminary_earnings_to_events,
    first_session_strictly_after,
)
from src.data.company_events.event_store import (
    build_company_information_event_id,
    normalize_company_information_event,
)


def _event() -> dict[str, object]:
    return {
        "market": "cn",
        "symbol": "000001",
        "exchange": "SZSE",
        "entity_id": "CN:SZSE:000001",
        "event_family": "earnings_forecast",
        "event_stage": "forecast_initial",
        "fiscal_period_end": "2023-12-31",
        "announced_at": "2024-01-15T00:00:00+08:00",
        "first_eligible_session": "2024-01-16",
        "effective_date": "",
        "payload_schema": "fixture_v1",
        "payload": {"forecast_type": "预增"},
        "source_provider": "fixture",
        "source_document_id": "https://example.test/a",
        "source_endpoint": "fixture",
        "retrieved_at": "2026-08-05T13:00:00+00:00",
        "source_hash": hashlib.sha256(b"fixture").hexdigest(),
        "revision_sequence": 0,
        "supersedes_event_id": "",
        "confidence": 1.0,
        "reconciliation_status": "reconciled",
        "availability_status": "usable",
        "event_id": "",
    }


def test_identity_is_deterministic_and_dates_are_separate() -> None:
    first = normalize_company_information_event(_event())
    second = normalize_company_information_event(_event())

    assert first == second
    assert first.event_id == build_company_information_event_id(first.to_dict())
    assert first.announced_at[:10] == "2024-01-15"
    assert first.first_eligible_session == "2024-01-16"
    assert first.effective_date == ""


def test_first_session_must_be_strictly_after_announcement() -> None:
    payload = _event()
    payload["first_eligible_session"] = "2024-01-15"

    with pytest.raises(ValueError, match="strictly after"):
        normalize_company_information_event(payload)


def test_revision_requires_supersession_link() -> None:
    payload = _event()
    payload["revision_sequence"] = 1
    payload["event_stage"] = "forecast_revision"

    with pytest.raises(ValueError, match="superseded event"):
        normalize_company_information_event(payload)


def test_only_reconciled_events_can_be_usable() -> None:
    payload = _event()
    payload["reconciliation_status"] = "missing_primary"

    with pytest.raises(ValueError, match="only reconciled"):
        normalize_company_information_event(payload)


def test_first_eligible_session_uses_strict_calendar_boundary() -> None:
    sessions = ["2024-01-12", "2024-01-15", "2024-01-16"]

    assert first_session_strictly_after("2024-01-15", sessions) == "2024-01-16"
    assert first_session_strictly_after("2024-01-16", sessions) == ""


def test_forecast_groups_multiple_structured_rows_and_reconciles_primary() -> None:
    structured = pd.DataFrame(
        {
            "股票代码": ["000001", "000001"],
            "股票简称": ["平安银行", "平安银行"],
            "预测指标": ["净利润", "营业收入"],
            "预告类型": ["预增", "预增"],
            "公告日期": ["2024-01-15", "2024-01-15"],
        }
    )
    primary = pd.DataFrame(
        {
            "代码": ["000001"],
            "公告标题": ["平安银行2023年度业绩预告"],
            "公告时间": ["2024-01-15"],
            "公告链接": ["https://www.cninfo.com.cn/a"],
        }
    )
    disclosures = cninfo_disclosure_index(primary, family="earnings_forecast")

    events = eastmoney_earnings_forecast_to_events(
        structured,
        fiscal_period_end="2023-12-31",
        disclosures=disclosures,
        sessions=["2024-01-15", "2024-01-16", "2024-01-17"],
        retrieved_at="2026-08-05T13:00:00+00:00",
        allowed_symbols=["000001"],
    )

    assert len(events) == 1
    event = events[0]
    assert event.reconciliation_status == "reconciled"
    assert event.availability_status == "usable"
    assert event.first_eligible_session == "2024-01-16"
    assert len(event.payload["structured_rows"]) == 2
    assert event.source_document_id == "https://www.cninfo.com.cn/a"


def test_preliminary_without_primary_is_retained_but_not_model_usable() -> None:
    structured = pd.DataFrame(
        {
            "股票代码": ["600000"],
            "股票简称": ["浦发银行"],
            "每股收益": [1.0],
            "公告日期": ["2024-02-01"],
        }
    )

    events = eastmoney_preliminary_earnings_to_events(
        structured,
        fiscal_period_end="2023-12-31",
        disclosures={},
        sessions=["2024-02-01", "2024-02-02"],
        retrieved_at="2026-08-05T13:00:00+00:00",
        allowed_symbols=["600000"],
    )

    assert len(events) == 1
    assert events[0].reconciliation_status == "missing_primary"
    assert events[0].availability_status == "partial"
