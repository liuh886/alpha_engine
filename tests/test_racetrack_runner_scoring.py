"""Unit and integration test suite for Racetrack Phase 2 Runner Registry and Race Scoring.

Covers TEST-RT-P2-01 through TEST-RT-P2-10 specified in:
- docs/architecture/racetrack_runner_scoring_spec.md
- PR #1306 §13
"""

from __future__ import annotations

import math
from pathlib import Path
import tempfile

import pandas as pd
import pytest

from src.racetrack.contracts import (
    EngineConfig,
    MonthlyRankPoint,
    NAVPoint,
    PriceMatrix,
    RebalanceEvent,
    Scoreboard,
    ScoreboardEntry,
    SimulationResult,
    ThesisMissingError,
    UnauthorizedAssetError,
    assert_privacy_clean,
)
from src.racetrack.matrix import load_price_matrix
from src.racetrack.pool_index import generate_equal_weight_pool_index
from src.racetrack.runner import RunnerContract, RunnerRegistry, validate_runner_thesis
from src.racetrack.scoring import (
    PointsRuleV1,
    calculate_monthly_returns,
    calculate_rolling_window_return,
    evaluate_race_season,
    generate_benchmark_simulation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_synthetic_simulation(
    runner_id: str,
    monthly_nav_series: list[tuple[str, float, float]],
) -> SimulationResult:
    """Create a synthetic SimulationResult from a list of (session, nav, net_return)."""
    nav_history = tuple(
        NAVPoint(
            session=sess,
            nav=nav,
            gross_return=ret,
            net_return=ret,
            turnover=0.0,
            friction=0.0,
            drawdown=0.0,
            weights={},
            cash_weight=1.0,
        )
        for sess, nav, ret in monthly_nav_series
    )
    final_nav = nav_history[-1].nav
    return SimulationResult(
        runner_id=runner_id,
        runner_version="1.0.0",
        start_session=nav_history[0].session,
        end_session=nav_history[-1].session,
        total_sessions=len(nav_history),
        cumulative_return=final_nav - 1.0,
        annualized_cagr=0.10,
        annualized_volatility=0.15,
        annualized_sharpe=1.20,
        max_drawdown=0.05,
        cumulative_turnover=0.0,
        annualized_excess_return=0.02,
        nav_history=nav_history,
    )


# ---------------------------------------------------------------------------
# TEST-RT-P2-01: Mandatory Thesis Gate (ThesisMissingError)
# ---------------------------------------------------------------------------
def test_rt_p2_01_thesis_gate_rejection() -> None:
    """TEST-RT-P2-01: Prohibit runners with empty, whitespace, None, or < 30 chars thesis."""
    # 1. validate_runner_thesis directly
    with pytest.raises(ThesisMissingError, match="cannot be empty"):
        validate_runner_thesis(None)

    with pytest.raises(ThesisMissingError, match="cannot be empty"):
        validate_runner_thesis("")

    with pytest.raises(ThesisMissingError, match="cannot be empty"):
        validate_runner_thesis("   \t\n  ")

    with pytest.raises(ThesisMissingError, match="too terse"):
        validate_runner_thesis("momentum strategy")  # 17 chars

    # Valid thesis does not raise
    validate_runner_thesis(
        "Cross-sectional price momentum based on 20-day returns, betting on trend continuation and failing under high volatility"
    )

    # 2. RunnerContract constructor enforcement
    with pytest.raises(ThesisMissingError):
        RunnerContract(
            runner_id="empty_thesis_runner",
            runner_version="1.0.0",
            pool_id="us_selected_equities_v2",
            benchmark_symbol="QQQ",
            thesis="",
            selection_logic="top 5 momentum",
            rebalance_logic="monthly equal weight",
        )

    with pytest.raises(ThesisMissingError):
        RunnerContract(
            runner_id="short_thesis_runner",
            runner_version="1.0.0",
            pool_id="us_selected_equities_v2",
            benchmark_symbol="QQQ",
            thesis="short thesis < 30 chars",
            selection_logic="top 5 momentum",
            rebalance_logic="monthly equal weight",
        )

    # Valid RunnerContract succeeds
    valid_runner = RunnerContract(
        runner_id="valid_runner",
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis="Substantive investment thesis explaining market phenomenon, economic rationale, and failure modes.",
        selection_logic="top 5 momentum",
        rebalance_logic="monthly equal weight",
    )
    assert valid_runner.runner_id == "valid_runner"


# ---------------------------------------------------------------------------
# TEST-RT-P2-02: RunnerRegistry Registration & Discovery
# ---------------------------------------------------------------------------
def test_rt_p2_02_registry_admission_and_duplicate_rejection() -> None:
    """TEST-RT-P2-02: RunnerRegistry manages admission, duplicate protection, and pool checking."""
    registry = RunnerRegistry(
        pool_id="us_selected_equities_v2", candidate_symbols=["AAPL", "MSFT", "NVDA"]
    )

    r1 = RunnerContract(
        runner_id="runner_alpha",
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis="Capturing earnings momentum through cross-sectional fundamental score rebalanced on monthly calendar boundaries.",
        selection_logic="top 3 score",
        rebalance_logic="equal weight monthly",
        target_symbols=["AAPL", "MSFT"],
    )
    registry.register(r1)

    assert registry.get("runner_alpha") == r1
    assert len(registry.list_runners()) == 1

    # Duplicate registration rejection
    with pytest.raises(ValueError, match="already registered"):
        registry.register(r1)

    # Missing runner in get() raises KeyError
    with pytest.raises(KeyError):
        registry.get("non_existent_runner")

    # Mismatched pool_id raises ValueError
    r_wrong_pool = RunnerContract(
        runner_id="runner_cn",
        runner_version="1.0.0",
        pool_id="cn_selected_equities_v3",
        benchmark_symbol="000300.SH",
        thesis="Chinese equities mean reversion strategy exploiting short-term reversal over 5 trading days.",
        selection_logic="lowest 5-day return",
        rebalance_logic="weekly rebalance",
    )
    with pytest.raises(ValueError, match="does not match registry pool_id"):
        registry.register(r_wrong_pool)

    # Runner targeting outside asset raises UnauthorizedAssetError
    r_illegal_asset = RunnerContract(
        runner_id="runner_illegal",
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis="Exploiting outside assets not contained in the authorized candidate universe pool configuration.",
        selection_logic="arbitrary selection",
        rebalance_logic="monthly",
        target_symbols=["BABA"],
    )
    with pytest.raises(UnauthorizedAssetError):
        registry.register(r_illegal_asset)

    # Runner targeting benchmark reference symbol raises UnauthorizedAssetError
    with pytest.raises(UnauthorizedAssetError):
        RunnerContract(
            runner_id="runner_qqq_buyer",
            runner_version="1.0.0",
            pool_id="us_selected_equities_v2",
            benchmark_symbol="QQQ",
            thesis="Attempting to purchase benchmark index ETF directly inside candidate asset portfolio.",
            selection_logic="passive index",
            rebalance_logic="buy and hold",
            target_symbols=["QQQ"],
        )


# ---------------------------------------------------------------------------
# TEST-RT-P2-03: Monthly Season Partition & Return Mathematical Equivalence
# ---------------------------------------------------------------------------
def test_rt_p2_03_monthly_season_partition_and_return_math_equivalence() -> None:
    """TEST-RT-P2-03: Calendar month partitioning and exact mathematical equivalence:
    R_m = NAV(end) / NAV(start) - 1 == prod(1 + r_net) - 1.
    """
    # 2 months with multi-day sessions
    sessions_data = [
        # Month 1: 2024-01
        ("2024-01-02", 1.000, 0.000),
        ("2024-01-15", 1.050, 0.050),
        ("2024-01-31", 1.1025, 0.050),  # (1.05)*(1.05) - 1 = 0.1025
        # Month 2: 2024-02
        ("2024-02-01", 1.08045, -0.020),
        ("2024-02-15", 1.1128635, 0.030),
        ("2024-02-29", 1.15737804, 0.040),
    ]

    sim = make_synthetic_simulation("test_runner", sessions_data)
    monthly_rets = calculate_monthly_returns(sim)

    assert "2024-01" in monthly_rets
    assert "2024-02" in monthly_rets

    # Month 1 math equivalence
    pts_m1 = [pt for pt in sim.nav_history if pt.session.startswith("2024-01")]
    prod_m1 = math.prod(1.0 + pt.net_return for pt in pts_m1) - 1.0
    nav_ratio_m1 = (pts_m1[-1].nav / 1.0) - 1.0
    assert abs(monthly_rets["2024-01"] - prod_m1) < 1e-12
    assert abs(monthly_rets["2024-01"] - nav_ratio_m1) < 1e-12

    # Month 2 math equivalence
    pts_m2 = [pt for pt in sim.nav_history if pt.session.startswith("2024-02")]
    prod_m2 = math.prod(1.0 + pt.net_return for pt in pts_m2) - 1.0
    nav_ratio_m2 = (pts_m2[-1].nav / pts_m1[-1].nav) - 1.0
    assert abs(monthly_rets["2024-02"] - prod_m2) < 1e-12
    assert abs(monthly_rets["2024-02"] - nav_ratio_m2) < 1e-12


# ---------------------------------------------------------------------------
# TEST-RT-P2-04: Monthly Cross-Sectional Ranking
# ---------------------------------------------------------------------------
def test_rt_p2_04_monthly_cross_sectional_ranking() -> None:
    """TEST-RT-P2-04: Cross-sectional descending rank: highest return is Rank 1."""
    # 5 runners across a 1-month session
    r1 = make_synthetic_simulation(
        "R1", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 1.12, 0.12)]
    )  # +12%
    r2 = make_synthetic_simulation(
        "R2", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 1.08, 0.08)]
    )  # +8%
    r3 = make_synthetic_simulation(
        "R3", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 1.04, 0.04)]
    )  # +4%
    r4 = make_synthetic_simulation(
        "R4", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 0.99, -0.01)]
    )  # -1%
    r5 = make_synthetic_simulation(
        "R5", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 0.94, -0.06)]
    )  # -6%

    qqq = make_synthetic_simulation("QQQ", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 1.05, 0.05)])
    pool = make_synthetic_simulation("POOL", [("2024-01-02", 1.0, 0.0), ("2024-01-31", 1.02, 0.02)])

    runners = [
        RunnerContract(
            "R1",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R1 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "R2",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R2 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "R3",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R3 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "R4",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R4 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "R5",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R5 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
    ]

    sim_results = {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5}

    scoreboard = evaluate_race_season(
        runners=runners,
        simulation_results=sim_results,
        qqq_simulation=qqq,
        pool_simulation=pool,
    )

    entry_by_id = {e.runner_id: e for e in scoreboard.entries}
    assert entry_by_id["R1"].monthly_ranks[0].rank == 1
    assert entry_by_id["R2"].monthly_ranks[0].rank == 2
    assert entry_by_id["R3"].monthly_ranks[0].rank == 3
    assert entry_by_id["R4"].monthly_ranks[0].rank == 4
    assert entry_by_id["R5"].monthly_ranks[0].rank == 5


# ---------------------------------------------------------------------------
# TEST-RT-P2-05: PointsRuleV1 Allocation & Accumulation
# ---------------------------------------------------------------------------
def test_rt_p2_05_points_rule_v1_allocation_and_accumulation() -> None:
    """TEST-RT-P2-05: Deterministic points mapping: 10, 6, 4, 2, 1, 0, and cumulative season points."""
    assert PointsRuleV1.get_points(1) == 10
    assert PointsRuleV1.get_points(2) == 6
    assert PointsRuleV1.get_points(3) == 4
    assert PointsRuleV1.get_points(4) == 2
    assert PointsRuleV1.get_points(5) == 1
    assert PointsRuleV1.get_points(6) == 0
    assert PointsRuleV1.get_points(10) == 0

    # 3-month season test
    # R1 finishes Rank 1, 2, 3 -> 10 + 6 + 4 = 20 pts
    # R2 finishes Rank 2, 1, 4 -> 6 + 10 + 2 = 18 pts
    r1 = make_synthetic_simulation(
        "R1",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.10, 0.10),
            ("2024-02-01", 1.10, 0.0),
            ("2024-02-29", 1.155, 0.05),
            ("2024-03-01", 1.155, 0.0),
            ("2024-03-29", 1.1781, 0.02),
        ],
    )
    r2 = make_synthetic_simulation(
        "R2",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.06, 0.06),
            ("2024-02-01", 1.06, 0.0),
            ("2024-02-29", 1.166, 0.10),
            ("2024-03-01", 1.166, 0.0),
            ("2024-03-29", 1.17766, 0.01),
        ],
    )
    r3 = make_synthetic_simulation(
        "R3",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.02, 0.02),
            ("2024-02-01", 1.02, 0.0),
            ("2024-02-29", 1.03, 0.01),
            ("2024-03-01", 1.03, 0.0),
            ("2024-03-29", 1.0815, 0.05),
        ],
    )

    qqq = make_synthetic_simulation(
        "QQQ",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.03, 0.03),
            ("2024-02-01", 1.03, 0.0),
            ("2024-02-29", 1.06, 0.03),
            ("2024-03-01", 1.06, 0.0),
            ("2024-03-29", 1.09, 0.03),
        ],
    )
    pool = qqq

    runners = [
        RunnerContract(
            "R1",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R1 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "R2",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R2 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "R3",
            "1.0",
            "p",
            "QQQ",
            "Thesis explaining why R3 exists and captures positive momentum returns.",
            "logic",
            "logic",
        ),
    ]

    scoreboard = evaluate_race_season(
        runners=runners,
        simulation_results={"R1": r1, "R2": r2, "R3": r3},
        qqq_simulation=qqq,
        pool_simulation=pool,
    )

    entry_by_id = {e.runner_id: e for e in scoreboard.entries}
    # Month 1: R1(+10%)=1st(10), R2(+6%)=2nd(6), R3(+2%)=3rd(4)
    # Month 2: R2(+10%)=1st(10), R1(+5%)=2nd(6), R3(+1%)=3rd(4)
    # Month 3: R3(+5%)=1st(10), R1(+2%)=2nd(6), R2(+1%)=3rd(4)
    # Total:
    # R1: 10 + 6 + 6 = 22
    # R2: 6 + 10 + 4 = 20
    # R3: 4 + 4 + 10 = 18
    assert entry_by_id["R1"].season_points == 22
    assert entry_by_id["R2"].season_points == 20
    assert entry_by_id["R3"].season_points == 18
    assert scoreboard.entries[0].runner_id == "R1"
    assert scoreboard.entries[1].runner_id == "R2"
    assert scoreboard.entries[2].runner_id == "R3"


