"""Racetrack race scoring, monthly cross-sectional ranking, and Scoreboard projection.

Implements versioned PointsRuleV1, monthly compounding returns, rolling window returns
(1M, 3M, 6M, 1Y), dual benchmark excess return computation, and persistence metrics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from src.racetrack.contracts import (
    EngineConfig,
    MonthlyRankPoint,
    NAVPoint,
    PriceMatrix,
    RebalanceEvent,
    Scoreboard,
    ScoreboardEntry,
    SimulationResult,
    UnauthorizedAssetError,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.runner import RunnerContract, RunnerRegistry


class PointsRuleV1:
    """Versioned season points allocation rule.

    Rank 1: 10 points
    Rank 2: 6 points
    Rank 3: 4 points
    Rank 4: 2 points
    Rank 5: 1 point
    Rank > 5: 0 points
    """

    POINTS_TABLE: dict[int, int] = {
        1: 10,
        2: 6,
        3: 4,
        4: 2,
        5: 1,
    }

    @classmethod
    def get_points(cls, rank: int) -> int:
        """Return points awarded for a given integer rank."""
        return cls.POINTS_TABLE.get(rank, 0)


def calculate_monthly_returns(simulation: SimulationResult) -> dict[str, float]:
    """Calculate compound net return for each calendar month in the simulation.

    Formula:
        R_m = NAV(t_m,end) / NAV(t_m-1,end) - 1.0 = prod_{t in m}(1 + r_net,t) - 1.0
    Where NAV(t_m-1,end) = 1.0 for the first month.

    Returns:
        Dictionary mapping month string ("YYYY-MM") -> compound net return float.
    """
    monthly_returns: dict[str, float] = {}
    if not simulation.nav_history:
        return monthly_returns

    # Group daily NAV points by month "YYYY-MM"
    month_groups: dict[str, list[NAVPoint]] = {}
    for pt in simulation.nav_history:
        month_key = pt.session[:7]
        if month_key not in month_groups:
            month_groups[month_key] = []
        month_groups[month_key].append(pt)

    sorted_months = sorted(month_groups.keys())
    prev_nav_end = 1.0
    for m in sorted_months:
        pts = month_groups[m]
        curr_nav_end = pts[-1].nav
        if prev_nav_end > 0:
            r_m = (curr_nav_end / prev_nav_end) - 1.0
        else:
            r_m = 0.0
        monthly_returns[m] = float(r_m)
        prev_nav_end = curr_nav_end

    return monthly_returns


def calculate_rolling_window_return(
    simulation: SimulationResult,
    months: int,
) -> float | None:
    """Calculate rolling compound net return over the most recent `months` calendar months.

    Args:
        simulation: Strategy SimulationResult.
        months: Number of calendar months in rolling window (e.g. 1, 3, 6, 12).

    Returns:
        Compound net return over the window, or None if simulation contains fewer than `months` months.
    """
    if months <= 0 or not simulation.nav_history:
        return None

    # Group points by month
    month_groups: dict[str, list[NAVPoint]] = {}
    for pt in simulation.nav_history:
        month_key = pt.session[:7]
        if month_key not in month_groups:
            month_groups[month_key] = []
        month_groups[month_key].append(pt)

    sorted_months = sorted(month_groups.keys())
    if len(sorted_months) < months:
        return None

    # Target window is the last `months` calendar months
    end_nav = month_groups[sorted_months[-1]][-1].nav

    if len(sorted_months) == months:
        start_nav = 1.0
    else:
        # NAV at close of the month immediately preceding the window
        prev_month_idx = len(sorted_months) - months - 1
        start_nav = month_groups[sorted_months[prev_month_idx]][-1].nav

    if start_nav <= 0:
        return 0.0

    return float((end_nav / start_nav) - 1.0)


def generate_benchmark_simulation(
    matrix: PriceMatrix,
    symbol: str = "QQQ",
    config: EngineConfig = EngineConfig(),
) -> SimulationResult:
    """Generate a 100% allocation buy-and-hold SimulationResult for a benchmark symbol."""
    if symbol not in matrix.symbols:
        raise UnauthorizedAssetError(f"Benchmark symbol '{symbol}' is not in PriceMatrix symbols")

    t_0 = matrix.sessions[0]
    ev = RebalanceEvent.create(
        parent_hash="0" * 64,
        effective_session=t_0,
        runner_id=f"benchmark_{symbol.lower()}",
        runner_version="1.0.0",
        target_weights={symbol: 1.0},
        reason=f"100% allocation to benchmark reference {symbol}",
    )
    return simulate_portfolio(matrix=matrix, ledger_events=[ev], config=config)


def evaluate_race_season(
    runners: Mapping[str, RunnerContract] | Sequence[RunnerContract] | RunnerRegistry,
    simulation_results: Mapping[str, SimulationResult],
    qqq_simulation: SimulationResult,
    pool_simulation: SimulationResult,
    season_id: str = "season_default",
    pool_id: str = "us_selected_equities_v2",
    benchmark_symbol: str = "QQQ",
    schema_version: str = "1.0",
) -> Scoreboard:
    """Evaluate full race season across all runners, allocating points and constructing Scoreboard.

    Algorithm:
        1. Identify common calendar months across all active runners and benchmarks.
        2. Monthly cross-sectional ranking: rank runners descending by monthly net return.
        3. Distribute points per month using PointsRuleV1 and accumulate total season points.
        4. Calculate dual excess returns (vs QQQ and vs Pool Index).
        5. Calculate persistence ratio (fraction of months in top 50%).
        6. Assemble Scoreboard sorted by season_points descending (with 1Y return tie-breaker).

    Returns:
        Scoreboard instance ready for serialization.
    """
    if isinstance(runners, RunnerRegistry):
        runner_map = {r.runner_id: r for r in runners.list_runners()}
    elif isinstance(runners, Mapping):
        runner_map = dict(runners)
    else:
        runner_map = {r.runner_id: r for r in runners}

    # 1. Compute monthly returns for all runners and benchmarks
    runner_monthly = {
        r_id: calculate_monthly_returns(sim) for r_id, sim in simulation_results.items()
    }
    qqq_monthly = calculate_monthly_returns(qqq_simulation)
    pool_monthly = calculate_monthly_returns(pool_simulation)

    # 2. Identify common natural calendar months
    month_sets = [set(m.keys()) for m in runner_monthly.values()]
    month_sets.append(set(qqq_monthly.keys()))
    month_sets.append(set(pool_monthly.keys()))
    if month_sets:
        common_months = sorted(list(set.intersection(*month_sets)))
    else:
        common_months = []

    # 3. Monthly cross-sectional ranking and points attribution
    monthly_ranks_by_runner: dict[str, list[MonthlyRankPoint]] = {
        r_id: [] for r_id in simulation_results
    }

    for m in common_months:
        # Collect returns for each runner in month m
        ret_pairs = [(r_id, runner_monthly[r_id].get(m, 0.0)) for r_id in simulation_results]
        # Descending sort by return
        ret_pairs.sort(key=lambda x: x[1], reverse=True)

        total_runners = len(ret_pairs)
        for rank_idx, (r_id, r_net) in enumerate(ret_pairs, start=1):
            rank = rank_idx
            pts = PointsRuleV1.get_points(rank)
            excess_qqq = r_net - qqq_monthly.get(m, 0.0)
            excess_pool = r_net - pool_monthly.get(m, 0.0)

            pt = MonthlyRankPoint(
                month=m,
                rank=rank,
                total_runners=total_runners,
                monthly_net_return=float(r_net),
                monthly_excess_vs_qqq=float(excess_qqq),
                monthly_excess_vs_pool=float(excess_pool),
                points_earned=pts,
            )
            monthly_ranks_by_runner[r_id].append(pt)

    # 4. Multi-period rolling returns for benchmarks
    qqq_1y = calculate_rolling_window_return(qqq_simulation, 12)
    pool_1y = calculate_rolling_window_return(pool_simulation, 12)

    # 5. Build raw entries
    raw_entries: list[tuple[ScoreboardEntry, float]] = []

    for r_id, sim in simulation_results.items():
        runner = runner_map.get(r_id)
        m_ranks = monthly_ranks_by_runner.get(r_id, [])
        season_pts = sum(p.points_earned for p in m_ranks)

        # Persistence ratio: fraction of months ranked in top 50%
        if m_ranks:
            top_half_count = sum(1 for p in m_ranks if p.rank <= math.ceil(p.total_runners / 2.0))
            persistence = float(top_half_count / len(m_ranks))
        else:
            persistence = 0.0

        ret_1m = calculate_rolling_window_return(sim, 1)
        ret_3m = calculate_rolling_window_return(sim, 3)
        ret_6m = calculate_rolling_window_return(sim, 6)
        ret_1y = calculate_rolling_window_return(sim, 12)

        # Excess returns vs dual benchmarks
        if ret_1y is not None and qqq_1y is not None:
            excess_qqq = ret_1y - qqq_1y
        else:
            excess_qqq = sim.cumulative_return - qqq_simulation.cumulative_return

        if ret_1y is not None and pool_1y is not None:
            excess_pool = ret_1y - pool_1y
        else:
            excess_pool = sim.cumulative_return - pool_simulation.cumulative_return

        thesis_text = runner.thesis if runner else ""
        thesis_summary = thesis_text[:100] + "..." if len(thesis_text) > 100 else thesis_text
        version_str = runner.runner_version if runner else sim.runner_version

        entry = ScoreboardEntry(
            runner_id=r_id,
            runner_version=version_str,
            thesis_summary=thesis_summary,
            season_points=season_pts,
            current_rank=1,  # will be assigned after sort
            return_1m=ret_1m,
            return_3m=ret_3m,
            return_6m=ret_6m,
            return_1y=ret_1y,
            excess_vs_qqq=excess_qqq,
            excess_vs_pool=excess_pool,
            max_drawdown=sim.max_drawdown,
            sharpe_ratio=sim.annualized_sharpe,
            persistence_ratio=persistence,
            monthly_ranks=m_ranks,
        )
        tie_breaker_return = ret_1y if ret_1y is not None else sim.cumulative_return
        raw_entries.append((entry, tie_breaker_return))

    # 6. Sort entries: season_points descending, then 1Y return descending
    raw_entries.sort(key=lambda item: (-item[0].season_points, -item[1]))

    # 7. Assign final ranks
    ranked_entries: list[ScoreboardEntry] = []
    for rank_idx, (entry, _) in enumerate(raw_entries, start=1):
        ranked_entries.append(
            ScoreboardEntry(
                runner_id=entry.runner_id,
                runner_version=entry.runner_version,
                thesis_summary=entry.thesis_summary,
                season_points=entry.season_points,
                current_rank=rank_idx,
                return_1m=entry.return_1m,
                return_3m=entry.return_3m,
                return_6m=entry.return_6m,
                return_1y=entry.return_1y,
                excess_vs_qqq=entry.excess_vs_qqq,
                excess_vs_pool=entry.excess_vs_pool,
                max_drawdown=entry.max_drawdown,
                sharpe_ratio=entry.sharpe_ratio,
                persistence_ratio=entry.persistence_ratio,
                monthly_ranks=entry.monthly_ranks,
            )
        )

    as_of_session = qqq_simulation.end_session if qqq_simulation else ""
    return Scoreboard(
        schema_version=schema_version,
        as_of_session=as_of_session,
        season_id=season_id,
        pool_id=pool_id,
        benchmark_symbol=benchmark_symbol,
        entries=ranked_entries,
    )
