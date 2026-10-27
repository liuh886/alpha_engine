"""Tests for supplemented personal portfolio holdings evidence.

Verifies:
1. All 4 supplemented market evidence JSON files exist and have valid structure and chart studies.
2. Catalog accurately indexes all 4 symbols with content hashes.
3. Reference instrument registry governs the symbols with declared roles.
4. Track B get_research_data_slice extracts slices cleanly for all 4 symbols.
5. Personal audit scanner reports 0 missing evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.data.research_slice import DataSliceRequest, get_research_data_slice
from src.research.personal_lens import scan_personal_investment_pool

SUPPLEMENTED_SYMBOLS = ("PL", "SOXL", "SPCX", "IQQ")


def test_supplemented_market_evidence_files_exist_and_valid() -> None:
    evidence_dir = Path("data/research/market_evidence/us/symbols")
    for sym in SUPPLEMENTED_SYMBOLS:
        file_path = evidence_dir / f"{sym}.json"
        assert file_path.is_file(), f"Market evidence missing for {sym}"
        data = json.loads(file_path.read_text(encoding="utf-8"))

        assert data["evidence_type"] == "security_market_evidence"
        assert data["symbol"] == sym
        assert data["market"] == "us"
        assert "comparison_reference" in data["roles"]
        assert len(data["bars"]) > 0
        assert data["start"] == data["bars"][0]["time"]
        assert data["cutoff"] == data["bars"][-1]["time"]

        # Check chart studies
        studies = data.get("chart_studies", {})
        assert "boll20" in studies
        assert "macd_12_26_9" in studies
        assert "rsi14" in studies


def test_catalog_contains_supplemented_symbols() -> None:
    catalog_path = Path("data/research/market_evidence/us/catalog.json")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    catalog_symbols = {s["symbol"]: s for s in catalog["symbols"]}
    for sym in SUPPLEMENTED_SYMBOLS:
        assert sym in catalog_symbols, f"{sym} not found in catalog"
        entry = catalog_symbols[sym]
        assert entry["path"] == f"symbols/{sym}.json"
        assert len(entry["sha256"]) == 64
        assert "comparison_reference" in entry["roles"]


def test_reference_registry_contains_supplemented_symbols() -> None:
    ref_path = Path("configs/pools/reference_instrument_registry_v1.yaml")
    ref_data = yaml.safe_load(ref_path.read_text(encoding="utf-8"))
    us_insts = ref_data["markets"]["us"]["instruments"]

    for sym in SUPPLEMENTED_SYMBOLS:
        assert sym in us_insts, f"{sym} not registered in reference registry"
        inst = us_insts[sym]
        assert "comparison_reference" in inst["roles"]
        assert inst["candidate_eligible"] is False
        assert inst["portfolio_eligible_by_default"] is False


def test_research_data_slice_extracts_supplemented_symbols() -> None:
    req = DataSliceRequest(
        market="us",
        pool_id="us_selected_equities_v2",
        symbols=list(SUPPLEMENTED_SYMBOLS),
        start_date="2026-08-01",
        end_date="2026-10-26",
        as_of_cutoff="2026-10-26",
        price_mode="anchored_adjusted",
        required_fields=["open", "high", "low", "close", "volume"],
    )
    res = get_research_data_slice(req)
    assert res.is_ready is True
    assert res.data is not None
    assert set(res.data["symbol"].unique()) == set(SUPPLEMENTED_SYMBOLS)
    assert len(res.data) > 0


def test_personal_audit_shows_zero_missing_evidence() -> None:
    pool_dir = Path("D:/Documents/zhihaol/200_Area/Investment/Pool")
    report = scan_personal_investment_pool(pool_dir)

    assert report.total_scanned == 23
    assert report.missing_evidence_count == 0
    assert report.ready_count == 21
    assert report.cash_count == 1
    assert report.other_market_count == 1
