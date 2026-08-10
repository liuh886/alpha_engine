"""Frozen VVIX state-0 defensive escalation for the QQQ v4.2 family.

VVIX is used only as a second-order tail-risk selector inside the already
formal defensive state 0. It never changes the v4.2 state trace, state 1 or
state 2. The 252-session / 80th-percentile stress convention is inherited from
v4.2 VIX logic and the 50/50 defensive step is inherited from the predeclared
blended SGOV architecture.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars, _return_metrics
from src.research.v4_2_panic_repair_boost import run_panic_repair_comparison

BASELINE = "current_v4_2"
PANIC = "v4_27_panic_repair_boost"
GUARD = "v4_29_vvix_state0_defense"
JOINT = "v4_29_panic_repair_vvix_state0_defense"
VVIX_WINDOW = 252
VVIX_STRESS_QUANTILE = 0.80
DEFENSIVE_EQUITY_WEIGHT = 0.50
DEFENSIVE_CASH_WEIGHT = 0.50
TRANSACTION_COST_BPS_PER_TURNOVER_UNIT = 10.0


def _normalise_vvix(vvix: pd.DataFrame) -> pd.Series:
    if "close" not in vvix.columns:
        raise ValueError("VVIX history missing close")
    frame = vvix.copy()
    frame.index = pd.to_datetime(frame.index, errors="raise").tz_localize(None).normalize()
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise ValueError("VVIX history contains duplicate dates")
    close = pd.to_numeric(frame["close"], errors="coerce")
    if bool(close.dropna().le(0.0).any()):
        raise ValueError("VVIX contains non-positive close values")
    return close.rename("vvix_close")


def build_vvix_stress_trace(daily: pd.DataFrame, vvix: pd.DataFrame) -> pd.DataFrame:
    """Build point-in-time VVIX stress and shift once for next-open execution."""
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")
    close = _normalise_vvix(vvix).reindex(daily.index)
    threshold = close.rolling(VVIX_WINDOW, min_periods=VVIX_WINDOW).quantile(VVIX_STRESS_QUANTILE)
    stress = close.notna() & threshold.notna() & close.ge(threshold)
    trace = pd.DataFrame(
        {
            "vvix_close": close,
            "vvix_stress_threshold": threshold,
            "vvix_stress_at_close": stress.astype(bool),
        },
        index=daily.index,
    )
    trace["vvix_stress_at_open"] = trace["vvix_stress_at_close"].shift(1, fill_value=False)
    return trace


def cash_next_open_return(
    bars: Mapping[str, pd.DataFrame], symbol: str, index: pd.DatetimeIndex
) -> pd.Series:
    """Return adjusted open-to-next-open cash-proxy returns on the strategy index."""
    if symbol not in bars:
        raise ValueError(f"cash proxy bars missing: {symbol}")
    normalised = _normalise_bars(bars[symbol], symbol)
    returns = normalised["open"].shift(-1) / normalised["open"] - 1.0
    aligned = returns.reindex(index)
    if bool(aligned.isna().any()):
        missing = aligned.index[aligned.isna()]
        if len(missing) == 1 and missing[0] == index[-1]:
            pass
        else:
            raise ValueError(f"{symbol} cash proxy missing strategy-session returns")
    return aligned.rename(f"{symbol}_next_open_return")


def _source_weights(source: StrategyResult) -> pd.DataFrame:
    columns = ["weight_QQQI", "weight_QQQ", "weight_TQQQ"]
    missing = sorted(set(columns) - set(source.daily.columns))
    if missing:
        raise ValueError(f"source missing weight columns: {missing}")
    return (
        source.daily[columns]
        .rename(
            columns={
                "weight_QQQI": "QQQI",
                "weight_QQQ": "QQQ",
                "weight_TQQQ": "TQQQ",
            }
        )
        .astype(float)
        .copy()
    )


def apply_vvix_state0_defense(
    source: StrategyResult,
    trace: pd.DataFrame,
    *,
    cash_symbol: str,
) -> tuple[pd.DataFrame, pd.Series]:
    """Override only stressed executed state-0 sessions with 50% cash defense."""
    daily = source.daily
    weights = _source_weights(source)
    weights[cash_symbol] = 0.0
    stress_at_open = trace["vvix_stress_at_open"].reindex(weights.index).fillna(False)
    eligible = daily["position_state"].astype(int).eq(0) & stress_at_open.astype(bool)

    weights.loc[eligible, "QQQI"] = DEFENSIVE_EQUITY_WEIGHT
    weights.loc[eligible, "QQQ"] = 0.0
    weights.loc[eligible, "TQQQ"] = 0.0
    weights.loc[eligible, cash_symbol] = DEFENSIVE_CASH_WEIGHT

    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("VVIX defensive weights must sum to one")
    if bool((weights < -1e-12).any().any()):
        raise AssertionError("VVIX defensive weights cannot be negative")

    non_state0 = daily["position_state"].astype(int).ne(0)
    original = _source_weights(source)
    if not np.allclose(
        weights.loc[non_state0, ["QQQI", "QQQ", "TQQQ"]],
        original.loc[non_state0, ["QQQI", "QQQ", "TQQQ"]],
    ):
        raise AssertionError("VVIX defense changed formal state 1/2 allocations")
    if bool(weights.loc[non_state0, cash_symbol].gt(0.0).any()):
        raise AssertionError("cash defense appeared outside formal state 0")
    return weights, eligible.astype(bool)


def run_vvix_defensive_backtest(
    source: StrategyResult,
    bars: Mapping[str, pd.DataFrame],
    vvix: pd.DataFrame,
    *,
    cash_symbol: str,
    strategy_key: str,
) -> StrategyResult:
    """Apply the frozen VVIX state-0 defensive escalation to one source result."""
    daily = source.daily.copy()
    trace = build_vvix_stress_trace(daily, vvix)
    weights, active = apply_vvix_state0_defense(source, trace, cash_symbol=cash_symbol)
    daily = daily.join(trace)
    daily["vvix_state0_defense_active"] = active
    daily[f"{cash_symbol}_next_open_return"] = cash_next_open_return(bars, cash_symbol, daily.index)
    for asset in weights.columns:
        daily[f"weight_{asset}"] = weights[asset]

    daily["gross_return"] = (
        daily["weight_QQQI"] * daily["QQQI_next_open_return"]
        + daily["weight_QQQ"] * daily["QQQ_next_open_return"]
        + daily["weight_TQQQ"] * daily["TQQQ_next_open_return"]
        + daily[f"weight_{cash_symbol}"] * daily[f"{cash_symbol}_next_open_return"]
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * TRANSACTION_COST_BPS_PER_TURNOVER_UNIT / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    changes = weights.loc[daily.index].ne(weights.loc[daily.index].shift()).any(axis=1)
    active_dates = daily.index[daily["vvix_state0_defense_active"].fillna(False)]
    year_counts = pd.Series(active_dates.year).value_counts().sort_index()
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(int(changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "vvix_guard_sessions": int(len(active_dates)),
            "vvix_guard_years": int(len(year_counts)),
            "largest_guard_year_share": (
                float(year_counts.max() / year_counts.sum()) if len(year_counts) else 1.0
            ),
        }
    )
    trade_columns = [
        "position_state",
        "vvix_close",
        "vvix_stress_threshold",
        "vvix_stress_at_open",
        "vvix_state0_defense_active",
        *[f"weight_{asset}" for asset in weights.columns],
        "turnover_units",
        "transaction_cost",
    ]
    trades = daily.loc[changes, trade_columns].reset_index(names="date")
    return StrategyResult(strategy_key, daily, trades, metrics)


def run_vvix_state0_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    fear_greed: pd.DataFrame,
    vvix: pd.DataFrame,
    *,
    cash_symbol: str,
) -> tuple[pd.DataFrame, dict[str, StrategyResult], dict[str, Any]]:
    """Run v4.2, v4.27, VVIX guard and the frozen joint candidate."""
    _, base_results = run_panic_repair_comparison(bars, bridge_contract, fear_greed)
    baseline = base_results[BASELINE]
    panic = base_results[PANIC]
    for result in (baseline, panic):
        result.metrics.setdefault("vvix_guard_sessions", 0)
        result.metrics.setdefault("vvix_guard_years", 0)
        result.metrics.setdefault("largest_guard_year_share", 0.0)
    guard = run_vvix_defensive_backtest(
        baseline,
        bars,
        vvix,
        cash_symbol=cash_symbol,
        strategy_key=GUARD,
    )
    joint = run_vvix_defensive_backtest(
        panic,
        bars,
        vvix,
        cash_symbol=cash_symbol,
        strategy_key=JOINT,
    )
    results = {BASELINE: baseline, PANIC: panic, GUARD: guard, JOINT: joint}
    same_trace = all(
        result.daily["position_state"].equals(baseline.daily["position_state"])
        for result in results.values()
    )
    if not same_trace:
        raise AssertionError("v4.29 changed the formal v4.2 state trace")
    headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    diagnostics = {
        "same_formal_state_trace": True,
        "cash_symbol": cash_symbol,
        "vvix_window": VVIX_WINDOW,
        "vvix_stress_quantile": VVIX_STRESS_QUANTILE,
        "guard_sessions": int(guard.metrics["vvix_guard_sessions"]),
        "guard_years": int(guard.metrics["vvix_guard_years"]),
        "largest_guard_year_share": float(guard.metrics["largest_guard_year_share"]),
        "joint_guard_sessions": int(joint.metrics["vvix_guard_sessions"]),
    }
    return headline, results, diagnostics
