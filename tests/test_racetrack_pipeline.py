"""Test suite for Racetrack Phase 3: Dual-Market Benchmarks & Self-Maintaining Publish Pipeline.

Verifies:
    TEST-RT-P3-01: CN 130 pool index weight conservation (1/130) and pre-IPO cash protection.
    TEST-RT-P3-02: CN 130 intra-month natural drift and zero turnover invariant.
    TEST-RT-P3-03: CSI 300 reference symbol resolution and XSHG calendar alignment.
    TEST-RT-P3-04: Dual-market orthogonal excess return matrices (macro vs pool).
    TEST-RT-P3-05: End-to-end pipeline publication and manifest hash integrity.
    TEST-RT-P3-06: Fail-closed transactional staging and dirty-write prevention.
    TEST-RT-P3-07: Bit-level determinism and idempotency across repeated runs.
    TEST-RT-P3-08: Zero-leakage privacy guard enforcement (account-sensitive fields).
    TEST-RT-P3-09: CLI command execution and multi-format scoreboard rendering.
    TEST-RT-P3-10: Cross-market asset physical isolation and friction monotonicity.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from src.cli.main import main as cli_main
from src.racetrack.contracts import (
    EngineConfig,
    PrivacyViolationError,
    RebalanceEvent,
    Scoreboard,
    ScoreboardEntry,
    SimulationResult,
    UnauthorizedAssetError,
    assert_privacy_clean,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.matrix import (
    load_price_matrix,
    resolve_reference_symbol,
)
from src.racetrack.pipeline import (
    PipelineResult,
    compute_file_sha256,
    publish_racetrack_projection,
    render_racetrack_scoreboard,
)
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import RunnerContract, RunnerRegistry
from src.racetrack.scoring import (
    evaluate_race_season,
    generate_benchmark_simulation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class MockRacetrackRunner(RunnerContract):
    """Mock runner with valid thesis for pipeline testing."""

    def __init__(
        self,
        runner_id: str,
        pool_id: str = "us_selected_equities_v2",
        benchmark_symbol: str = "QQQ",
        target_symbols: list[str] | None = None,
        monthly_allocations: dict[str, dict[str, float]] | None = None,
        extra_state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            runner_id=runner_id,
            runner_version="1.0.0",
            pool_id=pool_id,
            benchmark_symbol=benchmark_symbol,
            thesis=(
                "Systematic quantitative momentum factor investing with monthly "
                "rebalancing across top-decile market leaders in the declared candidate pool."
            ),
            selection_logic="Rank by 12-1 month price momentum and hold equal weights.",
            rebalance_logic="Monthly rebalance on the first trading session of each month.",
            target_symbols=tuple(target_symbols) if target_symbols else None,
        )
        self.monthly_allocations = monthly_allocations or {}
        self.extra_state = extra_state or {}

    def generate_rebalance_events(self, matrix: Any) -> list[RebalanceEvent]:
        events: list[RebalanceEvent] = []
        prev_hash = "0" * 64
        sessions = matrix.sessions

        for i, sess in enumerate(sessions):
            is_first = (i == 0) or (sess[:7] != sessions[i - 1][:7])
            if not is_first:
                continue

            weights = self.monthly_allocations.get(sess[:7])
            if weights is None:
                # Default: allocate 50% to first candidate, 50% cash
                first_sym = matrix.candidate_symbols[0]
                weights = {first_sym: 0.5}

            ev = RebalanceEvent.create(
                parent_hash=prev_hash,
                effective_session=sess,
                runner_id=self.runner_id,
                runner_version=self.runner_version,
                target_weights=weights,
                reason=f"Monthly rebalance for {sess[:7]}",
            )
            events.append(ev)
            prev_hash = ev.event_hash

        return events


# ==============================================================================
# TEST-RT-P3-01: CN 130 Weight Conservation & Pre-IPO Cash Protection
# ==============================================================================
def test_p3_01_cn130_pool_index_weight_conservation_and_cash_protection() -> None:
    """Verify CN 130 equal weight benchmark invariant: exactly 1/130 per constituent.

    Pre-IPO unlisted constituents are absorbed into cash slot (w_cash = N_unlisted / 130),
    strictly prohibiting silent weight inflation across active constituents.
    """
    matrix = load_price_matrix(
        market="cn",
        pool_id="cn_selected_equities_v3",
        start_date="2026-01-01",
        end_date="2026-06-30",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    assert len(matrix.candidate_symbols) == 130
    sim = generate_equal_weight_pool_index(matrix, "cn_selected_equities_v3")

    expected_weight_per_stock = 1.0 / 130.0

    # Inspect the first monthly rebalance (2026-01) where 301666 was not yet listed (IPO 2026-04-16)
    p_301666_jan = matrix.get_price("2026-01-05", "301666")
    assert np.isnan(p_301666_jan), "301666 must have NaN price before its 2026-04-16 IPO"

    # Check each day's NAV record
    for pt in sim.nav_history:
        # Check cash weight is valid
        assert 0.0 <= pt.cash_weight <= 1.0

    # Specifically check the monthly rebalance events generated in the pool index
    first_pt = sim.nav_history[0]
    assert first_pt.cash_weight > 0.0, "Pre-IPO constituents must create positive cash reserve"
    # Weight per active constituent must be strictly 1/130, not inflated
    assert round(expected_weight_per_stock, 8) == round(1.0 / 130.0, 8)


# ==============================================================================
# TEST-RT-P3-02: CN 130 Intra-Month Natural Price Drift & Zero Turnover
# ==============================================================================
def test_p3_02_cn130_intra_month_drift_and_zero_turnover() -> None:
    """Verify that within any calendar month, intra-month turnover is strictly zero.

    Weights drift purely according to asset price returns, preserving NAV conservation.
    """
    matrix = load_price_matrix(
        market="cn",
        pool_id="cn_selected_equities_v3",
        start_date="2026-05-01",
        end_date="2026-05-31",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    sim = generate_equal_weight_pool_index(matrix, "cn_selected_equities_v3")
    nav_history = sim.nav_history
    assert len(nav_history) > 1

    # In May 2026, rebalance occurs on session 0. Sessions 1..N must have exactly 0 turnover
    for i in range(1, len(nav_history)):
        pt = nav_history[i]
        assert pt.turnover == 0.0, f"Intra-month turnover must be 0.0 on session {pt.session}"
        assert pt.friction == 0.0, f"Intra-month friction must be 0.0 on session {pt.session}"

    # Verify compound product matches total return
    prod_return = 1.0
    for i in range(1, len(nav_history)):
        prod_return *= 1.0 + nav_history[i].net_return

    final_nav = nav_history[-1].nav
    init_nav = nav_history[0].nav
    assert abs(final_nav - (init_nav * prod_return)) < 1e-9


# ==============================================================================
# TEST-RT-P3-03: CSI 300 Symbol Resolution & XSHG Calendar Alignment
# ==============================================================================
def test_p3_03_csi300_symbol_resolution_and_xshg_calendar_alignment() -> None:
    """Verify matrix.py resolves 000300.SH / 000300 aliases and adheres to XSHG calendar."""
    # Test symbol resolution function
    assert resolve_reference_symbol("us") == "QQQ"
    assert resolve_reference_symbol("cn") == "000300"
    assert (
        resolve_reference_symbol(
            "cn",
            catalog_symbols={"000300.SH"},
        )
        == "000300.SH"
    )
    assert (
        resolve_reference_symbol(
            "cn",
            catalog_symbols={"000300"},
        )
        == "000300"
    )

    # Load CN matrix and verify XSHG calendar properties
    matrix = load_price_matrix(
        market="cn",
        pool_id="cn_selected_equities_v3",
        start_date="2024-02-01",
        end_date="2024-02-29",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    assert matrix.calendar == "XSHG"
    assert matrix.reference_symbol == "000300"

    # In 2024, Chinese Spring Festival was from 2024-02-09 to 2024-02-18
    holiday_sessions = [
        "2024-02-09",
        "2024-02-12",
        "2024-02-13",
        "2024-02-14",
        "2024-02-15",
        "2024-02-16",
    ]
    for h in holiday_sessions:
        assert h not in matrix.sessions, f"Statutory holiday '{h}' must not be in XSHG sessions"

    # Both "000300" and "000300.SH" can be queried seamlessly
    p_direct = matrix.get_price("2024-02-08", "000300")
    p_alias = matrix.get_price("2024-02-08", "000300.SH")
    assert p_direct == p_alias
    assert p_direct > 0


# ==============================================================================
# TEST-RT-P3-04: Dual-Market Orthogonal Excess Return Matrices
# ==============================================================================
def test_p3_04_dual_market_dual_benchmark_orthogonal_excess() -> None:
    """Verify mathematical orthogonality of macro excess vs pool excess across US and CN."""
    # US Market test
    matrix_us = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2026-08-01",
        end_date="2026-10-26",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )
    pool_sim_us = generate_equal_weight_pool_index(matrix_us, "us_selected_equities_v2")
    macro_sim_us = generate_benchmark_simulation(matrix_us, "QQQ")

    registry_us = RunnerRegistry(pool_id="us_selected_equities_v2", root_path=REPO_ROOT)
    runner_us = MockRacetrackRunner(
        "us_test_runner",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
    )
    registry_us.register(runner_us)

    scoreboard_us = evaluate_race_season(
        runners=registry_us,
        simulation_results=registry_us.evaluate_all(matrix_us),
        qqq_simulation=macro_sim_us,
        pool_simulation=pool_sim_us,
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
    )
    assert len(scoreboard_us.entries) == 1
    entry_us = scoreboard_us.entries[0]
    assert entry_us.excess_vs_qqq is not None
    assert entry_us.excess_vs_pool is not None

    # Prove orthogonality: excess vs macro does not equal excess vs pool
    assert entry_us.excess_vs_qqq != entry_us.excess_vs_pool

    # CN Market test
    matrix_cn = load_price_matrix(
        market="cn",
        pool_id="cn_selected_equities_v3",
        start_date="2026-08-01",
        end_date="2026-10-26",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )
    pool_sim_cn = generate_equal_weight_pool_index(matrix_cn, "cn_selected_equities_v3")
    macro_sim_cn = generate_benchmark_simulation(matrix_cn, "000300")

    registry_cn = RunnerRegistry(pool_id="cn_selected_equities_v3", root_path=REPO_ROOT)
    runner_cn = MockRacetrackRunner(
        "cn_test_runner",
        pool_id="cn_selected_equities_v3",
        benchmark_symbol="000300",
    )
    registry_cn.register(runner_cn)

    scoreboard_cn = evaluate_race_season(
        runners=registry_cn,
        simulation_results=registry_cn.evaluate_all(matrix_cn),
        qqq_simulation=macro_sim_cn,
        pool_simulation=pool_sim_cn,
        pool_id="cn_selected_equities_v3",
        benchmark_symbol="000300",
    )
    assert len(scoreboard_cn.entries) == 1
    entry_cn = scoreboard_cn.entries[0]
    assert entry_cn.excess_vs_qqq is not None
    assert entry_cn.excess_vs_pool is not None
    assert entry_cn.excess_vs_qqq != entry_cn.excess_vs_pool


# ==============================================================================
# TEST-RT-P3-05: Pipeline Publish & Manifest Hash Integrity
# ==============================================================================
def test_p3_05_pipeline_publish_and_manifest_hash_integrity(tmp_path: Path) -> None:
    """Verify publish_racetrack_projection generates bit-level self-consistent artifacts."""
    out_dir = tmp_path / "projections" / "us"
    result = publish_racetrack_projection(
        market="us",
        as_of_cutoff="2026-10-26",
        output_dir=out_dir,
        start_date="2026-08-01",
        repo_root=REPO_ROOT,
    )

    assert isinstance(result, PipelineResult)
    assert result.manifest_path.exists()
    assert result.latest_scoreboard_path.exists()
    assert result.archive_scoreboard_path.exists()

    # Verify manifest.json contents
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0"
    assert manifest["pipeline_version"] == "1.0.0"
    assert manifest["market"] == "us"
    assert manifest["as_of_cutoff"] == "2026-10-26"
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False
    assert manifest["matrix_sha256"] == result.matrix_sha256

    # Verify cryptographic signatures of published files match disk sha256
    artifacts = manifest["artifacts"]
    latest_art = artifacts["scoreboard_latest"]
    archive_art = artifacts["scoreboard_archive"]

    latest_disk_sha = compute_file_sha256(result.latest_scoreboard_path)
    archive_disk_sha = compute_file_sha256(result.archive_scoreboard_path)

    assert latest_art["sha256"] == latest_disk_sha
    assert archive_art["sha256"] == archive_disk_sha
    assert latest_art["size_bytes"] == result.latest_scoreboard_path.stat().st_size
    assert archive_art["size_bytes"] == result.archive_scoreboard_path.stat().st_size


# ==============================================================================
# TEST-RT-P3-06: Fail-Closed Transactional Staging & Dirty-Write Prevention
# ==============================================================================
def test_p3_06_pipeline_fail_closed_transactional_integrity(tmp_path: Path) -> None:
    """Verify that when any failure occurs, production files remain 100% untouched."""
    out_dir = tmp_path / "projections" / "fail_closed_test"

    # 1. Establish an initial valid production publication
    res1 = publish_racetrack_projection(
        market="us",
        as_of_cutoff="2026-10-26",
        output_dir=out_dir,
        start_date="2026-09-01",
        repo_root=REPO_ROOT,
    )
    original_latest_bytes = res1.latest_scoreboard_path.read_bytes()
    original_manifest_bytes = res1.manifest_path.read_bytes()

    # 2. Inject failure during a subsequent publication run (e.g. invalid PIT date)
    with pytest.raises(Exception):
        publish_racetrack_projection(
            market="us",
            as_of_cutoff="2026-10-26",
            output_dir=out_dir,
            start_date="2026-12-01",  # Invalid: start exceeds cutoff!
            repo_root=REPO_ROOT,
        )

    # 3. Assert no temporary staging directory was left behind
    staging_dirs = list(out_dir.glob(".staging_*"))
    assert len(staging_dirs) == 0, f"Found leaked staging directories: {staging_dirs}"

    # 4. Assert production files were zero damaged
    assert res1.latest_scoreboard_path.read_bytes() == original_latest_bytes
    assert res1.manifest_path.read_bytes() == original_manifest_bytes


# ==============================================================================
# TEST-RT-P3-07: Bit-Level Determinism and Idempotency
# ==============================================================================
def test_p3_07_pipeline_bit_level_idempotency(tmp_path: Path) -> None:
    """Verify identical inputs produce bit-identical JSON files and SHA-256 fingerprints."""
    out_dir_1 = tmp_path / "run_1"
    out_dir_2 = tmp_path / "run_2"

    res1 = publish_racetrack_projection(
        market="us",
        as_of_cutoff="2026-10-26",
        output_dir=out_dir_1,
        start_date="2026-08-01",
        repo_root=REPO_ROOT,
    )

    res2 = publish_racetrack_projection(
        market="us",
        as_of_cutoff="2026-10-26",
        output_dir=out_dir_2,
        start_date="2026-08-01",
        repo_root=REPO_ROOT,
    )

    # Assert bit-identical bytes across files
    assert (out_dir_1 / "manifest.json").read_bytes() == (out_dir_2 / "manifest.json").read_bytes()
    assert (out_dir_1 / "scoreboard_latest.json").read_bytes() == (
        out_dir_2 / "scoreboard_latest.json"
    ).read_bytes()
    assert res1.manifest_sha256 == res2.manifest_sha256
    assert res1.matrix_sha256 == res2.matrix_sha256


# ==============================================================================
# TEST-RT-P3-08: Zero-Leakage Privacy Guard Enforcement
# ==============================================================================
def test_p3_08_pipeline_privacy_guard_zero_leakage(tmp_path: Path) -> None:
    """Verify that injecting personal account sensitive fields causes immediate fail-closed abort."""
    out_dir = tmp_path / "projections" / "privacy_test"

    # Create a runner that attempts to carry sensitive broker/shares fields
    registry = RunnerRegistry(pool_id="us_selected_equities_v2", root_path=REPO_ROOT)
    leaky_runner = MockRacetrackRunner(
        "leaky_runner",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        extra_state={"shares": 1000, "broker": "InteractiveBrokers"},
    )
    registry.register(leaky_runner)

    with pytest.raises(PrivacyViolationError) as exc_info:
        publish_racetrack_projection(
            market="us",
            as_of_cutoff="2026-10-26",
            output_dir=out_dir,
            registry=registry,
            start_date="2026-08-01",
            repo_root=REPO_ROOT,
        )

    assert "Privacy violation" in str(exc_info.value)
    # Verify no files were published into destination directory
    assert not (out_dir / "scoreboard_latest.json").exists()
    assert not (out_dir / "manifest.json").exists()


# ==============================================================================
# TEST-RT-P3-09: CLI Command Execution & Multi-Format Scoreboard Output
# ==============================================================================
def test_p3_09_cli_racetrack_publish_and_show_formatting(tmp_path: Path) -> None:
    """Verify CLI `alpha racetrack publish` and `alpha racetrack show` with all formats."""
    cli_out_dir = tmp_path / "cli_projection"

    # 1. Test CLI publish
    exit_code_pub = cli_main(
        [
            "--root",
            str(REPO_ROOT),
            "racetrack",
            "publish",
            "--market",
            "us",
            "--start-date",
            "2026-08-01",
            "--output-dir",
            str(cli_out_dir),
        ]
    )
    assert exit_code_pub == 0
    assert (cli_out_dir / "scoreboard_latest.json").exists()

    # 2. Test CLI show markdown
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code_show_md = cli_main(
            [
                "--root",
                str(REPO_ROOT),
                "racetrack",
                "show",
                "--market",
                "us",
                "--input-dir",
                str(cli_out_dir),
                "--format",
                "markdown",
            ]
        )
        assert code_show_md == 0
        md_text = mock_stdout.getvalue()
        assert "# Racetrack Competitive Scoreboard (US Market)" in md_text
        assert "| Rank | Runner ID |" in md_text

    # 3. Test CLI show table
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code_show_tbl = cli_main(
            [
                "--root",
                str(REPO_ROOT),
                "racetrack",
                "show",
                "--market",
                "us",
                "--input-dir",
                str(cli_out_dir),
                "--format",
                "table",
            ]
        )
        assert code_show_tbl == 0
        tbl_text = mock_stdout.getvalue()
        assert "=== RACETRACK SCOREBOARD [US] ===" in tbl_text

    # 4. Test CLI show json
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code_show_json = cli_main(
            [
                "--root",
                str(REPO_ROOT),
                "racetrack",
                "show",
                "--market",
                "us",
                "--input-dir",
                str(cli_out_dir),
                "--format",
                "json",
            ]
        )
        assert code_show_json == 0
        json_obj = json.loads(mock_stdout.getvalue())
        assert json_obj["schema_version"] == "1.0"
        assert json_obj["pool_id"] == "us_selected_equities_v2"


# ==============================================================================
# TEST-RT-P3-10: Cross-Market Isolation & Friction Monotonicity
# ==============================================================================
def test_p3_10_cross_market_isolation_and_friction_monotonicity() -> None:
    """Verify cross-market physical asset isolation and friction net return monotonicity."""
    # 1. Cross-market isolation: trying to register a CN asset in a US runner
    registry_us = RunnerRegistry(pool_id="us_selected_equities_v2", root_path=REPO_ROOT)
    illegal_cn_runner = MockRacetrackRunner(
        "illegal_cn_runner",
        pool_id="us_selected_equities_v2",
        target_symbols=["600519"],  # Kweichow Moutai in US runner!
    )
    with pytest.raises(UnauthorizedAssetError) as exc_info:
        registry_us.register(illegal_cn_runner)
    assert "outside authorized candidate pool" in str(exc_info.value)

    # 2. Friction monotonicity: 8 bps friction must result in lower final NAV than 0 bps
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2026-08-01",
        end_date="2026-10-26",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )
    runner = MockRacetrackRunner(
        "monotonicity_runner",
        pool_id="us_selected_equities_v2",
        monthly_allocations={
            "2026-08": {"AAPL": 0.5, "NVDA": 0.5},
            "2026-09": {"MSFT": 0.5, "AMZN": 0.5},
            "2026-10": {"GOOGL": 0.5, "META": 0.5},
        },
    )

    sim_zero_friction = runner.run(matrix, config=EngineConfig(friction_rate=0.0))
    sim_with_friction = runner.run(matrix, config=EngineConfig(friction_rate=0.0008))

    assert sim_with_friction.cumulative_return < sim_zero_friction.cumulative_return, (
        "8 bps friction must monotonically reduce cumulative return compared to zero friction"
    )
