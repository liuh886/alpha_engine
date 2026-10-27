"""Unit and integration test suite for Racetrack Phase 1 Minimal Stack.

Covers TEST-RT-01 through TEST-RT-08 specified in docs/architecture/racetrack_minimal_stack_spec.md
and PR #1306 §12.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
import pytest

from src.racetrack.contracts import (
    CalendarSessionError,
    EngineConfig,
    LedgerTamperedError,
    MissingPriceDataError,
    PriceMatrix,
    PrivacyViolationError,
    RebalanceEvent,
    UnauthorizedAssetError,
    WeightConstraintError,
    assert_privacy_clean,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.ledger import EventLedger
from src.racetrack.matrix import load_price_matrix
from src.racetrack.pool_index import generate_equal_weight_pool_index

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# TEST-RT-01: Calendar Alignment, Forward-Fill Prohibition, and NaN Filling
# ---------------------------------------------------------------------------
def test_rt_01_calendar_alignment_and_nan_filling() -> None:
    """TEST-RT-01: Verify official XNYS calendar alignment, zero weekend/holiday leakage,
    and strict NaN filling for unlisted assets without forward-fill.
    """
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-01-16",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    # 1. Official sessions check: MLK Day (2024-01-15) was a market holiday
    assert "2024-01-15" not in matrix.sessions
    # Weekends must not exist
    for weekend_date in ("2024-01-06", "2024-01-07", "2024-01-13", "2024-01-14"):
        assert weekend_date not in matrix.sessions

    # 2. Strict NaN check for unlisted asset: ARM IPO was 2023-09-14
    matrix_arm_pre_ipo = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2023-01-03",
        end_date="2023-01-10",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )
    for sess in matrix_arm_pre_ipo.sessions:
        price = matrix_arm_pre_ipo.get_price(sess, "ARM")
        assert np.isnan(price), f"Expected NaN for pre-IPO ARM on {sess}, got {price}"

    # 3. Cutoff enforcement
    matrix_cutoff = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-01-20",
        as_of_cutoff="2024-01-05",
        root_path=REPO_ROOT,
    )
    assert matrix_cutoff.end_session <= "2024-01-05"
    for s in matrix_cutoff.sessions:
        assert s <= "2024-01-05"

    # 4. Out-of-bounds holiday/weekend range raises CalendarSessionError
    with pytest.raises(CalendarSessionError):
        load_price_matrix(
            market="us",
            pool_id="us_selected_equities_v2",
            start_date="2024-01-06",
            end_date="2024-01-07",  # Weekend only
            as_of_cutoff="2026-10-26",
            root_path=REPO_ROOT,
        )


# ---------------------------------------------------------------------------
# TEST-RT-02: Price Matrix SHA-256 Determinism and Source Immutability
# ---------------------------------------------------------------------------
def test_rt_02_price_matrix_sha256_determinism_and_source_immutability() -> None:
    """TEST-RT-02: Verify identical matrix SHA-256 fingerprints across independent runs
    and prove zero mutation to underlying evidence JSON files.
    """
    evidence_dir = REPO_ROOT / "data" / "research" / "market_evidence" / "us" / "symbols"
    test_symbols = ["AAPL", "QQQ", "MSFT"]
    shas_before: dict[str, str] = {}
    for sym in test_symbols:
        f_path = evidence_dir / f"{sym}.json"
        assert f_path.exists()
        shas_before[sym] = hashlib.sha256(f_path.read_bytes()).hexdigest()

    # Run 1
    m1 = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-01-31",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    # Run 2
    m2 = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-01-31",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    # Determinism assertion
    assert m1.matrix_sha256 == m2.matrix_sha256
    assert len(m1.matrix_sha256) == 64
    pd.testing.assert_frame_equal(m1.prices, m2.prices)

    # Source immutability assertion
    for sym in test_symbols:
        f_path = evidence_dir / f"{sym}.json"
        sha_after = hashlib.sha256(f_path.read_bytes()).hexdigest()
        assert sha_after == shas_before[sym], f"Source evidence file for {sym} was mutated!"


# ---------------------------------------------------------------------------
# TEST-RT-03: Q Ledger Hash Chain Integrity and Tamper Detection
# ---------------------------------------------------------------------------
def test_rt_03_ledger_hash_chain_integrity_and_tamper_detection() -> None:
    """TEST-RT-03: Verify genesis block anchoring ('0'*64), seamless hash-chaining,
    and fail-closed detection when any byte or reason in JSONL is modified.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger_path = Path(tmp_dir) / "test_runner_v1.jsonl"
        ledger = EventLedger.create(ledger_path, runner_id="test_runner", runner_version="1.0.0")

        # 1. Genesis event
        e1 = ledger.append(
            effective_session="2024-01-02",
            target_weights={"AAPL": 0.5, "MSFT": 0.5},
            reason="Genesis allocation",
        )
        assert e1.parent_hash == "0" * 64
        assert ledger.tip_hash == e1.event_hash

        # 2. Sequential events
        e2 = ledger.append(
            effective_session="2024-01-03",
            target_weights={"AAPL": 0.4, "MSFT": 0.6},
            reason="Shift to MSFT",
        )
        assert e2.parent_hash == e1.event_hash

        e3 = ledger.append(
            effective_session="2024-01-04",
            target_weights={"AAPL": 0.3, "MSFT": 0.7},
            reason="Further shift",
        )
        assert e3.parent_hash == e2.event_hash

        # Verification must pass
        assert ledger.verify() is True

        # Test dense panel expansion
        panel = ledger.to_dense_panel(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
        assert panel.loc["2024-01-02", "AAPL"] == 0.5
        assert panel.loc["2024-01-03", "AAPL"] == 0.4
        assert panel.loc["2024-01-04", "AAPL"] == 0.3
        # Forward fill on 2024-01-05
        assert panel.loc["2024-01-05", "AAPL"] == 0.3

        # 3. Tamper test: Alter reason on line 1
        raw_lines = ledger_path.read_text(encoding="utf-8").splitlines()
        tampered_line_1 = raw_lines[0].replace("Genesis allocation", "Tampered allocation")
        ledger_path.write_text("\n".join([tampered_line_1, raw_lines[1], raw_lines[2]]) + "\n", encoding="utf-8")

        with pytest.raises(LedgerTamperedError):
            ledger.verify()

        # 4. Tamper test: Alter target weight on line 2 (preserving sum <= 1.0)
        tampered_line_2 = raw_lines[1].replace('"AAPL":0.4', '"AAPL":0.35')
        ledger_path.write_text("\n".join([raw_lines[0], tampered_line_2, raw_lines[2]]) + "\n", encoding="utf-8")

        with pytest.raises(LedgerTamperedError):
            ledger.verify()


# ---------------------------------------------------------------------------
# TEST-RT-04: Strict Personal Account Privacy Guard
# ---------------------------------------------------------------------------
def test_rt_04_privacy_guard_negative_tests() -> None:
    """TEST-RT-04: Verify fail-closed PrivacyViolationError when any live personal
    account field is injected into research contracts or ledgers.
    """
    # 1. Prohibited fields directly in assert_privacy_clean
    prohibited_keys = [
        "shares",
        "qty",
        "lots",
        "total_cost",
        "cost_basis",
        "cash_balance",
        "broker",
        "account_id",
        "pnl",
        "realized_pnl",
        "executed_price",
    ]
    for key in prohibited_keys:
        with pytest.raises(PrivacyViolationError):
            assert_privacy_clean({key: 100})

    # 2. Prohibited field inside target_weights
    with pytest.raises(PrivacyViolationError):
        RebalanceEvent.create(
            parent_hash="0" * 64,
            effective_session="2024-01-02",
            runner_id="runner_1",
            runner_version="1.0",
            target_weights={"AAPL": 0.5, "shares": 100},
            reason="Violation attempt",
        )

    # 3. Prohibited field in ledger append
    with tempfile.TemporaryDirectory() as tmp_dir:
        lp = Path(tmp_dir) / "privacy.jsonl"
        ledger = EventLedger.create(lp, "runner_1", "1.0")
        with pytest.raises(PrivacyViolationError):
            ledger.append(
                effective_session="2024-01-02",
                target_weights={"AAPL": 0.5, "total_cost": 50000.0},
                reason="Violation",
            )


# ---------------------------------------------------------------------------
# TEST-RT-05: Mathematical Weight Drift and One-Sided Turnover Conservation
# ---------------------------------------------------------------------------
def test_rt_05_weight_drift_and_one_sided_turnover_conservation() -> None:
    """TEST-RT-05: Controlled synthetic test validating exact formula for daily
    weight drift and one-sided turnover conservation law.
    """
    # Create synthetic 3-session price matrix for 2 stocks: STOCK_A, STOCK_B, and reference QQQ
    # Day 0: A=100, B=100, QQQ=100
    # Day 1: A=120 (+20%), B=80 (-20%), QQQ=100
    # Day 2: A=120 (0%), B=80 (0%), QQQ=100
    sessions = ("2024-01-02", "2024-01-03", "2024-01-04")
    prices_df = pd.DataFrame(
        data={
            "STOCK_A": [100.0, 120.0, 120.0],
            "STOCK_B": [100.0, 80.0, 80.0],
            "QQQ": [100.0, 100.0, 100.0],
        },
        index=list(sessions),
    )
    prices_df.index.name = "session"

    synthetic_matrix = PriceMatrix(
        market="us",
        pool_id="synthetic_pool",
        reference_symbol="QQQ",
        calendar="XNYS",
        start_session=sessions[0],
        end_session=sessions[-1],
        sessions=sessions,
        candidate_symbols=("STOCK_A", "STOCK_B"),
        symbols=("STOCK_A", "STOCK_B", "QQQ"),
        prices=prices_df,
        matrix_sha256="0" * 64,
        source_evidence_hashes={},
    )

    # Initial allocation at Day 0: 50% A, 50% B
    e0 = RebalanceEvent.create(
        parent_hash="0" * 64,
        effective_session="2024-01-02",
        runner_id="math_runner",
        runner_version="1.0",
        target_weights={"STOCK_A": 0.5, "STOCK_B": 0.5},
        reason="Initial 50/50",
    )

    # Rebalance on Day 1: Shift to 40% A, 60% B
    e1 = RebalanceEvent.create(
        parent_hash=e0.event_hash,
        effective_session="2024-01-03",
        runner_id="math_runner",
        runner_version="1.0",
        target_weights={"STOCK_A": 0.4, "STOCK_B": 0.6},
        reason="Rebalance 40/60",
    )

    result = simulate_portfolio(
        matrix=synthetic_matrix,
        ledger_events=[e0, e1],
        config=EngineConfig(friction_rate=0.0008),
    )

    nav_points = result.nav_history
    # Day 0: Inception
    assert nav_points[0].session == "2024-01-02"
    assert nav_points[0].nav == 1.0
    assert nav_points[0].weights == {"STOCK_A": 0.5, "STOCK_B": 0.5}

    # Day 1:
    # Asset A ret = +0.20, Asset B ret = -0.20
    # r_gross = 0.5 * 0.20 + 0.5 * (-0.20) = 0.0
    # Drifted weight A: 0.5 * 1.20 / 1.00 = 0.60
    # Drifted weight B: 0.5 * 0.80 / 1.00 = 0.40
    # Target weight: A=0.40, B=0.60
    # One-sided turnover = 0.5 * (|0.40 - 0.60| + |0.60 - 0.40| + |0 - 0|) = 0.5 * 0.40 = 0.20
    # Friction = 0.20 * 0.0008 = 0.00016
    # r_net = 0.0 - 0.00016 = -0.00016
    # NAV(Day 1) = 1.0 * (1 - 0.00016) = 0.99984
    pt1 = nav_points[1]
    assert pt1.session == "2024-01-03"
    assert pytest.approx(pt1.gross_return, abs=1e-8) == 0.0
    assert pytest.approx(pt1.turnover, abs=1e-8) == 0.20
    assert pytest.approx(pt1.friction, abs=1e-8) == 0.00016
    assert pytest.approx(pt1.net_return, abs=1e-8) == -0.00016
    assert pytest.approx(pt1.nav, abs=1e-8) == 0.99984
    # Post-rebalance weights on Day 1 are the target weights
    assert pytest.approx(pt1.weights["STOCK_A"], abs=1e-8) == 0.40
    assert pytest.approx(pt1.weights["STOCK_B"], abs=1e-8) == 0.60


# ---------------------------------------------------------------------------
# TEST-RT-06: Friction Sensitivity Monotonicity (0 bps > 8 bps > 15 bps)
# ---------------------------------------------------------------------------
def test_rt_06_friction_sensitivity_monotonicity() -> None:
    """TEST-RT-06: Verify that across identical portfolios with turnover > 0,
    NAV and cumulative return are strictly monotonic: 0 bps > 8 bps > 15 bps.
    """
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-03-28",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    # Monthly equal-weight pool index has 2 rebalances (Feb 1 and Mar 1) with turnover > 0
    res_0bps = generate_equal_weight_pool_index(matrix, "us_selected_equities_v2", EngineConfig(friction_rate=0.0))
    res_8bps = generate_equal_weight_pool_index(matrix, "us_selected_equities_v2", EngineConfig(friction_rate=0.0008))
    res_15bps = generate_equal_weight_pool_index(matrix, "us_selected_equities_v2", EngineConfig(friction_rate=0.0015))

    # Assert cumulative turnover is identical and positive
    assert res_0bps.cumulative_turnover > 0.0
    assert pytest.approx(res_0bps.cumulative_turnover, abs=1e-6) == res_8bps.cumulative_turnover
    assert pytest.approx(res_8bps.cumulative_turnover, abs=1e-6) == res_15bps.cumulative_turnover

    # Assert strict monotonicity: 0 bps > 8 bps > 15 bps
    assert res_0bps.cumulative_return > res_8bps.cumulative_return > res_15bps.cumulative_return
    assert res_0bps.nav_history[-1].nav > res_8bps.nav_history[-1].nav > res_15bps.nav_history[-1].nav
    assert res_0bps.annualized_cagr > res_8bps.annualized_cagr > res_15bps.annualized_cagr


# ---------------------------------------------------------------------------
# TEST-RT-07: Pool Index Benchmark and QQQ Excess Return Calculation
# ---------------------------------------------------------------------------
def test_rt_07_us87_pool_index_generation_and_excess_vs_qqq() -> None:
    """TEST-RT-07: Verify US 87 pool equal-weight index generation, monthly rebalance
    timing, intra-month zero turnover, and excess return vs QQQ.
    """
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-03-28",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    result = generate_equal_weight_pool_index(matrix, "us_selected_equities_v2")

    # Rebalances must occur only on the first trading session of Feb and Mar
    rebalance_sessions = [pt.session for pt in result.nav_history if pt.turnover > 0]
    assert rebalance_sessions == ["2024-02-01", "2024-03-01"]

    # All non-rebalance days must have exactly 0 turnover
    for pt in result.nav_history:
        if pt.session not in rebalance_sessions:
            assert pt.turnover == 0.0
            assert pt.friction == 0.0

    # Benchmark excess return check
    assert result.annualized_excess_return != 0.0
    # MDD must be non-positive float
    assert result.max_drawdown <= 0.0
    # Output dictionary contract check
    summary = result.to_dict()
    assert "annualized_cagr" in summary
    assert "annualized_sharpe" in summary
    assert "annualized_excess_return" in summary
    assert "max_drawdown" in summary


# ---------------------------------------------------------------------------
# TEST-RT-08: End-to-End Real Data Full Lifecycle and Reproducibility
# ---------------------------------------------------------------------------
def test_rt_08_end_to_end_real_data_lifecycle_and_reproducibility() -> None:
    """TEST-RT-08: End-to-end simulation on real repository data with multi-step
    rebalances, DataFrame projection conversion, and 100% bit-level reproducibility.
    """
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-06-28",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger_file = Path(tmp_dir) / "strategy_top5_v1.jsonl"
        ledger = EventLedger.create(ledger_file, "strategy_top5", "1.0.0")

        # Initial allocation on 2024-01-02: 5 tech giants (20% each)
        ledger.append(
            effective_session="2024-01-02",
            target_weights={"AAPL": 0.20, "MSFT": 0.20, "NVDA": 0.20, "AMZN": 0.20, "GOOGL": 0.20},
            reason="Q1 equal allocation",
        )

        # Rebalance at start of Q2: 2024-04-01
        ledger.append(
            effective_session="2024-04-01",
            target_weights={"AAPL": 0.15, "MSFT": 0.25, "NVDA": 0.30, "AMZN": 0.15, "GOOGL": 0.15},
            reason="Q2 momentum tilt to NVDA/MSFT",
        )

        assert ledger.verify() is True

        # Run 1
        res1 = simulate_portfolio(matrix, ledger.events)
        df1 = res1.to_dataframe()

        # Run 2
        res2 = simulate_portfolio(matrix, ledger.events)
        df2 = res2.to_dataframe()

        # Bit-level reproducibility assertion
        np.testing.assert_allclose(df1["nav"].values, df2["nav"].values, rtol=1e-12, atol=1e-12)
        assert res1.cumulative_return == res2.cumulative_return
        assert res1.annualized_sharpe == res2.annualized_sharpe
        assert res1.max_drawdown == res2.max_drawdown

        # DataFrame projection structure assertions
        assert "nav" in df1.columns
        assert "gross_return" in df1.columns
        assert "net_return" in df1.columns
        assert "turnover" in df1.columns
        assert "friction" in df1.columns
        assert "drawdown" in df1.columns
        assert len(df1) == len(matrix.sessions)
        assert (df1["nav"] > 0).all()


# ---------------------------------------------------------------------------
# Additional Boundary & Negative Cases
# ---------------------------------------------------------------------------
def test_unauthorized_asset_blocked() -> None:
    """Verify that targeting an asset not in the authorized pool fails closed."""
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-01-10",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )
    unauthorized_event = RebalanceEvent.create(
        parent_hash="0" * 64,
        effective_session="2024-01-02",
        runner_id="rogue_runner",
        runner_version="1.0",
        target_weights={"UNKNOWN_STOCK_XYZ": 0.5},
        reason="Illegal asset",
    )
    with pytest.raises(UnauthorizedAssetError):
        simulate_portfolio(matrix, [unauthorized_event])


def test_weight_constraint_violations() -> None:
    """Verify that sum(weights) > 1.0 or negative weights are rejected."""
    with pytest.raises(WeightConstraintError):
        RebalanceEvent.create(
            parent_hash="0" * 64,
            effective_session="2024-01-02",
            runner_id="runner_1",
            runner_version="1.0",
            target_weights={"AAPL": 0.6, "MSFT": 0.5},  # Sum = 1.1
            reason="Exceeds 100%",
        )

    with pytest.raises(WeightConstraintError):
        RebalanceEvent.create(
            parent_hash="0" * 64,
            effective_session="2024-01-02",
            runner_id="runner_1",
            runner_version="1.0",
            target_weights={"AAPL": -0.1, "MSFT": 0.5},  # Negative
            reason="Negative short position",
        )
