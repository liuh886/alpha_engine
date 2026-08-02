from __future__ import annotations

import pandas as pd

from src.data.corporate_actions.tiingo_events import (
    tiingo_bars_to_corporate_actions,
)
from src.data.fundamentals.sec_companyfacts import companyfacts_to_events
from src.data.fundamentals.tushare_financials import tushare_indicator_to_events


RETRIEVED = "2026-08-02T00:00:00+00:00"


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
        field_map={
            "Revenues": {"field": "revenue", "unit": "USD", "currency": "USD"}
        },
        retrieved_at=RETRIEVED,
    )
    assert len(events) == 1
    event = events[0]
    assert event.fiscal_period_end == "2025-09-27"
    assert event.reported_at.startswith("2025-10-31T00:00:00")
    assert event.available_at.startswith("2025-11-01T00:00:00")
    assert event.source_document_id == "0000320193-25-000079"
    assert event.is_derived is False


def test_tushare_fundamentals_use_announcement_not_period_end():
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
        field_map={
            "eps": {"field": "basic_eps", "unit": "CNY/shares", "currency": "CNY"}
        },
        retrieved_at=RETRIEVED,
    )
    assert len(events) == 1
    event = events[0]
    assert event.fiscal_period_end == "2026-03-31"
    assert event.available_at.startswith("2026-04-26T00:00:00+08:00")
    assert event.available_at[:10] != event.fiscal_period_end


def test_tiingo_actions_are_explicit_not_price_inferred():
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
    assert all(event.reconciliation_status == "source_only" for event in events)

    no_fields = frame.drop(columns=["cash_distribution", "split_factor"])
    assert tiingo_bars_to_corporate_actions(
        no_fields,
        symbol="AAPL",
        exchange="XNAS",
        entity_id="CIK0000320193",
        retrieved_at=RETRIEVED,
    ) == []
