from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from scripts.data.populate_selected_pool_events import (
    _populate_us,
    _sec_mapping,
)
from src.data.cn_selected_pool_event_sources import (
    populate_cn_selected_pool_event_sources,
)

from src.data.corporate_actions.ashare_public_actions import (
    eastmoney_dividend_to_events,
)
from src.data.corporate_actions.tiingo_events import (
    tiingo_bars_to_corporate_actions,
)
from src.data.corporate_actions.yfinance_events import (
    yfinance_actions_to_corporate_actions,
)
from src.data.fundamentals.ashare_public_financials import (
    cninfo_period_disclosures,
    sina_statement_to_events,
)
from src.data.fundamentals.sec_companyfacts import (
    DEFAULT_SEC_USER_AGENT,
    SecCompanyFactsClient,
    companyfacts_to_events,
    resolve_sec_user_agent,
)
from src.data.fundamentals.tushare_financials import tushare_indicator_to_events


RETRIEVED = "2026-08-02T00:00:00+00:00"


def test_us87_sec_mapping_is_exact_and_keeps_tigo_tygo_distinct():
    pool = yaml.safe_load(
        Path("configs/research_universes/us_selected_equities_v2.yaml").read_text(encoding="utf-8")
    )
    mapping = yaml.safe_load(
        Path("configs/providers/us_selected_equities_sec_cik_v3.yaml").read_text(encoding="utf-8")
    )
    expected = set(pool["symbols"])
    mapped = set(mapping["symbols"])
    missing = set(mapping["missing_symbols"])
    assert mapped | missing == expected
    assert mapped & missing == set()
    assert mapping["mapped_symbol_count"] == len(mapped) == 86
    assert mapping["symbols"]["TIGO"] != mapping["symbols"]["TYGO"]
    runtime = _sec_mapping(
        list(pool["symbols"]),
        Path("configs/providers/us_selected_equities_sec_cik_v3.yaml"),
    )
    assert runtime["SBGSY"] == {
        "cik": "",
        "title": "Schneider Electric SE unsponsored ADR",
        "entity_id": "SELECTED_POOL_ENTITY:SCHNEIDER_ELECTRIC_SE",
    }


def test_non_sec_entity_still_populates_independent_corporate_actions(
    monkeypatch, tmp_path: Path
) -> None:
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(
        yaml.safe_dump(
            {
                "pool_id": "us_selected_equities_v2",
                "symbols": {},
                "missing_symbols": ["SBGSY"],
                "declared_exceptions": {
                    "SBGSY": {
                        "entity": "Schneider Electric SE unsponsored ADR",
                        "entity_id": "SELECTED_POOL_ENTITY:SCHNEIDER_ELECTRIC_SE",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.data.populate_selected_pool_events.fetch_yfinance_actions",
        lambda _symbol: pd.DataFrame(),
    )

    fundamentals, actions = _populate_us(
        ["SBGSY"],
        {},
        RETRIEVED,
        identity_mapping_path=mapping_path,
    )

    assert fundamentals["SBGSY"].status == "identity_missing"
    assert actions["SBGSY"].status == "no_event_observed"
    assert actions["SBGSY"].providers == ["yfinance_actions"]


def test_cn_sources_are_reused_only_for_the_exact_cutoff(monkeypatch, tmp_path: Path) -> None:
    calls = {"disclosures": 0, "statements": 0, "actions": 0}

    class FinancialClient:
        def fetch_disclosures(self, **_kwargs):
            calls["disclosures"] += 1
            return pd.DataFrame()

        def fetch_statement(self, **_kwargs):
            calls["statements"] += 1
            return pd.DataFrame()

    class ActionClient:
        def fetch_dividends(self, **_kwargs):
            calls["actions"] += 1
            return pd.DataFrame(
                [
                    {
                        "报告期": "2025-12-31",
                        "最新公告日期": "2026-05-20",
                        "股权登记日": "2026-05-27",
                        "除权除息日": "2026-05-28",
                        "现金红利发放日": "2026-05-28",
                        "现金分红-现金分红比例": 5.0,
                        "送转股份-送转总比例": 0.0,
                    }
                ]
            )

    financial_client = FinancialClient()
    monkeypatch.setattr(
        "src.data.cn_selected_pool_event_sources.AsharePublicFinancialClient",
        lambda: financial_client,
    )
    monkeypatch.setattr(
        "src.data.cn_selected_pool_event_sources.AsharePublicActionClient",
        lambda: ActionClient(),
    )

    first = populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        "2026-08-04T00:00:00+00:00",
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
        progress=lambda _message: None,
    )
    assert first.fundamentals["000425"].status == "partial"
    assert first.source_reuse["fundamentals"]["source_fetch_count"] == 1
    assert first.source_reuse["corporate_actions"]["source_fetch_count"] == 1
    assert calls == {"disclosures": 1, "statements": 3, "actions": 1}
    first_retrieved_at = first.corporate_actions["000425"].events[0].retrieved_at

    second = populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        "2026-08-05T00:00:00+00:00",
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
        progress=lambda _message: None,
    )
    assert calls == {"disclosures": 1, "statements": 3, "actions": 1}
    assert second.source_reuse["fundamentals"]["exact_cutoff_reuse_count"] == 1
    assert second.source_reuse["corporate_actions"]["exact_cutoff_reuse_count"] == 1
    assert (
        second.corporate_actions["000425"].events[0].retrieved_at
        == first_retrieved_at
    )

    populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        "2026-08-05T00:00:00+00:00",
        start_date="2021-01-01",
        end_date="2026-08-01",
        source_cache_root=tmp_path,
        progress=lambda _message: None,
    )
    assert calls == {"disclosures": 2, "statements": 6, "actions": 2}


def test_sec_client_has_non_secret_declared_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert resolve_sec_user_agent() == DEFAULT_SEC_USER_AGENT
    client = SecCompanyFactsClient()
    assert "AlphaEngine" in str(client.user_agent)
    # SEC fair-access guidance expects a declared identity with a contact
    # route; the checked-in default carries the owner's public noreply address.
    assert "@" in str(client.user_agent)
    assert client.transport_evidence()["egress_mode"] == "direct"


def test_sec_companyfacts_uses_conservative_post_filing_availability():
    payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "fy": 2025,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-10-31",
                                "end": "2025-09-27",
                                "accn": "0000320193-25-000079",
                                "val": 100.0,
                            }
                        ]
                    }
                }
            }
        },
    }
    events = companyfacts_to_events(
        payload,
        symbol="AAPL",
        cik="0000320193",
        exchange="XNAS",
        field_map={"Revenues": {"field": "revenue", "unit": "USD", "currency": "USD"}},
        retrieved_at=RETRIEVED,
    )
    assert len(events) == 1
    event = events[0]
    assert event.fiscal_period_end == "2025-09-27"
    assert event.reported_at.startswith("2025-10-31T00:00:00")
    assert event.available_at.startswith("2025-11-01T00:00:00")
    assert event.source_document_id == "0000320193-25-000079"
    assert event.is_derived is False


