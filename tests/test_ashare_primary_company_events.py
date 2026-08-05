from __future__ import annotations

import pandas as pd

from src.data.company_events.ashare_primary_announcements import (
    classify_buyback_title,
    classify_restricted_unlock_title,
    cninfo_primary_announcements_to_events,
    is_expected_empty_cninfo_error,
)


def test_buyback_title_classifier_orders_specific_stages() -> None:
    assert classify_buyback_title("关于首次回购公司股份的公告") == "first_execution"
    assert classify_buyback_title("关于回购公司股份进展暨累计回购的公告") == "progress"
    assert classify_buyback_title("关于股份回购实施完成的公告") == "completion"
    assert classify_buyback_title("2023年第一次临时股东大会审议通过回购方案") == "approval"
    assert classify_buyback_title("关于董事会提议回购公司股份的公告") == "plan"


def test_buyback_classifier_excludes_equity_incentive_cancellations() -> None:
    assert classify_buyback_title("关于回购注销部分限制性股票的公告") is None
    assert classify_buyback_title("关于股票质押式回购交易的公告") is None


def test_unlock_classifier_keeps_only_listing_events() -> None:
    assert classify_restricted_unlock_title("首次公开发行限售股份上市流通公告") == "scheduled"
    assert classify_restricted_unlock_title("部分限售股份解除限售暨上市流通提示性公告") == "scheduled"
    assert classify_restricted_unlock_title("限制性股票解除限售条件成就的公告") is None


def test_primary_adapter_prefers_full_document_over_summary() -> None:
    frame = pd.DataFrame(
        {
            "代码": ["000001", "000001"],
            "公告标题": [
                "关于首次回购公司股份的公告摘要",
                "关于首次回购公司股份的公告",
            ],
            "公告时间": ["2024-01-15", "2024-01-15"],
            "announcementId": ["summary", "full"],
            "orgId": ["gssz0000001", "gssz0000001"],
            "公告链接": ["https://www.cninfo.com.cn/summary", "https://www.cninfo.com.cn/full"],
        }
    )

    events = cninfo_primary_announcements_to_events(
        frame,
        family="buyback",
        sessions=["2024-01-15", "2024-01-16"],
        retrieved_at="2026-08-05T14:00:00+00:00",
        allowed_symbols=["000001"],
    )

    assert len(events) == 1
    assert events[0].source_document_id == "full"
    assert events[0].first_eligible_session == "2024-01-16"
    assert events[0].event_stage == "first_execution"


def test_multiple_buyback_stages_on_same_date_are_not_collapsed() -> None:
    frame = pd.DataFrame(
        {
            "代码": ["600000", "600000"],
            "公告标题": ["关于首次回购公司股份的公告", "关于回购公司股份进展的公告"],
            "公告时间": ["2024-02-01", "2024-02-01"],
            "announcementId": ["first", "progress"],
            "公告链接": ["https://www.cninfo.com.cn/first", "https://www.cninfo.com.cn/progress"],
        }
    )

    events = cninfo_primary_announcements_to_events(
        frame,
        family="buyback",
        sessions=["2024-02-01", "2024-02-02"],
        retrieved_at="2026-08-05T14:00:00+00:00",
        allowed_symbols=["600000"],
    )

    assert {event.event_stage for event in events} == {"first_execution", "progress"}


def test_expected_empty_cninfo_error_is_narrow() -> None:
    expected = KeyError(
        "None of [Index(['代码', '简称', '公告标题', '公告时间', 'announcementId', 'orgId'])] are in the [columns]"
    )
    unexpected = KeyError("missing arbitrary schema column")

    assert is_expected_empty_cninfo_error(expected)
    assert not is_expected_empty_cninfo_error(unexpected)
