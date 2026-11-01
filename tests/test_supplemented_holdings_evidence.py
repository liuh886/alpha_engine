"""Portable supplemental-reference readers; no claim about live owner coverage.

Synthetic test prices stay under tmp_path. Registry authorization is checked
against the maintained repository; missing sources must remain visible.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from src.data.research_slice import DataSliceRequest, get_research_data_slice
from src.research.personal_lens import scan_personal_investment_pool

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENTED_SYMBOLS = ("PL", "SOXL", "SPCX", "IQQ")


@pytest.fixture
def evidence_root(tmp_path: Path) -> Path:
    root = tmp_path / "research"
    for relative in (
        "configs/pools/selected_pool_registry_v1.yaml",
        "configs/pools/reference_instrument_registry_v1.yaml",
        "configs/research_universes/us_selected_equities_v2.yaml",
        "configs/data_quality/symbol_identity_and_lifecycle_v1.yaml",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    market = root / "data/research/market_evidence/us"
    (market / "symbols").mkdir(parents=True)
    catalog = []
    for symbol in SUPPLEMENTED_SYMBOLS:
        bars = [{"time": f"2026-08-0{day}", "open": 10., "high": 12.,
                 "low": 9., "close": 11., "volume": 100.} for day in (3, 4, 5)]
        payload = {"symbol": symbol, "market": "us", "bars": bars,
                   "roles": ["comparison_reference"], "start": bars[0]["time"],
                   "cutoff": bars[-1]["time"], "research_only": True, "trade_ready": False}
        path = market / "symbols" / f"{symbol}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        catalog.append({**{k: payload[k] for k in ("symbol", "roles", "start", "cutoff")},
                        "path": f"symbols/{symbol}.json",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (market / "catalog.json").write_text(json.dumps({"symbols": catalog}), encoding="utf-8")
    return root


def _request() -> DataSliceRequest:
    return DataSliceRequest(market="us", pool_id="us_selected_equities_v2",
                            symbols=list(SUPPLEMENTED_SYMBOLS), start_date="2026-08-03",
                            end_date="2026-08-05", as_of_cutoff="2026-08-05",
                            price_mode="anchored_adjusted",
                            required_fields=["open", "high", "low", "close", "volume"])


def test_reference_registry_contains_supplemented_symbols() -> None:
    ref_data = yaml.safe_load((ROOT / "configs/pools/reference_instrument_registry_v1.yaml").read_text(encoding="utf-8"))
    instruments = ref_data["markets"]["us"]["instruments"]
    for symbol in SUPPLEMENTED_SYMBOLS:
        assert "comparison_reference" in instruments[symbol]["roles"]
        assert instruments[symbol]["candidate_eligible"] is False
        assert instruments[symbol]["portfolio_eligible_by_default"] is False


def test_research_data_slice_extracts_supplemented_symbols(evidence_root: Path) -> None:
    before = {p: p.read_bytes() for p in evidence_root.rglob("*.json")}
    result = get_research_data_slice(_request(), root=evidence_root)
    assert result.is_ready
    assert result.data is not None
    assert set(result.data["symbol"].unique()) == set(SUPPLEMENTED_SYMBOLS)
    assert len(result.data) == 12
    assert set(result.data["close"]) == {11.}
    assert result.receipt["research_only"] is True
    assert result.receipt["trade_ready"] is False
    assert {p: p.read_bytes() for p in before} == before


def test_supplemented_slice_blocks_missing_source(evidence_root: Path) -> None:
    (evidence_root / "data/research/market_evidence/us/symbols/PL.json").unlink()
    result = get_research_data_slice(_request(), root=evidence_root)
    assert not result.is_ready
    assert result.data is None
    assert result.receipt["data_hash"] is None
    assert any(b["symbol"] == "PL" and b["code"] == "DATA_MISSING_FOR_DATE_RANGE"
               for b in result.receipt["blocked_reasons"])


@pytest.mark.parametrize("missing", [False, True])
def test_personal_audit_classifies_fixture_evidence(evidence_root: Path, tmp_path: Path, missing: bool) -> None:
    pool = tmp_path / "notes"
    pool.mkdir()
    for symbol in SUPPLEMENTED_SYMBOLS:
        (pool / f"{symbol}.md").write_text(f"---\nticker: {symbol}\nmarket: US\n---\n", encoding="utf-8")
    (pool / "cash.md").write_text("---\nticker: USD\nasset_type: cash\n---\n", encoding="utf-8")
    (pool / "foreign.md").write_text("---\nticker: FOREIGN\nmarket: EU\n---\n", encoding="utf-8")
    if missing:
        market = evidence_root / "data/research/market_evidence/us"
        (market / "symbols/PL.json").unlink()
        catalog_path = market / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["symbols"] = [row for row in catalog["symbols"] if row["symbol"] != "PL"]
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    before = {p: p.read_bytes() for p in pool.iterdir()}
    report = scan_personal_investment_pool(pool, root=evidence_root)
    assert report.total_scanned == 6
    assert report.ready_count == (3 if missing else 4)
    assert report.missing_evidence_count == int(missing)
    assert report.cash_count == 1
    assert report.other_market_count == 1
    assert all(h.in_reference_registry for h in report.holdings if h.ticker in SUPPLEMENTED_SYMBOLS)
    assert {p: p.read_bytes() for p in pool.iterdir()} == before