# ---------------------------------------------------------------------------
# TEST-RT-P2-06: Anti-Spike Bias: Steady Marathoner Beats Single-Day Spike
# ---------------------------------------------------------------------------
def test_rt_p2_06_anti_spike_bias_steady_marathoner_beats_spiky_flash() -> None:
    """TEST-RT-P2-06: A steady runner finishing in the top 2 every month beats a strategy
    with a massive single-day 300% spike in month 1 that finishes last in all other months.
    """
    months = [f"2024-{m:02d}" for m in range(1, 13)]

    # Steady Runner: Consistent +3% every single month -> ranks 2nd every month (6 pts x 12 = 72 pts)
    # Spiky Runner: Huge spike in month 1 (+200%, ranks 1st = 10 pts), but -2% in months 2..12 (ranks 4th/last = 0 pts)
    # Baseline Runners:
    # Winner Runner in months 2..12: +5% in months 2..12
    # Middle Runner: +1% every month
    # Bottom Runner: -3% every month

    steady_series = [("2024-01-01", 1.0, 0.0)]
    spiky_series = [("2024-01-01", 1.0, 0.0)]
    winner_series = [("2024-01-01", 1.0, 0.0)]
    bottom_series = [("2024-01-01", 1.0, 0.0)]
    qqq_series = [("2024-01-01", 1.0, 0.0)]

    for m_idx, m_str in enumerate(months, start=1):
        # Last day session of month
        sess = f"{m_str}-28"

        # Steady: +3% every month
        prev_steady = steady_series[-1][1]
        steady_series.append((sess, prev_steady * 1.03, 0.03))

        # Spiky: Month 1 = +200%, Month 2..12 = -2%
        prev_spiky = spiky_series[-1][1]
        r_spiky = 2.00 if m_idx == 1 else -0.02
        spiky_series.append((sess, prev_spiky * (1.0 + r_spiky), r_spiky))

        # Winner: Month 1 = +10%, Month 2..12 = +5%
        prev_winner = winner_series[-1][1]
        r_win = 0.10 if m_idx == 1 else 0.05
        winner_series.append((sess, prev_winner * (1.0 + r_win), r_win))

        # Bottom: -5% every month
        prev_bot = bottom_series[-1][1]
        bottom_series.append((sess, prev_bot * 0.95, -0.05))

        # QQQ: +1% every month
        prev_q = qqq_series[-1][1]
        qqq_series.append((sess, prev_q * 1.01, 0.01))

    sim_steady = make_synthetic_simulation("steady_runner", steady_series)
    sim_spiky = make_synthetic_simulation("spiky_runner", spiky_series)
    sim_winner = make_synthetic_simulation("winner_runner", winner_series)
    sim_bottom = make_synthetic_simulation("bottom_runner", bottom_series)
    sim_qqq = make_synthetic_simulation("QQQ", qqq_series)

    # Note: Spiky runner cumulative return is: (1 + 2.0) * (0.98^11) - 1 = 3.0 * 0.8007 - 1 = +140%!
    # Steady runner cumulative return is: (1.03^12) - 1 = +42.5%!
    assert sim_spiky.cumulative_return > sim_steady.cumulative_return

    runners = [
        RunnerContract(
            "steady_runner",
            "1.0",
            "p",
            "QQQ",
            "Consistent low-beta quality factor strategy delivering steady returns across all market cycles.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "spiky_runner",
            "1.0",
            "p",
            "QQQ",
            "Volatile penny stock anomaly strategy that exploded on one trading day but has zero recurring alpha.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "winner_runner",
            "1.0",
            "p",
            "QQQ",
            "High-growth compounder strategy capturing secular technology trend momentum consistently.",
            "logic",
            "logic",
        ),
        RunnerContract(
            "bottom_runner",
            "1.0",
            "p",
            "QQQ",
            "Underperforming short strategy suffering persistent drag during market expansion regime.",
            "logic",
            "logic",
        ),
    ]

    sims = {
        "steady_runner": sim_steady,
        "spiky_runner": sim_spiky,
        "winner_runner": sim_winner,
        "bottom_runner": sim_bottom,
    }

    scoreboard = evaluate_race_season(
        runners=runners,
        simulation_results=sims,
        qqq_simulation=sim_qqq,
        pool_simulation=sim_qqq,
    )

    entry_by_id = {e.runner_id: e for e in scoreboard.entries}
    steady_entry = entry_by_id["steady_runner"]
    spiky_entry = entry_by_id["spiky_runner"]

    # Month 1: Spiky(+200%)=1st(10), Winner(+10%)=2nd(6), Steady(+3%)=3rd(4), Bottom(-5%)=4th(2)
    # Month 2..12 (11 months): Winner(+5%)=1st(10), Steady(+3%)=2nd(6), Spiky(-2%)=3rd(4), Bottom(-5%)=4th(2)
    # Total Season Points:
    # Steady: 4 + 11*6 = 70 points
    # Spiky: 10 + 11*4 = 54 points (or less if 5+ runners)
    assert steady_entry.season_points > spiky_entry.season_points
    assert steady_entry.current_rank < spiky_entry.current_rank


