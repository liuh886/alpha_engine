from __future__ import annotations

import pandas as pd

from src.data.company_events.ashare_holding_change_events import (
    classify_holding_change_title,
    cninfo_holding_change_to_events,
)


def test_holding_change_classifier_separates_plan_and_execution() -> None:
    assert classify_holding_change_title("关于控股股东增持计划的公告") == "increase_plan"
    assert classify_holding_change_title("关于控股股东增持股份进展的公告") == "increase_execution"
    assert classify_holding_change_title("关于董事减持计划的预披露公告") == "decrease_plan"
    assert classify_holding_change_title("关于股东减持计划实施完毕的公告") == "decrease_execution"


def test_holding_change_classifier_handles_cninfo_markup() -> None:
    assert (
        classify_holding_change_title("关于股东<em>减持</em>计划时间过半的进展公告")
        == "decrease_execution"
    )
    assert (
        classify_holding_change_title("关于董事长拟<em>增持</em>公司股份的公告")
        == "increase_plan"
    )


def test_holding_change_classifier_excludes_non_discretionary_events() -> None:
    assert classify_holding_change_title("关于回购注销限制性股票导致持股比例被动增加的公告") is None
    assert classify_holding_change_title("关于股东所持股份司法拍卖暨被动减持的公告") is None
    assert classify_holding_change_title("关于股东股份解除质押及减持计划的公告") is None
    assert classify_holding_change_title("证券公司关于股东减持计划的核查意见") is None


def test_holding_change_adapter_deduplicates_keyword_queries() -> None:
    increase = pd.DataFrame(
        {
            "代码": ["000001", "000001"],
            "公告标题": ["关于控股股东增持计划的公告摘要", "关于控股股东增持计划的公告"],
            "公告时间": ["2024-01-15", "2024-01-15"],
            "announcementId": ["summary", "full"],
            "公告链接": ["https://www.cninfo.com.cn/summary", "https://www.cninfo.com.cn/full"],
        }
    )
    duplicate_query = pd.DataFrame(
        {
            "代码": ["000001"],
            "公告标题": ["关于控股股东增持计划的公告"],
            "公告时间": ["2024-01-15"],
            "announcementId": ["full"],
            "公告链接": ["https://www.cninfo.com.cn/full"],
        }
    )

    events = cninfo_holding_change_to_events(
        [increase, duplicate_query],
        sessions=["2024-01-15", "2024-01-16"],
        retrieved_at="2026-08-05T15:15:00+00:00",
        allowed_symbols=["000001"],
    )

    assert len(events) == 1
    assert events[0].source_document_id == "full"
    assert events[0].event_stage == "increase_plan"
    assert events[0].first_eligible_session == "2024-01-16"


def test_distinct_plan_and_execution_on_same_date_are_retained() -> None:
    frame = pd.DataFrame(
        {
            "代码": ["600000", "600000"],
            "公告标题": ["关于股东减持计划的公告", "关于股东减持计划实施完毕的公告"],
            "公告时间": ["2024-02-01", "2024-02-01"],
            "announcementId": ["plan", "execution"],
            "公告链接": ["https://www.cninfo.com.cn/plan", "https://www.cninfo.com.cn/execution"],
        }
    )

    events = cninfo_holding_change_to_events(
        [frame],
        sessions=["2024-02-01", "2024-02-02"],
        retrieved_at="2026-08-05T15:15:00+00:00",
        allowed_symbols=["600000"],
    )

    assert {event.event_stage for event in events} == {
        "decrease_plan",
        "decrease_execution",
    }
