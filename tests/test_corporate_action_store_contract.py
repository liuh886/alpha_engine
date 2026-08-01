import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.data.audit_corporate_action_coverage import audit
from src.data.corporate_actions import (
    build_corporate_action_id,
    normalize_corporate_action,
    rebuild_adjusted_ohlcv,
)


def _event(symbol: str = "000001") -> dict:
    return {
        "market": "cn",
        "symbol": symbol,
        "exchange": "SZ",
        "entity_id": f"cn:{symbol}",
        "event_type": "cash_dividend",
        "announced_at": "2026-04-01T18:00:00+08:00",
        "ex_date": "2026-05-15",
        "record_date": "2026-05-14",
        "pay_date": "2026-05-15",
        "effective_date": "2026-05-15",
        "cash_amount": 0.25,
        "currency": "CNY",
        "split_ratio": None,
        "stock_dividend_ratio": None,
        "rights_ratio": None,
        "rights_price": None,
        "shares_before": None,
        "shares_after": None,
        "old_symbol": "",
        "new_symbol": "",
        "source_provider": "tushare",
        "source_document_id": f"dividend:{symbol}:20260515:0",
        "source_endpoint": "dividend",
        "retrieved_at": "2026-08-01T12:00:00+00:00",
        "source_hash": "b" * 64,
        "revision_sequence": 0,
        "supersedes_event_id": "",
        "confidence": 1.0,
        "reconciliation_status": "source_only",
        "event_id": "",
    }


def test_corporate_action_identity_is_deterministic() -> None:
    first = normalize_corporate_action(_event())
    second = normalize_corporate_action(_event())

    assert first == second
    assert first.event_id == build_corporate_action_id(first.to_dict())
    assert len(first.event_id) == 64


def test_split_requires_a_positive_ratio() -> None:
    payload = _event()
    payload["event_type"] = "split"
    payload["cash_amount"] = None
    payload["currency"] = ""

    with pytest.raises(ValueError, match="positive split_ratio"):
        normalize_corporate_action(payload)


def test_ticker_change_requires_old_and_new_symbols() -> None:
    payload = _event()
    payload["event_type"] = "ticker_change"
    payload["cash_amount"] = None
    payload["currency"] = ""

    with pytest.raises(ValueError, match="old_symbol and new_symbol"):
        normalize_corporate_action(payload)


def test_rebuild_adjusted_prices_uses_frozen_cutoff_anchor() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-05"],
            "open": [10.0, 6.0],
            "high": [11.0, 6.5],
            "low": [9.0, 5.5],
            "close": [10.0, 6.0],
            "volume": [100.0, 200.0],
        }
    )
    factors = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-05"],
            "factor": [1.0, 2.0],
        }
    )

    adjusted = rebuild_adjusted_ohlcv(raw, factors, cutoff="2026-01-05")

    assert adjusted.loc[0, "close"] == pytest.approx(5.0)
    assert adjusted.loc[1, "close"] == pytest.approx(6.0)
    assert adjusted.loc[0, "volume"] == pytest.approx(200.0)
    assert adjusted.loc[1, "volume"] == pytest.approx(200.0)
    assert raw.loc[0, "close"] == 10.0
    assert adjusted["price_role"].unique().tolist() == [
        "adjusted_feature_and_label"
    ]


def test_rebuild_rejects_missing_daily_factor() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-05"],
            "open": [10.0, 6.0],
            "high": [11.0, 6.5],
            "low": [9.0, 5.5],
            "close": [10.0, 6.0],
            "volume": [100.0, 200.0],
        }
    )
    factors = pd.DataFrame(
        {"date": ["2026-01-05"], "factor": [2.0]}
    )

    with pytest.raises(ValueError, match="missing adjustment factor"):
        rebuild_adjusted_ohlcv(raw, factors, cutoff="2026-01-05")


def test_coverage_enumerates_all_cn_selected_candidates(tmp_path: Path) -> None:
    event = normalize_corporate_action(_event()).to_dict()
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")

    report = audit(Path.cwd(), market="cn", events_path=events)

    assert report["candidate_count"] == 130
    assert report["reported_candidate_count"] == 130
    assert report["complete_candidate_enumeration"] is True
    assert report["symbols_with_events"] == 1
    assert report["symbols_without_events"] == 129
    assert report["coverage"]["000001"]["event_count"] == 1
    assert report["coverage"]["000063"]["status"] == "no_event_observed"


def test_coverage_rejects_out_of_pool_symbol(tmp_path: Path) -> None:
    event = normalize_corporate_action(_event("999999")).to_dict()
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside selected pool"):
        audit(Path.cwd(), market="cn", events_path=events)