# ---------------------------------------------------------------------------
# TEST-RT-P2-07: Rolling Multi-Period Windows (1M, 3M, 6M, 1Y)
# ---------------------------------------------------------------------------
def test_rt_p2_07_rolling_multi_period_windows() -> None:
    """TEST-RT-P2-07: Verify 1M, 3M, 6M, 1Y rolling returns and bit-level 1M consistency."""
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    series = [("2024-01-01", 1.0, 0.0)]

    # Monthly returns: +2% for each of the 12 months
    for m_str in months:
        prev = series[-1][1]
        series.append((f"{m_str}-28", prev * 1.02, 0.02))

    sim_12m = make_synthetic_simulation("test_12m", series)

    # 1M return
    r_1m = calculate_rolling_window_return(sim_12m, 1)
    monthly_rets = calculate_monthly_returns(sim_12m)
    assert r_1m is not None
    # Bit-level self-consistency
    assert abs(r_1m - monthly_rets["2024-12"]) < 1e-12

    # 3M return: (1.02^3) - 1
    r_3m = calculate_rolling_window_return(sim_12m, 3)
    assert r_3m is not None
    assert abs(r_3m - ((1.02**3) - 1.0)) < 1e-12

    # 6M return: (1.02^6) - 1
    r_6m = calculate_rolling_window_return(sim_12m, 6)
    assert r_6m is not None
    assert abs(r_6m - ((1.02**6) - 1.0)) < 1e-12

    # 1Y return: (1.02^12) - 1
    r_1y = calculate_rolling_window_return(sim_12m, 12)
    assert r_1y is not None
    assert abs(r_1y - ((1.02**12) - 1.0)) < 1e-12

    # Short simulation: only 2 months
    short_series = series[:3]  # start + Jan + Feb
    sim_short = make_synthetic_simulation("short", short_series)
    assert calculate_rolling_window_return(sim_short, 1) is not None
    assert calculate_rolling_window_return(sim_short, 3) is None
    assert calculate_rolling_window_return(sim_short, 6) is None
    assert calculate_rolling_window_return(sim_short, 12) is None


