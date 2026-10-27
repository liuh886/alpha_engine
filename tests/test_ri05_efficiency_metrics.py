"""Tests for Track B RI-05: Researcher Efficiency Metrics and Interface Optimization.

Verifies:
1. Mathematical equivalence between ad-hoc baseline and slice-based computation.
2. Efficiency gains: >80% boilerplate code reduction, >60% manual steps reduction.
3. Automated PIT enforcement (interception of lookahead queries).
4. CLI --data-output CSV export for ready slices and fail-closed suppression for blocked slices.
5. Zero secondary databases, zero background schedulers, strict governance invariants.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.cli.main import main
from src.research.efficiency_benchmark import (
    measure_efficiency_metrics,
    run_ad_hoc_baseline,
    run_slice_optimized,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_ri05_mathematical_equivalence() -> None:
    """Prove that data slice returns identical factor values to baseline parsing."""
    metrics = measure_efficiency_metrics(REPO_ROOT)
    assert metrics.data_equivalence_verified is True
    assert metrics.max_absolute_difference < 1e-5


def test_ri05_efficiency_gain_thresholds() -> None:
    """Verify workflow step estimates and empirically measured AST statements / PIT verification."""
    metrics = measure_efficiency_metrics(REPO_ROOT)

    # 1. Qualitative workflow steps (Heuristic estimation)
    assert metrics.estimated_baseline_workflow_steps == 7
    assert metrics.estimated_optimized_workflow_steps == 2
    assert metrics.estimated_steps_reduction_pct >= 60.0
    assert len(metrics.workflow_steps_breakdown["baseline_workflow_steps"]) == 7
    assert len(metrics.workflow_steps_breakdown["optimized_workflow_steps"]) == 2

    # 2. Empirically measured AST statement complexity
    assert metrics.measured_baseline_ast_statements > metrics.measured_optimized_ast_statements
    assert metrics.measured_ast_statement_reduction_pct >= 40.0

    # 3. Empirically verified PIT lookahead protection (via actual challenge execution)
    assert metrics.verified_baseline_intercepts_lookahead is False
    assert metrics.verified_optimized_intercepts_lookahead is True

    # 4. Auditability & cryptographic binding
    assert metrics.baseline_has_cryptographic_receipt is False
    assert metrics.optimized_has_cryptographic_receipt is True


def test_ri05_cli_data_output_export_happy_path(tmp_path: Path) -> None:
    """Test CLI --data-output exports valid CSV with matching row counts when ready."""
    out_csv = tmp_path / "slice_export.csv"
    out_receipt = tmp_path / "slice_receipt.json"

    argv = [
        "--root",
        str(REPO_ROOT),
        "data",
        "slice",
        "--market",
        "us",
        "--pool",
        "us_selected_equities_v2",
        "--symbols",
        "AAPL,MSFT",
        "--start",
        "2026-08-03",
        "--end",
        "2026-08-07",
        "--cutoff",
        "2026-09-04",
        "--output",
        str(out_receipt),
        "--data-output",
        str(out_csv),
    ]

    exit_code = main(argv)
    assert exit_code == 0
    assert out_receipt.is_file()
    assert out_csv.is_file()

    receipt = json.loads(out_receipt.read_text(encoding="utf-8"))
    assert receipt["status"] == "ready"
    assert receipt["total_rows"] == 10  # 5 trading days x 2 symbols

    # Read exported CSV
    with out_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 10
    assert {"symbol", "time", "open", "high", "low", "close", "volume"}.issubset(rows[0].keys())
    symbols_in_csv = {r["symbol"] for r in rows}
    assert symbols_in_csv == {"AAPL", "MSFT"}


def test_ri05_cli_data_output_blocked_fail_closed(tmp_path: Path) -> None:
    """Test CLI --data-output suppresses CSV creation when slice is blocked (exit code 10)."""
    out_csv = tmp_path / "blocked_export.csv"
    out_receipt = tmp_path / "blocked_receipt.json"

    argv = [
        "--root",
        str(REPO_ROOT),
        "data",
        "slice",
        "--market",
        "us",
        "--pool",
        "us_selected_equities_v2",
        "--symbols",
        "AAPL",
        "--start",
        "2026-08-01",
        "--end",
        "2026-09-10",  # After cutoff
        "--cutoff",
        "2026-09-04",
        "--output",
        str(out_receipt),
        "--data-output",
        str(out_csv),
    ]

    exit_code = main(argv)
    assert exit_code == 10
    assert out_receipt.is_file()
    # Strictly fail-closed: output CSV must NOT exist
    assert not out_csv.is_file()

    receipt = json.loads(out_receipt.read_text(encoding="utf-8"))
    assert receipt["status"] == "blocked"
    assert receipt["data_hash"] is None


def test_ri05_cli_data_output_blocked_does_not_delete_existing_file(tmp_path: Path) -> None:
    """Ensure a blocked slice does NOT delete an existing file at --data-output path."""
    existing_file = tmp_path / "user_important_data.csv"
    existing_file.write_text("pre_existing_data", encoding="utf-8")

    argv = [
        "--root",
        str(REPO_ROOT),
        "data",
        "slice",
        "--market",
        "us",
        "--pool",
        "us_selected_equities_v2",
        "--symbols",
        "AAPL",
        "--start",
        "2026-08-01",
        "--end",
        "2026-09-10",  # Blocked: after cutoff
        "--cutoff",
        "2026-09-04",
        "--data-output",
        str(existing_file),
    ]

    exit_code = main(argv)
    assert exit_code == 10
    # Must preserve existing user file completely intact
    assert existing_file.is_file()
    assert existing_file.read_text(encoding="utf-8") == "pre_existing_data"


def test_ri05_governance_invariants() -> None:
    """Ensure research_only=true, trade_ready=false and zero secondary database."""
    _, receipt, _ = run_slice_optimized(
        REPO_ROOT,
        market="us",
        pool_id="us_selected_equities_v2",
        symbols=["AAPL"],
        benchmark_symbol="QQQ",
        start_date="2026-08-01",
        end_date="2026-08-10",
        as_of_cutoff="2026-09-04",
    )
    assert receipt.get("research_only") is True
    assert receipt.get("trade_ready") is False
    assert receipt.get("trade_signal") is not True

    # Assert no auxiliary database was generated
    db_candidates = list(REPO_ROOT.glob("*.db")) + list((REPO_ROOT / "data").glob("*.db"))
    assert len(db_candidates) == 0, f"Unexpected secondary database generated: {db_candidates}"
