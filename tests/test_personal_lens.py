"""Tests for Personal Investment Lens Interface (src/research/personal_lens.py).

Verifies:
1. Gate A4 / Zero Privacy Leakage: Sensitive financial numbers are never parsed or exposed.
2. Read-only safety: Personal notes are never written to or modified in place.
3. Accurate classification: Candidate pool, reference assets, cash reserves, and missing evidence.
4. CLI execution: Both human-readable Markdown table and JSON outputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.cli.main import main
from src.research.personal_lens import (
    FORBIDDEN_FINANCIAL_KEYS,
    PersonalHoldingAudit,
    PersonalLensError,
    _extract_safe_frontmatter,
    scan_personal_investment_pool,
)


def test_extract_safe_frontmatter_privacy_isolation() -> None:
    """Verifies that private financial fields are strictly stripped and never stored."""
    note_content = """---
type: stock-holding
ticker: "SECRET"
name: "Top Secret Corp"
market: US
currency: USD
asset_type: stock
strategy: growth
conviction: high
accounts:
  - "Private Brokerage #123456"
status: holding
shares: 50000.0
total_cost: 1250000.75
cost_basis: 25.00
realized_pnl: 45000.00
unrealized_pnl: 80000.00
portfolio_weight: 0.35
target_weight: 0.20
---

# Transaction History (DO NOT READ)
| Date | Action | Shares | Price |
| 2026-01-01 | BUY | 50000 | 25.0 |
"""
    meta = _extract_safe_frontmatter(note_content, "SECRET.md")

    # Safe metadata preserved
    assert meta["ticker"] == "SECRET"
    assert meta["name"] == "Top Secret Corp"
    assert meta["market"] == "US"
    assert meta["asset_type"] == "stock"
    assert meta["strategy"] == "growth"
    assert meta["conviction"] == "high"
    assert meta["status"] == "holding"

    # Strictly verify zero forbidden financial keys leaked into meta
    for forbidden in FORBIDDEN_FINANCIAL_KEYS:
        assert forbidden not in meta

    # Verify audit item construction
    audit = PersonalHoldingAudit(
        ticker=meta["ticker"],
        name=meta["name"],
        market=meta["market"],
        asset_type=meta["asset_type"],
        strategy=meta["strategy"],
        conviction=meta["conviction"],
        status=meta["status"],
        in_governed_pool=True,
        in_reference_registry=False,
        market_evidence_present=True,
        date_range="2021-01-01 ~ 2026-10-26",
        data_readiness="ready",
        note_file="SECRET.md",
    )

    d = audit.to_dict()
    for forbidden in FORBIDDEN_FINANCIAL_KEYS:
        assert forbidden not in d
        assert not hasattr(audit, forbidden)


def test_personal_notes_are_strictly_read_only(tmp_path: Path) -> None:
    """Verifies that personal notes on disk are never opened in write mode or modified."""
    mock_pool = tmp_path / "Pool"
    mock_pool.mkdir()

    test_file = mock_pool / "MOCK.md"
    original_text = """---
