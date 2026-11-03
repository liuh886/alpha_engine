"""Racetrack independent US87 challenger runner.

Implements an independent low-volatility cross-sectional selection rule
over the fixed US87 candidate pool, with frozen thesis, strict PIT lookback,
zero lookahead, deterministic rebalancing, and cash buffering.
"""

from __future__ import annotations

import hashlib
import numpy as np

from src.racetrack.contracts import (
    CalendarSessionError,
    EngineConfig,
    RebalanceEvent,
    SimulationResult,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.matrix import PriceMatrix
from src.racetrack.runner import RunnerContract

US87_LOW_VOL_RUNNER_ID = "us87_low_vol_challenger_v1"
US87_LOW_VOL_RUNNER_VERSION = "1.0.0"

US87_LOW_VOL_THESIS = (
    "Select the lowest realized-volatility quintile of US87 candidate equities "
    "under monthly rebalancing to test defensive risk-adjusted performance against "
    "the unselected equal-weight pool benchmark. The hypothesis expects reduced "
    "drawdowns during market turbulence but underperformance during speculative, "
    "high-beta technology rallies. All trailing volatility estimates use closed "
    "sessions strictly before rebalance date; unlisted, halted, or short-history "
    "assets are disqualified with target slots held in cash."
)

US87_LOW_VOL_SELECTION = (
    "At the first session of each calendar month after the initial 20-session "
    "burn-in window, compute 20-session annualized realized volatility for all "
    "active US87 candidates with complete price history. Rank ascending and select "
    "the top K=20 lowest-volatility equities, weighting each at 5.0%. Unavailable "
    "or unlisted slots remain in cash."
)

US87_LOW_VOL_REBALANCE = (
    "Initialize in cash at the first replay session. Rebalance at the first trading "
    "session of each calendar month with complete lookback history. Deduct shared "
    "engine friction (5 bps) on rebalance turnover. Holdings drift naturally intra-month "
    "with zero rebalance turnover between monthly boundaries."
)


def compute_realized_volatility(prices: np.ndarray) -> float:
    """Compute annualized realized volatility from a 1D sequence of prices.

    Uses daily log returns: r_t = ln(P_t / P_{t-1}).
    Annualized with 252 trading sessions.

    Returns:
        Annualized standard deviation of daily log returns, or np.nan if invalid.
    """
    if len(prices) < 2:
        return float(np.nan)
    if np.any(np.isnan(prices)) or np.any(prices <= 0):
        return float(np.nan)
    returns = np.diff(np.log(prices))
    if len(returns) < 2:
        return float(np.nan)
    std = float(np.std(returns, ddof=1))
    return std * np.sqrt(252.0)


def generate_low_vol_events(
    matrix: PriceMatrix,
    pool_id: str = "us_selected_equities_v2",
    runner_id: str = US87_LOW_VOL_RUNNER_ID,
    runner_version: str = US87_LOW_VOL_RUNNER_VERSION,
    lookback_sessions: int = 20,
    top_k: int = 20,
) -> list[RebalanceEvent]:
    """Generate deterministic rebalance events for the US87 low-volatility challenger.

    Rules:
        - Candidate universe is strictly restricted to matrix.candidate_symbols.
        - Benchmark reference symbol (e.g. QQQ) is NEVER allocated.
        - Rebalance occurs on the first trading session of each calendar month.
        - Initial session (month 1): 100% cash buffer (burn-in period).
        - Subsequent months: compute trailing `lookback_sessions` realized volatility
          using sessions strictly BEFORE the rebalance session (t - lookback to t - 1).
        - Rank ascending (lowest volatility first; ties broken by symbol string).
        - Select top K candidates and allocate 1 / K target weight each (e.g. 5%).
        - If fewer than K candidates have complete lookback history, unallocated slots remain cash.
        - Intra-month sessions drift naturally with zero turnover.
    """
    if matrix.pool_id != pool_id:
        raise ValueError(
            f"Challenger pool_id '{pool_id}' does not match matrix pool_id '{matrix.pool_id}'"
        )
    sessions = matrix.sessions
    if not sessions:
        raise CalendarSessionError("Matrix contains zero sessions")

    candidates = matrix.candidate_symbols
    if not candidates:
        raise ValueError(f"Matrix contains zero candidate symbols for pool '{pool_id}'")

    import exchange_calendars as xcals

    calendar = xcals.get_calendar(matrix.calendar)
    events: list[RebalanceEvent] = []
    prev_hash = "0" * 64
    target_slot_weight = 1.0 / float(top_k)

    for i, sess in enumerate(sessions):
        # Identify first trading session of each calendar month
        is_first_session_of_month = (i == 0) or (sess[:7] != sessions[i - 1][:7])
        if not is_first_session_of_month:
            continue

        target_weights: dict[str, float] = {}

        # Lookback requires at least `lookback_sessions` historical sessions strictly before `sess`
        if i >= lookback_sessions:
            history_sessions = sessions[i - lookback_sessions : i]
            candidate_vols: list[tuple[float, str]] = []

            for sym in candidates:
                # Extract trailing price series for sym
                price_series = np.array(
                    [matrix.get_price(hist_sess, sym) for hist_sess in history_sessions],
                    dtype=np.float64,
                )
                # Current session price must also be active/valid to buy into it today
                current_price = matrix.get_price(sess, sym)
                if np.isnan(current_price) or current_price <= 0:
                    continue

                vol = compute_realized_volatility(price_series)
                if not np.isnan(vol) and np.isfinite(vol) and vol > 0:
                    candidate_vols.append((vol, sym))

            # Sort ascending: lowest volatility first. Tie-breaker is symbol name for strict determinism.
            candidate_vols.sort(key=lambda item: (item[0], item[1]))

            # Select top K
            selected = candidate_vols[:top_k]
            for _, sym in selected:
                target_weights[sym] = target_slot_weight
            reason = (
                f"Monthly low-volatility selection for {sess[:7]}: "
                f"selected {len(selected)}/{top_k} lowest-volatility candidates "
                f"(slot_weight={target_slot_weight:.4f}), "
                f"cash_weight={max(0.0, 1.0 - len(selected) * target_slot_weight):.4f}"
            )
        else:
            # Insufficient trailing history: maintain 100% cash
            target_weights = {}
            reason = (
                f"Initial burn-in window for {sess[:7]}: "
                f"100% cash held pending {lookback_sessions} historical sessions"
            )

        ev = RebalanceEvent.create(
            parent_hash=prev_hash,
            effective_session=sess,
            runner_id=runner_id,
            runner_version=runner_version,
            event_id=hashlib.sha256(
                f"{pool_id}:{runner_id}:{runner_version}:{sess}".encode()
            ).hexdigest(),
            timestamp_utc=calendar.session_close(sess).isoformat(),
            target_weights=target_weights,
            reason=reason,
        )
        events.append(ev)
        prev_hash = ev.event_hash

    return events


def create_us_low_vol_runner(
    lookback_sessions: int = 20,
    top_k: int = 20,
    runner_id: str = US87_LOW_VOL_RUNNER_ID,
    runner_version: str = US87_LOW_VOL_RUNNER_VERSION,
) -> RunnerContract:
    """Factory creating the admitted US87 Low-Volatility Challenger Runner."""
    return RunnerContract(
        runner_id=runner_id,
        runner_version=runner_version,
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis=US87_LOW_VOL_THESIS,
        selection_logic=US87_LOW_VOL_SELECTION,
        rebalance_logic=US87_LOW_VOL_REBALANCE,
        events_generator=lambda matrix: generate_low_vol_events(
            matrix,
            pool_id="us_selected_equities_v2",
            runner_id=runner_id,
            runner_version=runner_version,
            lookback_sessions=lookback_sessions,
            top_k=top_k,
        ),
    )


def simulate_us_low_vol_challenger(
    matrix: PriceMatrix,
    config: EngineConfig = EngineConfig(),
    lookback_sessions: int = 20,
    top_k: int = 20,
) -> SimulationResult:
    """Run full simulation of US87 Low-Volatility Challenger."""
    runner = create_us_low_vol_runner(
        lookback_sessions=lookback_sessions,
        top_k=top_k,
    )
    return runner.run(matrix=matrix, config=config)