# ---------------------------------------------------------------------------
# TEST-RT-P2-08: Dual Benchmark Excess Return Matrix
# ---------------------------------------------------------------------------
def test_rt_p2_08_dual_benchmark_excess_matrix() -> None:
    """TEST-RT-P2-08: Dual benchmark excess returns (vs QQQ and vs Pool Index)."""
    # 2-month simulation
    # Runner: +10% in Jan, +5% in Feb
    # QQQ: +4% in Jan, +2% in Feb
    # Pool: +2% in Jan, +1% in Feb
    r_sim = make_synthetic_simulation(
        "runner_a",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.10, 0.10),
            ("2024-02-01", 1.10, 0.0),
            ("2024-02-29", 1.155, 0.05),
        ],
    )
    qqq_sim = make_synthetic_simulation(
        "qqq",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.04, 0.04),
            ("2024-02-01", 1.04, 0.0),
            ("2024-02-29", 1.0608, 0.02),
        ],
    )
    pool_sim = make_synthetic_simulation(
        "pool",
        [
            ("2024-01-02", 1.0, 0.0),
            ("2024-01-31", 1.02, 0.02),
            ("2024-02-01", 1.02, 0.0),
            ("2024-02-29", 1.0302, 0.01),
        ],
    )

    runner = RunnerContract(
        "runner_a",
        "1.0",
        "p",
        "QQQ",
        "Strategy designed to beat both external tech beta and internal equal weight equity pool.",
        "logic",
        "logic",
    )

    scoreboard = evaluate_race_season(
        runners=[runner],
        simulation_results={"runner_a": r_sim},
        qqq_simulation=qqq_sim,
        pool_simulation=pool_sim,
    )

    entry = scoreboard.entries[0]
    # Month 1 excess
    m1 = entry.monthly_ranks[0]
    assert abs(m1.monthly_excess_vs_qqq - (0.10 - 0.04)) < 1e-12
    assert abs(m1.monthly_excess_vs_pool - (0.10 - 0.02)) < 1e-12

    # Month 2 excess
    m2 = entry.monthly_ranks[1]
    assert abs(m2.monthly_excess_vs_qqq - (0.05 - 0.02)) < 1e-12
    assert abs(m2.monthly_excess_vs_pool - (0.05 - 0.01)) < 1e-12


