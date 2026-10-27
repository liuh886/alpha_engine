"""Racetrack unified portfolio simulation and NAV conversion engine (V & NAV Engine).

Implements daily weight drift dynamics, one-sided turnover conservation,
linear transaction friction deductions, continuous NAV compounding, and
rolling/annualized performance KPIs (MDD, Sharpe, CAGR, Excess vs QQQ).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from src.racetrack.contracts import (
    CalendarSessionError,
    ChronologyOrderError,
    DuplicateSessionError,
    EngineConfig,
    LifecycleIntegrityError,
    MissingPriceDataError,
    NAVPoint,
    PriceMatrix,
    RebalanceEvent,
    SimulationResult,
    UnauthorizedAssetError,
)


def simulate_portfolio(
    matrix: PriceMatrix,
    ledger_events: Sequence[RebalanceEvent],
    config: EngineConfig = EngineConfig(),
) -> SimulationResult:
    """Execute unified portfolio simulation over the price matrix and ledger events.

    Args:
        matrix: Aligned PriceMatrix P(t, s).
        ledger_events: Sequence of RebalanceEvent objects.
        config: EngineConfig specifying friction rate, risk-free rate, and annualization.

    Returns:
        SimulationResult containing daily NAV series and computed KPI metrics.

    Raises:
        CalendarSessionError: If matrix has no sessions or event date is not in matrix.
        UnauthorizedAssetError: If an event targets an asset outside the matrix universe.
        MissingPriceDataError: If price data is NaN for any held/targeted asset.
    """
    sessions = matrix.sessions
    if not sessions:
        raise CalendarSessionError("PriceMatrix contains zero trading sessions")

    session_set = set(sessions)

    # 1. Index and validate rebalance events
    events_by_session: dict[str, RebalanceEvent] = {}
    seen_sessions: set[str] = set()
    prev_event_session: str | None = None
    runner_id = "generic_runner"
    runner_version = "1.0.0"

    for ev in ledger_events:
        if ev.effective_session not in session_set:
            raise CalendarSessionError(
                f"RebalanceEvent session '{ev.effective_session}' is not a valid trading session in PriceMatrix"
            )
        if ev.effective_session in seen_sessions:
            raise DuplicateSessionError(
                f"Duplicate rebalance event detected for session '{ev.effective_session}'"
            )
        if prev_event_session is not None and ev.effective_session < prev_event_session:
            raise ChronologyOrderError(
                f"Rebalance events are out of order: '{ev.effective_session}' < '{prev_event_session}'"
            )

        seen_sessions.add(ev.effective_session)
        prev_event_session = ev.effective_session

        # Validate that targeted assets belong to matrix symbols
        for sym, weight in ev.target_weights.items():
            if weight > 0 and sym not in matrix.symbols:
                raise UnauthorizedAssetError(
                    f"Asset '{sym}' in rebalance event is not part of authorized universe '{matrix.pool_id}'"
                )
        events_by_session[ev.effective_session] = ev
        runner_id = ev.runner_id
        runner_version = ev.runner_version

    # 2. Inception state at t_0: initial cash capital allocation
    # Portfolio starts at t_0- with 100% cash (V(t_0-) = 1.0, w_cash = 1.0, w_i = 0.0)
    t_0 = sessions[0]
    if t_0 in events_by_session:
        init_ev = events_by_session[t_0]
        current_weights = {k: float(v) for k, v in init_ev.target_weights.items() if v > 0}
        current_cash = float(init_ev.cash_weight)
        # One-sided turnover from 100% cash: sum(target equity weights)
        init_turnover = float(sum(current_weights.values()))
        init_friction = init_turnover * config.friction_rate
        init_net_ret = -init_friction
        init_nav = 1.0 - init_friction
        init_drawdown = init_net_ret
    else:
        current_weights = {}
        current_cash = 1.0
        init_turnover = 0.0
        init_friction = 0.0
        init_net_ret = 0.0
        init_nav = 1.0
        init_drawdown = 0.0

    # Ensure held assets at t_0 have valid non-NaN prices
    for sym, weight in current_weights.items():
        if weight > 0:
            p0 = matrix.get_price(t_0, sym)
            if np.isnan(p0):
                raise LifecycleIntegrityError(
                    f"Held asset '{sym}' has missing (NaN) price on inception session '{t_0}'"
                )

    nav_history: list[NAVPoint] = []
    nav_history.append(
        NAVPoint(
            session=t_0,
            nav=init_nav,
            gross_return=0.0,
            net_return=init_net_ret,
            turnover=init_turnover,
            friction=init_friction,
            drawdown=init_drawdown,
            weights=dict(current_weights),
            cash_weight=current_cash,
        )
    )

    peak_nav = max(1.0, init_nav)
    current_nav = init_nav
    last_known_prices: dict[str, float] = {}

    # 3. Daily iteration over sessions t_1 to t_N
    for i in range(1, len(sessions)):
        prev_sess = sessions[i - 1]
        curr_sess = sessions[i]

        # 3.1 Calculate gross return from t-1 to t
        r_gross = 0.0
        drifted_weights: dict[str, float] = {}

        for sym, w_prev in current_weights.items():
            if w_prev <= 0:
                continue
            p_curr = matrix.get_price(curr_sess, sym)
            if np.isnan(p_curr):
                # Held asset is suspended/halted on curr_sess.
                # In real market simulation, suspended assets have zero daily return (price unchanged)
                # until trading resumes.
                if sym not in last_known_prices:
                    p_prev = matrix.get_price(prev_sess, sym)
                    if not np.isnan(p_prev) and p_prev > 0:
                        last_known_prices[sym] = p_prev
                    else:
                        raise MissingPriceDataError(
                            f"Held asset '{sym}' has missing (NaN) price on session '{curr_sess}'"
                        )
                asset_ret = 0.0
                r_gross += w_prev * asset_ret
                drifted_weights[sym] = w_prev * (1.0 + asset_ret)
                continue

            p_ref = last_known_prices.pop(sym, None)
            if p_ref is None:
                p_ref = matrix.get_price(prev_sess, sym)

            if np.isnan(p_ref) or p_ref <= 0:
                raise MissingPriceDataError(
                    f"Invalid non-positive price for '{sym}' on session '{prev_sess}': {p_ref}"
                )

            asset_ret = (p_curr / p_ref) - 1.0
            r_gross += w_prev * asset_ret
            # Temporary storage for unnormalized drifted weight
            drifted_weights[sym] = w_prev * (1.0 + asset_ret)

        # 3.2 Normalize drifted weights by (1 + r_gross)
        gross_multiplier = 1.0 + r_gross
        for sym in list(drifted_weights.keys()):
            drifted_weights[sym] = drifted_weights[sym] / gross_multiplier

        w_cash_drift = current_cash / gross_multiplier

        # 3.3 Check for rebalance event effective at close of curr_sess
        if curr_sess in events_by_session:
            ev = events_by_session[curr_sess]
            target_weights = {k: float(v) for k, v in ev.target_weights.items() if v > 0}
            target_cash = float(ev.cash_weight)

            # Check prices for any newly targeted asset
            for sym, weight in target_weights.items():
                if weight > 0:
                    p = matrix.get_price(curr_sess, sym)
                    if np.isnan(p):
                        raise LifecycleIntegrityError(
                            f"Asset '{sym}' targeted for rebalance has missing (NaN) price on session '{curr_sess}'"
                        )

            # One-sided turnover: 0.5 * ( sum(|w_target - w_drift|) + |w_cash_target - w_cash_drift| )
            all_assets = set(drifted_weights.keys()) | set(target_weights.keys())
            diff_sum = sum(
                abs(target_weights.get(sym, 0.0) - drifted_weights.get(sym, 0.0))
                for sym in all_assets
            )
            diff_sum += abs(target_cash - w_cash_drift)
            turnover = 0.5 * diff_sum
            friction = turnover * config.friction_rate

            current_weights = dict(target_weights)
            current_cash = target_cash
        else:
            turnover = 0.0
            friction = 0.0
            current_weights = dict(drifted_weights)
            current_cash = w_cash_drift

        # 3.4 Net return and continuous NAV compounding
        r_net = r_gross - friction
        current_nav = current_nav * (1.0 + r_net)

        # 3.5 Maximum Drawdown tracking
        if current_nav > peak_nav:
            peak_nav = current_nav
        drawdown = (peak_nav - current_nav) / peak_nav if peak_nav > 0 else 0.0

        nav_history.append(
            NAVPoint(
                session=curr_sess,
                nav=current_nav,
                gross_return=r_gross,
                net_return=r_net,
                turnover=turnover,
                friction=friction,
                drawdown=drawdown,
                weights=dict(current_weights),
                cash_weight=current_cash,
            )
        )

    # 4. Compute performance metrics
    total_sessions = len(sessions)
    n_steps = total_sessions - 1
    final_nav = nav_history[-1].nav
    cumulative_return = final_nav - 1.0

    if n_steps >= 1 and final_nav > 0:
        annualized_cagr = (final_nav ** (config.annual_trading_days / n_steps)) - 1.0
    else:
        annualized_cagr = 0.0

    net_returns = [pt.net_return for pt in nav_history[1:]]
    if len(net_returns) > 1:
        daily_std = float(np.std(net_returns, ddof=1))
        annualized_volatility = daily_std * np.sqrt(config.annual_trading_days)
    else:
        annualized_volatility = 0.0

    # Sharpe ratio with risk-free rate
    if len(net_returns) > 1:
        rf_daily = (
            (1.0 + config.risk_free_rate_annual) ** (1.0 / config.annual_trading_days)
        ) - 1.0
        excess_returns = np.array(net_returns) - rf_daily
        excess_mean = float(np.mean(excess_returns))
        excess_std = float(np.std(excess_returns, ddof=1))
        if excess_std > 1e-12:
            annualized_sharpe = float(
                np.sqrt(config.annual_trading_days) * (excess_mean / excess_std)
            )
        else:
            annualized_sharpe = 0.0
    else:
        annualized_sharpe = 0.0

    max_dd = max((pt.drawdown for pt in nav_history), default=0.0)
    max_drawdown = -float(max_dd)
    cumulative_turnover = sum(pt.turnover for pt in nav_history)

    # Benchmark QQQ excess return
    ref_symbol = matrix.reference_symbol
    annualized_excess_return = 0.0
    if ref_symbol in matrix.prices.columns and n_steps >= 1:
        p_start = matrix.get_price(sessions[0], ref_symbol)
        p_end = matrix.get_price(sessions[-1], ref_symbol)
        if not np.isnan(p_start) and not np.isnan(p_end) and p_start > 0 and p_end > 0:
            benchmark_cagr = ((p_end / p_start) ** (config.annual_trading_days / n_steps)) - 1.0
            annualized_excess_return = annualized_cagr - benchmark_cagr

    return SimulationResult(
        runner_id=runner_id,
        runner_version=runner_version,
        start_session=sessions[0],
        end_session=sessions[-1],
        total_sessions=total_sessions,
        cumulative_return=cumulative_return,
        annualized_cagr=annualized_cagr,
        annualized_volatility=annualized_volatility,
        annualized_sharpe=annualized_sharpe,
        max_drawdown=max_drawdown,
        cumulative_turnover=cumulative_turnover,
        annualized_excess_return=annualized_excess_return,
        nav_history=tuple(nav_history),
    )
