"""Racetrack race scoring, monthly cross-sectional ranking, and Scoreboard projection.

Implements versioned PointsRuleV1, monthly compounding returns, rolling window returns
(1M, 3M, 6M, 1Y), dual benchmark excess return computation, and persistence metrics.
Enforces strict session alignment across all runners and benchmarks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import math
import re

from src.racetrack.contracts import (
    CalendarSessionError,
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


class ReturnPointsV2:
    """A month's net return expressed in percentage points, never rank awards."""

    rule_id = "monthly_net_return_percentage_points_v2"

    @staticmethod
    def get_points(monthly_net_return: float) -> float:
        if not math.isfinite(monthly_net_return):
            raise ValueError("Return points require a finite monthly net return")
        return monthly_net_return * 100.0


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


def parse_season_month(season_id: str, default_month: str = "") -> str:
    """Extract YYYY-MM target month string from season_id."""
    match = re.search(r"(\d{4})[-_](\d{2})", season_id)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return default_month


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
        1. Strict session alignment: verify every runner and benchmark has identical trading session sequence.
        2. Identify common calendar months across all active runners and benchmarks.
        3. Monthly cross-sectional ranking: rank runners descending by monthly net return.
        4. Distribute points per month using PointsRuleV1.
        5. Decouple target season_points (for month in season_id) and cumulative_points (all months).
        6. Calculate dual excess returns (vs QQQ and vs Pool Index) and persistence ratio.
        7. Assemble Scoreboard with timeseries (dates, benchmarks, top_runners_nav) and status.

    Returns:
        Scoreboard instance ready for serialization.
    """
    if isinstance(runners, RunnerRegistry):
        runner_map = {r.runner_id: r for r in runners.list_runners()}
    elif isinstance(runners, Mapping):
        runner_map = dict(runners)
    else:
        runner_map = {r.runner_id: r for r in runners}

    # 1. Strict trading session alignment verification
    base_sessions = [p.session for p in pool_simulation.nav_history]
    macro_sessions = [p.session for p in qqq_simulation.nav_history]
    if macro_sessions != base_sessions:
        raise CalendarSessionError(
            f"Macro benchmark session sequence does not strictly match pool index sessions: "
            f"expected {len(base_sessions)} sessions, got {len(macro_sessions)}"
        )

    for r_id, sim in simulation_results.items():
        runner_sessions = [p.session for p in sim.nav_history]
        if runner_sessions != base_sessions:
            raise CalendarSessionError(
                f"Runner '{r_id}' session sequence does not strictly match official pool calendar sessions: "
                f"expected {len(base_sessions)} sessions, got {len(runner_sessions)}"
            )

    # 2. Compute monthly returns for all runners and benchmarks
    runner_monthly = {
        r_id: calculate_monthly_returns(sim) for r_id, sim in simulation_results.items()
    }
    qqq_monthly = calculate_monthly_returns(qqq_simulation)
    pool_monthly = calculate_monthly_returns(pool_simulation)

    # 3. Identify common natural calendar months
    month_sets = [set(m.keys()) for m in runner_monthly.values()]
    month_sets.append(set(qqq_monthly.keys()))
    month_sets.append(set(pool_monthly.keys()))
    if month_sets:
        common_months = sorted(list(set.intersection(*month_sets)))
    else:
        common_months = []

    # Target season month from season_id (or fallback to latest common month)
    target_season_month = parse_season_month(
        season_id,
        default_month=common_months[-1] if common_months else "",
    )

    # 4. Monthly cross-sectional ranking and points attribution
    monthly_ranks_by_runner: dict[str, list[MonthlyRankPoint]] = {
        r_id: [] for r_id in simulation_results
    }

    for m in common_months:
        ret_pairs = [(r_id, runner_monthly[r_id].get(m, 0.0)) for r_id in simulation_results]
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

    # 5. Multi-period rolling returns for benchmarks
    qqq_1y = calculate_rolling_window_return(qqq_simulation, 12)
    pool_1y = calculate_rolling_window_return(pool_simulation, 12)

    # 6. Build raw entries
    raw_entries: list[tuple[ScoreboardEntry, float]] = []

    for r_id, sim in simulation_results.items():
        runner = runner_map.get(r_id)
        m_ranks = monthly_ranks_by_runner.get(r_id, [])

        # Decouple cumulative all-time points vs target season month points
        cumulative_pts = sum(p.points_earned for p in m_ranks)
        season_pts = sum(p.points_earned for p in m_ranks if p.month == target_season_month)

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
            cumulative_points=cumulative_pts,
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

    # 7. Sort entries: cumulative_points descending, season_points descending, then 1Y return descending
    raw_entries.sort(
        key=lambda item: (-item[0].cumulative_points, -item[0].season_points, -item[1])
    )

    # 8. Assign final ranks
    ranked_entries: list[ScoreboardEntry] = []
    for rank_idx, (entry, _) in enumerate(raw_entries, start=1):
        ranked_entries.append(
            ScoreboardEntry(
                runner_id=entry.runner_id,
                runner_version=entry.runner_version,
                thesis_summary=entry.thesis_summary,
                season_points=entry.season_points,
                cumulative_points=entry.cumulative_points,
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

    # 9. Extract timeseries for frontend zero-compute rendering
    dates = [p.session for p in pool_simulation.nav_history]
    benchmarks = {
        "pool_index": [float(p.nav) for p in pool_simulation.nav_history],
        "macro": [float(p.nav) for p in qqq_simulation.nav_history],
    }
    top_runners_nav = {
        e.runner_id: [float(p.nav) for p in simulation_results[e.runner_id].nav_history]
        for e in ranked_entries[:10]
        if e.runner_id in simulation_results
    }
    status = "operational_race" if ranked_entries else "diagnostic_baseline_only"
    as_of_session = qqq_simulation.end_session if qqq_simulation else ""

    return Scoreboard(
        schema_version=schema_version,
        as_of_session=as_of_session,
        season_id=season_id,
        pool_id=pool_id,
        benchmark_symbol=benchmark_symbol,
        entries=ranked_entries,
        status=status,
        dates=dates,
        benchmarks=benchmarks,
        top_runners_nav=top_runners_nav,
    )


def evaluate_first_season(
    runners: Mapping[str, RunnerContract],
    simulation_results: Mapping[str, SimulationResult],
    qqq_simulation: SimulationResult,
    pool_simulation: SimulationResult,
    season_id: str,
    pool_id: str,
    benchmark_symbol: str,
    calendar_name: str,
    pool_runner_id: str,
) -> Scoreboard:
    """Schema 2: full-duration window ranks and provisional monthly return points.

    Reuse the existing scorer's session validation, monthly returns and risk
    evidence. No strategy is evaluated here. Old PointsRuleV1 output is unchanged.
    Complete calendar coverage is evidence for a later review, not settlement.
    """
    import exchange_calendars as xcals
    import pandas as pd

    legacy = evaluate_race_season(runners, simulation_results, qqq_simulation,
        pool_simulation, season_id, pool_id, benchmark_symbol)
    if not legacy.dates or pool_runner_id not in runners:
        raise ValueError("First season requires its registered pool racer and dated evidence")
    calendar = xcals.get_calendar(calendar_name)
    dates = legacy.dates
    if parse_season_month(season_id) != dates[-1][:7]:
        raise ValueError("First season must identify the current natural calendar month")
    if dates != [str(d.date()) for d in calendar.sessions_in_range(dates[0], dates[-1])]:
        raise CalendarSessionError("First-season evidence has missing or unofficial sessions")

    def ranks(values: Mapping[str, float]) -> dict[str, int]:
        ordered = sorted(values, key=lambda key: (-values[key], key))
        result = {}
        previous, rank = None, 0
        for index, key in enumerate(ordered, 1):
            if previous is None or values[key] != previous:
                rank = index
            result[key] = rank
            previous = values[key]
        return result

    month_windows = []
    for month in sorted({d[:7] for d in dates}):
        first = pd.Timestamp(f"{month}-01")
        expected = [str(d.date()) for d in calendar.sessions_in_range(first, first + pd.offsets.MonthEnd())]
        observed = [d for d in dates if d.startswith(month)]
        month_windows.append({"month": month, "first_session": expected[0], "last_session": expected[-1],
            "expected_sessions": len(expected), "observed_sessions": len(observed),
            "complete_window": expected == observed, "settlement_status": "not_reviewed"})

    windows, window_returns = {}, {}
    for months in (1, 3, 6, 12):
        target = pd.Timestamp(dates[-1]) - pd.DateOffset(months=months)
        anchor = str(calendar.date_to_session(target, direction="previous").date())
        start_index = dates.index(anchor) if anchor in dates else None
        if start_index is not None and any(sim.nav_history[start_index].nav <= 0 for sim in simulation_results.values()):
            raise ValueError("Non-positive window anchor NAV")
        values = {key: float(sim.nav_history[-1].nav / sim.nav_history[start_index].nav - 1)
            for key, sim in simulation_results.items()} if start_index is not None else {}
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("Window return must be finite")
        ranked = ranks(values)
        ordered = sorted(values, key=lambda key: (-values[key], key))
        windows[str(months)] = {"anchor_session": anchor if start_index is not None else None,
            "end_session": dates[-1], "ranks": {key: ranked.get(key) for key in runners},
            "top_runner_ids": ordered[:10]}
        window_returns[months] = values

    monthly_values = {month["month"]: {e.runner_id: next(p.monthly_net_return for p in e.monthly_ranks
        if p.month == month["month"]) for e in legacy.entries} for month in month_windows}
    monthly_rank = {month: ranks(values) for month, values in monthly_values.items()}
    entries = []
    for entry in legacy.entries:
        key = entry.runner_id
        history = [replace(p, rank=monthly_rank[p.month][key],
            points_earned=ReturnPointsV2.get_points(p.monthly_net_return)) for p in entry.monthly_ranks]
        returns = {m: window_returns[m].get(key) for m in (1, 3, 6, 12)}
        # The reference excess period follows the same full-history eligibility.
        anchor = windows["12"]["anchor_session"]
        ref_index = dates.index(anchor) if anchor else None
        sim = simulation_results[key]
        def excess(reference: SimulationResult) -> float:
            if ref_index is None:
                return sim.cumulative_return - reference.cumulative_return
            return returns[12] - (reference.nav_history[-1].nav / reference.nav_history[ref_index].nav - 1)
        entries.append(replace(entry, monthly_ranks=history,
            season_points=sum(p.points_earned for p in history if p.month == parse_season_month(season_id)),
            cumulative_points=sum(p.points_earned for p in history), return_1m=returns[1],
            return_3m=returns[3], return_6m=returns[6], return_1y=returns[12],
            excess_vs_qqq=excess(qqq_simulation), excess_vs_pool=excess(pool_simulation),
            persistence_ratio=sum(p.rank <= math.ceil(p.total_runners / 2) for p in history) / len(history)))
    season_ranks = ranks({e.runner_id: e.season_points for e in entries})
    entries = [replace(e, current_rank=season_ranks[e.runner_id]) for e in sorted(entries,
        key=lambda e: (-e.season_points, e.runner_id))]
    retained_ids = {e.runner_id for e in entries[:10]}
    retained_ids.update(key for window in windows.values() for key in window["top_runner_ids"])
    return replace(legacy, schema_version="2.0", entries=entries,
        top_runners_nav={key: [p.nav for p in simulation_results[key].nav_history] for key in sorted(retained_ids)},
        first_season={"contract_version": "first_season_v2", "points_rule": ReturnPointsV2.rule_id,
            "rank_policy": "window_net_return_competition_rank_v1", "season_state": "provisional",
            "month_windows": month_windows, "windows": windows, "pool_runner_id": pool_runner_id,
            "roles": {key: "internal_benchmark_racer" if key == pool_runner_id else "strategy_racer" for key in runners}})