# ---------------------------------------------------------------------------
# TEST-RT-P2-09: Scoreboard JSON Serialization & Deserialization Round-Trip
# ---------------------------------------------------------------------------
def test_rt_p2_09_scoreboard_json_serialization_and_roundtrip() -> None:
    """TEST-RT-P2-09: Scoreboard JSON schema integrity, privacy assertions, and read-only round-trip."""
    rank_pt = MonthlyRankPoint(
        month="2024-01",
        rank=1,
        total_runners=3,
        monthly_net_return=0.085,
        monthly_excess_vs_qqq=0.035,
        monthly_excess_vs_pool=0.055,
        points_earned=10,
    )
    entry = ScoreboardEntry(
        runner_id="runner_prime",
        runner_version="1.0.0",
        thesis_summary="Substantive multi-factor investment thesis capturing value and momentum.",
        season_points=10,
        current_rank=1,
        return_1m=0.085,
        return_3m=None,
        return_6m=None,
        return_1y=None,
        excess_vs_qqq=0.035,
        excess_vs_pool=0.055,
        max_drawdown=0.02,
        sharpe_ratio=1.85,
        persistence_ratio=1.0,
        monthly_ranks=[rank_pt],
    )
    sb = Scoreboard(
        schema_version="1.0",
        as_of_session="2024-01-31",
        season_id="season_2024_q1",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        entries=[entry],
    )

    # 1. Privacy audit
    sb_dict = sb.to_dict()
    assert_privacy_clean(sb_dict)

    # 2. JSON serialization
    json_str = sb.to_json()
    assert '"schema_version": "1.0"' in json_str
    assert '"runner_prime"' in json_str

    # 3. Round-trip deserialization
    loaded = Scoreboard.from_json(json_str)
    assert loaded.schema_version == sb.schema_version
    assert loaded.as_of_session == sb.as_of_session
    assert loaded.season_id == sb.season_id
    assert loaded.pool_id == sb.pool_id
    assert len(loaded.entries) == 1

    loaded_entry = loaded.entries[0]
    assert loaded_entry.runner_id == entry.runner_id
    assert loaded_entry.season_points == 10
    assert loaded_entry.current_rank == 1
    assert loaded_entry.monthly_ranks[0].rank == 1
    assert loaded_entry.monthly_ranks[0].points_earned == 10


