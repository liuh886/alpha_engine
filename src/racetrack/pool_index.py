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
    strict_full_pool: bool = False,
) -> SimulationResult:
    """Generate equal-weight benchmark index for the candidate universe pool.

    Rules:
        - Automatically identifies the first trading session of each calendar month.
        - Emits an equal-weight rebalance event (1 / N for each active pool constituent).
        - Intra-month sessions undergo natural drift with zero turnover.
        - Evaluated via simulate_portfolio with friction applied on rebalance days.

    Args:
        matrix: Aligned PriceMatrix containing candidates and reference.
        pool_id: Pool identifier (e.g. 'us_selected_equities_v2').
        config: EngineConfig for friction and KPI statistics.
        strict_full_pool: If True, assigns 1 / total_candidates to every candidate
            regardless of whether its price on that session is NaN. If False, assigns
            equal weight among all candidate members with valid (non-NaN) prices on that session.

    Returns:
        SimulationResult representing the internal benchmark line.
    """
    sessions = matrix.sessions
    if not sessions:
        raise CalendarSessionError("Matrix contains zero sessions")

    candidates = matrix.candidate_symbols
    if not candidates:
        raise ValueError(f"Matrix contains zero candidate symbols for pool '{pool_id}'")

    events: list[RebalanceEvent] = []
    prev_hash = "0" * 64

    for i, sess in enumerate(sessions):
        # Identify first trading session of each calendar month
        is_first_session_of_month = (i == 0) or (sess[:7] != sessions[i - 1][:7])
        if not is_first_session_of_month:
            continue

        if strict_full_pool:
            target_symbols = list(candidates)
        else:
            # Active candidate symbols with non-NaN price on this session
            target_symbols = [
                sym for sym in candidates if not np.isnan(matrix.get_price(sess, sym))
            ]

        if not target_symbols:
            # All candidates unlisted or NaN
            target_weights: dict[str, float] = {}
        else:
            w = 1.0 / len(target_symbols)
            target_weights = {sym: w for sym in target_symbols}

        ev = RebalanceEvent.create(
            parent_hash=prev_hash,
            effective_session=sess,
            runner_id=f"benchmark_{pool_id}_ew",
            runner_version="1.0.0",
            target_weights=target_weights,
            reason=f"Monthly equal-weight rebalance for {sess[:7]}",
        )
        events.append(ev)
        prev_hash = ev.event_hash

    return simulate_portfolio(matrix=matrix, ledger_events=events, config=config)
