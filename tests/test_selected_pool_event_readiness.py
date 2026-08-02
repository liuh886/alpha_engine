from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.corporate_actions.event_store import normalize_corporate_action
from src.data.fundamentals.event_store import normalize_event_record
from src.data.selected_pool_event_population import (
    SelectedPoolEventPopulationError,
    SymbolPopulation,
    build_selected_pool_event_artifacts,
)


def _fundamental(symbol: str):
    return normalize_event_record(
        {
            "market": "us",
            "symbol": symbol,
            "exchange": "US",
            "entity_id": f"CIK:{symbol}",
            "fiscal_period_end": "2025-12-31",
            "fiscal_year": 2025,
            "fiscal_period": "FY",
            "reported_at": "2026-02-01T00:00:00+00:00",
            "available_at": "2026-02-02T00:00:00+00:00",
            "filing_type": "10-K",
            "source_provider": "sec_companyfacts",
            "source_document_id": f"filing:{symbol}",
            "source_endpoint": "companyfacts",
            "field": "revenue",
            "value": 100.0,
            "unit": "USD",
            "currency": "USD",
            "is_quarterly": False,
            "is_derived": False,
            "derivation_rule": "",
            "revision_sequence": 0,
            "supersedes_event_id": "",
            "retrieved_at": "2026-08-02T00:00:00+00:00",
            "source_hash": "a" * 64,
        }
    )


def _action(symbol: str):
    return normalize_corporate_action(
        {
            "market": "us",
            "symbol": symbol,
            "exchange": "US",
            "entity_id": f"CIK:{symbol}",
            "event_type": "cash_dividend",
            "announced_at": "2026-03-01T00:00:00+00:00",
            "ex_date": "2026-03-05",
            "record_date": "",
            "pay_date": "",
            "effective_date": "2026-03-05",
            "cash_amount": 0.5,
            "currency": "USD",
            "split_ratio": None,
            "stock_dividend_ratio": None,
            "rights_ratio": None,
            "rights_price": None,
            "shares_before": None,
            "shares_after": None,
            "old_symbol": "",
            "new_symbol": "",
            "source_provider": "yfinance_actions",
            "source_document_id": f"action:{symbol}",
            "source_endpoint": "Ticker.actions",
            "retrieved_at": "2026-08-02T00:00:00+00:00",
            "source_hash": "b" * 64,
            "revision_sequence": 0,
            "supersedes_event_id": "",
            "confidence": 0.8,
            "reconciliation_status": "source_only",
        }
    )


def test_builds_direct_components_and_explicit_symbol_statuses(tmp_path: Path) -> None:
    symbols = ["AAA", "BBB"]
    fundamentals = {
        "AAA": SymbolPopulation("AAA", "ready", [_fundamental("AAA")], ["sec_companyfacts"]),
        "BBB": SymbolPopulation("BBB", "partial", [], ["sec_companyfacts"]),
    }
    actions = {
        "AAA": SymbolPopulation("AAA", "ready", [_action("AAA")], ["yfinance_actions"]),
        "BBB": SymbolPopulation("BBB", "no_event_observed", [], ["yfinance_actions"]),
    }
    manifest = build_selected_pool_event_artifacts(
        market="us",
        pool_id="fixture_pool",
        symbols=symbols,
        fundamentals=fundamentals,
        corporate_actions=actions,
        evidence_cutoff="2026-07-31",
        output_root=tmp_path,
    )
    assert manifest["expected_symbol_count"] == 2
    fundamental = json.loads(
        (tmp_path / "fundamentals/component_manifest.json").read_text(encoding="utf-8")
    )
    corporate = json.loads(
        (tmp_path / "corporate_actions/component_manifest.json").read_text(encoding="utf-8")
    )
    assert fundamental["status"] == "partial"
    assert fundamental["ready_symbol_count"] == 1
    assert corporate["status"] == "ready"
    assert corporate["ready_symbol_count"] == 2
    assert corporate["details"]["status_counts"]["no_event_observed"] == 1
    assert (tmp_path / "fundamentals/events.jsonl").read_text().count("\n") == 1


def test_fails_when_any_selected_symbol_has_no_explicit_status(tmp_path: Path) -> None:
    populations = {
        "AAA": SymbolPopulation("AAA", "partial", [], ["fixture"]),
    }
    with pytest.raises(SelectedPoolEventPopulationError, match="missing=\['BBB'\]"):
        build_selected_pool_event_artifacts(
            market="us",
            pool_id="fixture_pool",
            symbols=["AAA", "BBB"],
            fundamentals=populations,
            corporate_actions=populations,
            evidence_cutoff="2026-07-31",
            output_root=tmp_path,
        )