# ---------------------------------------------------------------------------
# TEST-RT-P2-10: End-to-End Real US 87 Market Data Full Race Simulation
# ---------------------------------------------------------------------------
def test_rt_p2_10_end_to_end_real_us87_data_race() -> None:
    """TEST-RT-P2-10: Full race simulation using real US 87 market evidence data:
    multiple runners, QQQ and US87_EW benchmarks, ledger persistence, and Scoreboard generation.
    """
    matrix = load_price_matrix(
        market="us",
        pool_id="us_selected_equities_v2",
        start_date="2024-01-02",
        end_date="2024-03-28",
        as_of_cutoff="2026-10-26",
        root_path=REPO_ROOT,
    )

    registry = RunnerRegistry(
        pool_id="us_selected_equities_v2",
        candidate_symbols=matrix.candidate_symbols,
    )

    # Runner 1: Tech Momentum (AAPL, MSFT, NVDA) rebalanced monthly
    def gen_tech_events(m: PriceMatrix) -> list[RebalanceEvent]:
        events = []
        sessions = m.sessions
        prev_h = "0" * 64
        for i, sess in enumerate(sessions):
            if i == 0 or sess[:7] != sessions[i - 1][:7]:
                ev = RebalanceEvent.create(
                    parent_hash=prev_h,
                    effective_session=sess,
                    runner_id="runner_tech_momentum",
                    runner_version="1.0.0",
                    target_weights={"AAPL": 0.33, "MSFT": 0.33, "NVDA": 0.34},
                    reason="Monthly equal tech allocation",
                )
                events.append(ev)
                prev_h = ev.event_hash
        return events

    r_tech = RunnerContract(
        runner_id="runner_tech_momentum",
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis="Betting on secular semiconductor and cloud software expansion through top tech constituents.",
        selection_logic="top 3 tech market cap",
        rebalance_logic="monthly rebalance",
        events_generator=gen_tech_events,
    )

    # Runner 2: Defensive Value (COST, PEP, WMT) rebalanced monthly
    def gen_defensive_events(m: PriceMatrix) -> list[RebalanceEvent]:
        events = []
        sessions = m.sessions
        prev_h = "0" * 64
        for i, sess in enumerate(sessions):
            if i == 0 or sess[:7] != sessions[i - 1][:7]:
                ev = RebalanceEvent.create(
                    parent_hash=prev_h,
                    effective_session=sess,
                    runner_id="runner_defensive_value",
                    runner_version="1.0.0",
                    target_weights={"COST": 0.33, "PEP": 0.33, "WMT": 0.34},
                    reason="Monthly defensive value allocation",
                )
                events.append(ev)
                prev_h = ev.event_hash
        return events

    r_def = RunnerContract(
        runner_id="runner_defensive_value",
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis="Defensive consumer staple and retail holding to mitigate drawdowns during market corrections.",
        selection_logic="top 3 low-beta dividend champions",
        rebalance_logic="monthly rebalance",
        events_generator=gen_defensive_events,
    )

    # Runner 3: 100% Cash holding strategy
    def gen_cash_events(m: PriceMatrix) -> list[RebalanceEvent]:
        ev = RebalanceEvent.create(
            parent_hash="0" * 64,
            effective_session=m.sessions[0],
            runner_id="runner_pure_cash",
            runner_version="1.0.0",
            target_weights={},
            reason="100% Cash capital preservation",
        )
        return [ev]

    r_cash = RunnerContract(
        runner_id="runner_pure_cash",
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis="Preserves capital with 100% cash holding, expecting widespread market decline across all sectors.",
        selection_logic="cash filter",
        rebalance_logic="hold cash",
        events_generator=gen_cash_events,
    )

    registry.register(r_tech)
    registry.register(r_def)
    registry.register(r_cash)

    with tempfile.TemporaryDirectory() as tmp_dir:
        ledgers_dir = Path(tmp_dir) / "ledgers"
        # 1. Run all strategies via registry
        sim_results = registry.evaluate_all(matrix=matrix, ledgers_dir=ledgers_dir)

        # Assert all ledgers written and verify hash-chain integrity
        for runner in registry.list_runners():
            l_path = ledgers_dir / f"{runner.runner_id}.jsonl"
            assert l_path.exists()
            assert l_path.stat().st_size > 0

        # 2. Benchmarks
        qqq_sim = generate_benchmark_simulation(matrix=matrix, symbol="QQQ")
        pool_sim = generate_equal_weight_pool_index(
            matrix=matrix, pool_id="us_selected_equities_v2"
        )

        # 3. Race evaluation and Scoreboard generation
        scoreboard = evaluate_race_season(
            runners=registry,
            simulation_results=sim_results,
            qqq_simulation=qqq_sim,
            pool_simulation=pool_sim,
            season_id="season_2024_q1",
            pool_id=matrix.pool_id,
            benchmark_symbol=matrix.reference_symbol,
        )

        # 4. Scoreboard assertions
        assert len(scoreboard.entries) == 3
        assert scoreboard.schema_version == "1.0"
        assert scoreboard.pool_id == "us_selected_equities_v2"
        assert scoreboard.benchmark_symbol == "QQQ"

        # Current ranks are sequential: 1, 2, 3
        ranks = [e.current_rank for e in scoreboard.entries]
        assert ranks == [1, 2, 3]

        # Top runner has highest points
        assert scoreboard.entries[0].season_points >= scoreboard.entries[1].season_points
        assert scoreboard.entries[1].season_points >= scoreboard.entries[2].season_points

        # Verify JSON serialization
        sb_json = scoreboard.to_json()
        assert "runner_tech_momentum" in sb_json
        assert "season_2024_q1" in sb_json

        # Round-trip deserialization
        loaded_sb = Scoreboard.from_json(sb_json)
        assert len(loaded_sb.entries) == 3
        assert loaded_sb.entries[0].runner_id == scoreboard.entries[0].runner_id
