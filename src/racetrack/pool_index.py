"""Racetrack pool index benchmark generator.

Generates monthly equal-weight rebalanced pool index (e.g. US 87 EW)
with intra-month natural drift and zero intra-month turnover.
"""

from __future__ import annotations

import numpy as np

from src.racetrack.contracts import (
    CalendarSessionError,
    EngineConfig,
    RebalanceEvent,
    SimulationResult,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.matrix import PriceMatrix


def generate_equal_weight_pool_index(
    matrix: PriceMatrix,
    pool_id: str,
    config: EngineConfig = EngineConfig(),
) -> SimulationResult:
    """Generate equal-weight benchmark index for the declared candidate universe pool.

    Constituent Eligibility & Drift Protection Rules:
        - The pool membership is fixed to the declared candidate universe (N = len(matrix.candidate_symbols)).
        - Each declared constituent receives an exact fixed target allocation of 1 / N (e.g. 1/87).
        - If a constituent is unlisted (pre-IPO) or halted (NaN price) on rebalance date,
          its 1 / N slot is held in cash, NOT silently redistributed to inflate other stocks.
        - Rebalances occur on the first trading session of each calendar month.
        - Intra-month sessions undergo natural price drift with zero rebalance turnover.
        - Evaluated via simulate_portfolio with friction applied on rebalance days.

    Args:
        matrix: Aligned PriceMatrix containing candidates and reference.
        pool_id: Pool identifier (e.g. 'us_selected_equities_v2').
        config: EngineConfig for friction and KPI statistics.

    Returns:
        SimulationResult representing the internal benchmark line.
    """
    events = generate_pool_index_events(matrix, pool_id)
    return simulate_portfolio(matrix=matrix, ledger_events=events, config=config)


def generate_pool_index_events(
    matrix: PriceMatrix,
    pool_id: str,
    runner_id: str | None = None,
    runner_version: str = "1.0.0",
) -> list[RebalanceEvent]:
    """One event derivation for the benchmark and its separately named racer.

    Initialize at the replay's first session, then rebalance at each observed
    month boundary. A partial first month is initialization, not a settled month.
    Missing slots become cash at rebalance; interim valuation stays in the engine.
    """
    if matrix.pool_id != pool_id:
        raise ValueError("Pool index identity does not match the price matrix")
    sessions = matrix.sessions
    if not sessions:
        raise CalendarSessionError("Matrix contains zero sessions")

    candidates = matrix.candidate_symbols
    num_declared = len(candidates)
    if num_declared == 0:
        raise ValueError(f"Matrix contains zero candidate symbols for pool '{pool_id}'")

    weight_per_constituent = 1.0 / float(num_declared)
    events: list[RebalanceEvent] = []
    prev_hash = "0" * 64

    for i, sess in enumerate(sessions):
        # Identify first trading session of each calendar month
        is_first_session_of_month = (i == 0) or (sess[:7] != sessions[i - 1][:7])
        if not is_first_session_of_month:
            continue

        # Audit active constituent eligibility: only allocate if price is valid on session
        active_symbols = [sym for sym in candidates if not np.isnan(matrix.get_price(sess, sym))]
        unlisted_count = num_declared - len(active_symbols)

        # Fixed 1 / N per constituent, unlisted/missing constituent weight remains in cash
        target_weights = {sym: weight_per_constituent for sym in active_symbols}
        unallocated_cash = unlisted_count * weight_per_constituent

        ev = RebalanceEvent.create(
            parent_hash=prev_hash,
            effective_session=sess,
            runner_id=runner_id or f"benchmark_{pool_id}_ew",
            runner_version=runner_version,
            target_weights=target_weights,
            reason=(
                f"Monthly equal-weight rebalance for {sess[:7]}: "
                f"{len(active_symbols)}/{num_declared} active constituents (weight={weight_per_constituent:.6f}), "
                f"{unlisted_count} unlisted/halted slots held in cash ({unallocated_cash:.6f})"
            ),
        )
        events.append(ev)
        prev_hash = ev.event_hash

    return events
