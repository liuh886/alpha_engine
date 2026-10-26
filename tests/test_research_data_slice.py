"""Tests for parameterized research data slice reader and governance contracts.

Governed under Track B (RI-03B / #1296) and ADR-0005.
Verifies determinism, fail-closed PIT boundaries, lifecycle checks,
source byte immutability, CLI integration, and operational state decoupling.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli.main import main as cli_main
from src.data.research_slice import (
    DataSliceRequest,
    get_research_data_slice,
)

ROOT = Path(__file__).resolve().parents[1]


def test_research_data_slice_happy_path_deterministic() -> None:
    """Sample 1: Happy path with 4 CN equities returns deterministic data and receipt."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000001", "000338", "600519", "688008"),
        start_date="2024-01-01",
        end_date="2026-09-04",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
        required_fields=("open", "high", "low", "close", "volume"),
    )

    res1 = get_research_data_slice(req, root=ROOT)
    assert res1.receipt["status"] == "ready"
    assert res1.receipt["total_rows"] == 2596
    assert res1.receipt["blocked_reasons"] == []
    assert res1.data is not None
    assert len(res1.data) == 2596
    assert list(res1.data.columns) == ["symbol", "time", "open", "high", "low", "close", "volume"]

    # Check symbol row counts (649 trading days each)
    for sym in ("000001", "000338", "600519", "688008"):
        assert res1.receipt["symbol_row_counts"][sym] == 649

    # Repeat execution to prove exact determinism across runs
    res2 = get_research_data_slice(req, root=ROOT)
    assert res1.receipt["data_hash"] == res2.receipt["data_hash"]
    assert res1.receipt["slice_id"] == res2.receipt["slice_id"]
    assert res1.receipt["request_hash"] == res2.receipt["request_hash"]
    assert res1.receipt["data_hash"] == "5c112d4a11fb6b2b8ef671bd7f482c573b7fc9ae6808e790f80c9fc54c929a64"


def test_research_data_slice_blocks_future_corporate_action_pit() -> None:
    """Sample 2: Jinpan 688676 future dividend announcement blocks lookahead query."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("688676",),
        start_date="2024-01-01",
        end_date="2026-10-15",
        as_of_cutoff="2026-09-04",
        price_mode="anchored_adjusted",
    )

    res = get_research_data_slice(req, root=ROOT)
    assert res.receipt["status"] == "blocked"
    assert res.receipt["data_hash"] is None
    assert res.receipt["total_rows"] == 0
    assert res.data is None

    blocker_codes = {b["code"] for b in res.receipt["blocked_reasons"]}
    assert "PIT_VIOLATION_LOOKAHEAD_CUTOFF" in blocker_codes
    assert "PIT_VIOLATION_FUTURE_EVENT_ANNOUNCEMENT" in blocker_codes

    future_blockers = [b for b in res.receipt["blocked_reasons"] if b["code"] == "PIT_VIOLATION_FUTURE_EVENT_ANNOUNCEMENT"]
    assert len(future_blockers) == 1
    assert future_blockers[0]["symbol"] == "688676"
    assert "2026-09-23" in future_blockers[0]["message"]


def test_research_data_slice_blocks_unlisted_symbol_lifecycle() -> None:
    """Sample 3: 301666 queried prior to listing date 2026-04-16 triggers SYMBOL_NOT_YET_LISTED."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("301666",),
        start_date="2024-01-01",
        end_date="2025-01-01",
        as_of_cutoff="2026-09-04",
    )

    res = get_research_data_slice(req, root=ROOT)
    assert res.receipt["status"] == "blocked"
    assert res.receipt["data_hash"] is None
    assert res.data is None

    blocker_codes = {b["code"] for b in res.receipt["blocked_reasons"]}
    assert "SYMBOL_NOT_YET_LISTED" in blocker_codes
    listed_blocker = [b for b in res.receipt["blocked_reasons"] if b["code"] == "SYMBOL_NOT_YET_LISTED"][0]
    assert listed_blocker["symbol"] == "301666"
    assert "2026-04-16" in listed_blocker["message"]