ticker: MOCK
name: Mock Asset
market: US
asset_type: stock
shares: 42.0
total_cost: 1000.0
---
Some personal notes.
"""
    test_file.write_text(original_text, encoding="utf-8")
    original_sha = hashlib.sha256(test_file.read_bytes()).hexdigest()
    original_mtime = test_file.stat().st_mtime_ns

    # Perform scan
    report = scan_personal_investment_pool(mock_pool, root=Path.cwd())

    # Verify file is 100% byte-identical and untouched
    after_sha = hashlib.sha256(test_file.read_bytes()).hexdigest()
    after_mtime = test_file.stat().st_mtime_ns

    assert original_sha == after_sha
    assert original_mtime == after_mtime
    assert report.total_scanned == 1
    assert report.holdings[0].ticker == "MOCK"


def test_classification_logic_across_asset_types(tmp_path: Path) -> None:
    """Verifies correct classification for cash, foreign stocks, candidate pool, and missing assets."""
    mock_pool = tmp_path / "Pool"
    mock_pool.mkdir()

    # 1. Cash note
    (mock_pool / "CASH.md").write_text(
        "---\nticker: USD.CASH.TEST\nname: Test Cash\nasset_type: cash\nshares: 500\n---\n",
        encoding="utf-8",
    )
    # 2. Foreign market note
    (mock_pool / "EU_STOCK.md").write_text(
        "---\nticker: EU1\nname: Europe Stock\nmarket: EU\nasset_type: stock\n---\n",
        encoding="utf-8",
    )
    # 3. Known candidate stock (NVDA is in us_selected_equities_v2)
    (mock_pool / "NVDA.md").write_text(
        "---\nticker: NVDA\nname: NVIDIA Corp\nmarket: US\nasset_type: stock\n---\n",
        encoding="utf-8",
    )
    # 4. Known reference ETF (SGOV is in reference_instrument_registry_v1)
    (mock_pool / "SGOV.md").write_text(
        "---\nticker: SGOV\nname: Short Treasury ETF\nmarket: US\nasset_type: etf\n---\n",
        encoding="utf-8",
    )
    # 5. Missing market evidence stock
    (mock_pool / "NONEXISTENT.md").write_text(
        "---\nticker: NONEXISTENT\nname: Nonexistent Corp\nmarket: US\nasset_type: stock\n---\n",
        encoding="utf-8",
    )

    report = scan_personal_investment_pool(mock_pool, root=Path.cwd())

    assert report.total_scanned == 5
    assert report.cash_count == 1
    assert report.other_market_count == 1
    assert report.ready_count == 2
    assert report.missing_evidence_count == 1

    holdings_by_ticker = {h.ticker: h for h in report.holdings}

    # Cash check
    assert holdings_by_ticker["USD.CASH.TEST"].data_readiness == "cash_reserve"
    # EU check
    assert holdings_by_ticker["EU1"].data_readiness == "unregistered_market_eu"
    # NVDA check
    assert holdings_by_ticker["NVDA"].in_governed_pool is True
    assert holdings_by_ticker["NVDA"].data_readiness == "ready"
    # SGOV check
    assert holdings_by_ticker["SGOV"].in_reference_registry is True
    assert holdings_by_ticker["SGOV"].data_readiness == "ready"
    # Missing check
    assert holdings_by_ticker["NONEXISTENT"].data_readiness == "missing_market_evidence"


def test_scan_personal_investment_pool_missing_dir(tmp_path: Path) -> None:
    """Verifies that non-existent directory raises PersonalLensError."""
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(PersonalLensError, match="not found"):
        scan_personal_investment_pool(non_existent, root=Path.cwd())


def test_cli_personal_audit_table_and_json_modes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies CLI execution for table and json formatting."""
    mock_pool = tmp_path / "Pool"
    mock_pool.mkdir()
    (mock_pool / "NVDA.md").write_text(
        "---\nticker: NVDA\nname: NVIDIA Corp\nmarket: US\nasset_type: stock\nshares: 10\n---\n",
        encoding="utf-8",
    )

    # 1. Test table mode
    code = main(["personal", "audit", "--dir", str(mock_pool), "--format", "table"])
    assert code == 0
    captured = capsys.readouterr()
    assert "| `NVDA` | NVIDIA Corp | stock |" in captured.out
    assert "汇总统计" in captured.out
    assert "shares" not in captured.out

    # 2. Test json mode
    code_json = main(["personal", "audit", "--dir", str(mock_pool), "--format", "json"])
    assert code_json == 0
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["total_scanned"] == 1
    assert payload["ready_count"] == 1
    assert payload["privacy_boundary"] == "zero_financial_data_read_or_exposed"
    assert "shares" not in captured_json.out


def test_cli_personal_audit_missing_dir_fail_closed(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies fail-closed behavior on missing directory in CLI."""
    code = main(["personal", "audit", "--dir", "non_existent_dir_random_99999"])
    assert code == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "blocked"
    assert "not found" in payload["reason"]