def test_sina_financials_require_cninfo_disclosure_time():
    disclosures = pd.DataFrame(
        [
            {
                "公告标题": "某公司2025年年度报告",
                "公告时间": "2026-03-28",
                "公告链接": "https://www.cninfo.com.cn/report/1",
            }
        ]
    )
    indexed = cninfo_period_disclosures(disclosures)
    statement = pd.DataFrame(
        [
            {
                "报告日": "20251231",
                "类型": "合并期末",
                "营业收入": 123.0,
                "更新日期": "2026-03-28 T18:00:00",
            },
            {
                "报告日": "20250930",
                "类型": "合并期末",
                "营业收入": 99.0,
                "更新日期": "2025-10-30 T18:00:00",
            },
        ]
    )
    events = sina_statement_to_events(
        statement,
        disclosures=indexed,
        symbol="600000",
        exchange="SSE",
        statement="利润表",
        field_map={"营业收入": {"field": "revenue", "unit": "CNY", "currency": "CNY"}},
        retrieved_at=RETRIEVED,
    )
    assert len(events) == 1
    event = events[0]
    assert event.fiscal_period_end == "2025-12-31"
    assert event.reported_at.startswith("2026-03-28")
    assert event.available_at.startswith("2026-03-29")
    assert event.source_provider == "akshare_sina_financial_report_cninfo_time"


def test_tushare_fundamentals_are_validation_only():
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20260425",
                "end_date": "20260331",
                "eps": 0.55,
            }
        ]
    )
    events = tushare_indicator_to_events(
        frame,
        symbol="000001",
        ts_code="000001.SZ",
        exchange="SZSE",
        field_map={"eps": {"field": "basic_eps", "unit": "CNY/shares", "currency": "CNY"}},
        retrieved_at=RETRIEVED,
    )
    assert len(events) == 1
    event = events[0]
    assert event.fiscal_period_end == "2026-03-31"
    assert event.available_at.startswith("2026-04-26T00:00:00+08:00")
    assert event.source_provider.startswith("tushare_validation_")


def test_eastmoney_actions_use_explicit_fields():
    frame = pd.DataFrame(
        [
            {
                "报告期": "2025-12-31",
                "最新公告日期": "2026-05-20",
                "股权登记日": "2026-05-27",
                "除权除息日": "2026-05-28",
                "现金红利发放日": "2026-05-28",
                "现金分红-现金分红比例": 5.0,
                "送转股份-送转总比例": 2.0,
            }
        ]
    )
    events = eastmoney_dividend_to_events(
        frame,
        symbol="600000",
        exchange="SSE",
        retrieved_at=RETRIEVED,
    )
    assert [event.event_type for event in events] == ["cash_dividend", "stock_dividend"]
    assert events[0].cash_amount == 0.5
    assert events[1].stock_dividend_ratio == 0.2
    assert all(event.source_provider == "akshare_eastmoney_dividend" for event in events)


def test_yahoo_actions_are_primary_explicit_events():
    frame = pd.DataFrame(
        {
            "Dividends": [0.25, 0.0],
            "Stock Splits": [0.0, 2.0],
        },
        index=pd.to_datetime(["2026-06-01", "2026-06-02"], utc=True),
    )
    events = yfinance_actions_to_corporate_actions(
        frame,
        symbol="AAPL",
        exchange="XNAS",
        entity_id="CIK0000320193",
        retrieved_at=RETRIEVED,
    )
    assert [event.event_type for event in events] == ["cash_dividend", "split"]
    assert all(event.source_provider == "yfinance_actions" for event in events)


def test_tiingo_actions_are_explicit_validation_evidence():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
            "close": [100.0, 50.0, 51.0],
            "cash_distribution": [0.0, 0.25, 0.0],
            "split_factor": [1.0, 2.0, 1.0],
        }
    )
    events = tiingo_bars_to_corporate_actions(
        frame,
        symbol="AAPL",
        exchange="XNAS",
        entity_id="CIK0000320193",
        retrieved_at=RETRIEVED,
    )
    assert [event.event_type for event in events] == ["cash_dividend", "split"]
    assert all(event.effective_date == "2026-06-02" for event in events)

    no_fields = frame.drop(columns=["cash_distribution", "split_factor"])
    assert (
        tiingo_bars_to_corporate_actions(
            no_fields,
            symbol="AAPL",
            exchange="XNAS",
            entity_id="CIK0000320193",
            retrieved_at=RETRIEVED,
        )
        == []
    )