def test_research_data_slice_blocks_cross_market_and_pool_mismatches() -> None:
    """Asserts market isolation: US symbol or mismatched pool fails closed."""
    # Market pool mismatch
    req_mismatch = DataSliceRequest(
        market="us",
        pool_id="cn_selected_equities_v3",
        symbols=("000001",),
        start_date="2024-01-01",
        end_date="2024-06-01",
        as_of_cutoff="2024-06-01",
    )
    res_mismatch = get_research_data_slice(req_mismatch, root=ROOT)
    assert res_mismatch.receipt["status"] == "blocked"
    assert any(b["code"] == "MARKET_POOL_MISMATCH" for b in res_mismatch.receipt["blocked_reasons"])

    # Symbol not in governed pool
    req_unknown = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("AAPL", "999999"),
        start_date="2024-01-01",
        end_date="2024-06-01",
        as_of_cutoff="2024-06-01",
    )
    res_unknown = get_research_data_slice(req_unknown, root=ROOT)
    assert res_unknown.receipt["status"] == "blocked"
    unknown_codes = [b["code"] for b in res_unknown.receipt["blocked_reasons"]]
    assert unknown_codes.count("SYMBOL_NOT_IN_GOVERNED_POOL") == 2


def test_research_data_slice_preserves_source_bytes_immutability() -> None:
    """Asserts that running slices never mutates raw underlying JSON files."""
    source_file = ROOT / "data/research/market_evidence/cn/symbols/000001.json"
    original_bytes = source_file.read_bytes()

    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000001",),
        start_date="2024-01-01",
        end_date="2024-06-01",
        as_of_cutoff="2024-06-01",
    )
    res = get_research_data_slice(req, root=ROOT)
    assert res.receipt["status"] == "ready"

    # Strict byte-for-byte equality assertion
    assert source_file.read_bytes() == original_bytes


def test_research_data_slice_receipt_governance_invariants() -> None:
    """Receipt must carry non-negotiable governance fields."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000001",),
        start_date="2024-01-01",
        end_date="2024-06-01",
        as_of_cutoff="2024-06-01",
    )
    res = get_research_data_slice(req, root=ROOT)
    receipt = res.receipt
    assert receipt["rights_label"] == "academic_and_internal_research_only"
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["schema_version"] == "research_data_slice_v1"
    assert receipt["slice_id"].startswith("slice_cn_")


def test_research_data_slice_strictly_decouples_operational_monitoring() -> None:
    """Security boundary check: receipt and data must never leak operational weights or ledgers (#1288)."""
    req = DataSliceRequest(
        market="cn",
        pool_id="cn_selected_equities_v3",
        symbols=("000001", "000338"),
        start_date="2024-01-01",
        end_date="2024-06-01",
        as_of_cutoff="2024-06-01",
    )
    res = get_research_data_slice(req, root=ROOT)
    receipt_str = json.dumps(res.receipt)

    forbidden_tokens = (
        "operating_state",
        "current_weights",
        "target_weights",
        "strategy_signal_ledgers",
        "broker_account",
    )
    for token in forbidden_tokens:
        assert token not in receipt_str
        if res.data is not None:
            assert token not in res.data.columns


def test_alpha_cli_data_slice_command(tmp_path: Path) -> None:
    """Verify alpha data slice CLI command execution, exit codes and output receipt file."""
    out_file = tmp_path / "test_cli_receipt.json"

    # 1. Happy path returns exit code 0
    exit_code_ready = cli_main([
        "--root",
        str(ROOT),
        "data",
        "slice",
        "--market",
        "cn",
        "--pool",
        "cn_selected_equities_v3",
        "--symbols",
        "000001,000338",
        "--start",
        "2024-01-01",
        "--end",
        "2026-09-04",
        "--cutoff",
        "2026-09-04",
        "--output",
        str(out_file),
    ])
    assert exit_code_ready == 0
    assert out_file.is_file()
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["status"] == "ready"
    assert payload["total_rows"] == 1298

    # 2. Blocked path returns exit code 10
    exit_code_blocked = cli_main([
        "--root",
        str(ROOT),
        "data",
        "slice",
        "--market",
        "cn",
        "--pool",
        "cn_selected_equities_v3",
        "--symbols",
        "688676",
        "--start",
        "2024-01-01",
        "--end",
        "2026-10-15",
        "--cutoff",
        "2026-09-04",
    ])
    assert exit_code_blocked == 10
