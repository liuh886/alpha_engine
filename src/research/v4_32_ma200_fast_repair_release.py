"""MA200 slow-bear defense with frozen v4.2 fast-repair release.

The slow entry selector is unchanged from v4.31. Strong defense is suppressed
as soon as the existing v4.2/v4.27 repair-ready semantics are true, allowing
the source allocation (including the frozen v4.27 panic-repair boost) to resume
at the next open. No thresholds, windows or weights are changed.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars, _return_metrics
from src.research.v4_2_panic_repair_boost import run_panic_repair_comparison

BASELINE = "current_v4_2"
PANIC = "v4_27_panic_repair_boost"
GUARD = "v4_32_ma200_fast_repair_defense"
JOINT = "v4_32_panic_repair_ma200_fast_release"
DEFENSIVE_EQUITY_WEIGHT = 0.50
DEFENSIVE_CASH_WEIGHT = 0.50
TRANSACTION_COST_BPS_PER_TURNOVER_UNIT = 10.0


def build_ma200_fast_release_trace(daily: pd.DataFrame) -> pd.DataFrame:
    """Build slow-entry / fast-release close decisions and next-open flags."""
    required = {
        "ma_long",
        "early_repair",
        "stress_price_failure",
        "vix_easing",
        "vix_normalized",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"daily trace missing columns: {missing}")
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")

    ma_long = pd.to_numeric(daily["ma_long"], errors="coerce")
    ma200_falling = ma_long.notna() & ma_long.shift(1).notna() & ma_long.lt(ma_long.shift(1))
    repair_ready = (
        daily["early_repair"].fillna(False).astype(bool)
        & ~daily["stress_price_failure"].fillna(True).astype(bool)
        & (
            daily["vix_easing"].fillna(False).astype(bool)
            | daily["vix_normalized"].fillna(False).astype(bool)
        )
    )
    strong_defense = ma200_falling & ~repair_ready
    trace = pd.DataFrame(
        {
            "ma200": ma_long,
            "ma200_falling_at_close": ma200_falling.astype(bool),
            "fast_repair_ready_at_close": repair_ready.astype(bool),
            "strong_defense_at_close": strong_defense.astype(bool),
        },
        index=daily.index,
    )
    trace["strong_defense_at_open"] = trace["strong_defense_at_close"].shift(
        1, fill_value=False
    )
    return trace


def _source_weights(source: StrategyResult) -> pd.DataFrame:
    columns = ["weight_QQQI", "weight_QQQ", "weight_TQQQ"]
    missing = sorted(set(columns) - set(source.daily.columns))
    if missing:
        raise ValueError(f"source missing weight columns: {missing}")
    return source.daily[columns].rename(
        columns={"weight_QQQI": "QQQI", "weight_QQQ": "QQQ", "weight_TQQQ": "TQQQ"}
    ).astype(float).copy()


def cash_next_open_return(
    bars: Mapping[str, pd.DataFrame], symbol: str, index: pd.DatetimeIndex
) -> pd.Series:
    if symbol not in bars:
        raise ValueError(f"cash proxy bars missing: {symbol}")
    normalised = _normalise_bars(bars[symbol], symbol)
    returns = normalised["open"].shift(-1) / normalised["open"] - 1.0
    aligned = returns.reindex(index)
    if bool(aligned.isna().any()):
        missing = aligned.index[aligned.isna()]
        if len(missing) != 1 or missing[0] != index[-1]:
            raise ValueError(f"{symbol} cash proxy missing strategy-session returns")
    return aligned.rename(f"{symbol}_next_open_return")


def apply_fast_release_state0_defense(
    source: StrategyResult,
    trace: pd.DataFrame,
    *,
    cash_symbol: str,
) -> tuple[pd.DataFrame, pd.Series]:
    """Apply strong defense only to executed state 0 after a non-repaired close."""
    daily = source.daily
    weights = _source_weights(source)
    weights[cash_symbol] = 0.0
    strong_at_open = trace["strong_defense_at_open"].reindex(weights.index).fillna(False)
    eligible = daily["position_state"].astype(int).eq(0) & strong_at_open.astype(bool)

    weights.loc[eligible, "QQQI"] = DEFENSIVE_EQUITY_WEIGHT
    weights.loc[eligible, "QQQ"] = 0.0
    weights.loc[eligible, "TQQQ"] = 0.0
    weights.loc[eligible, cash_symbol] = DEFENSIVE_CASH_WEIGHT

    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("v4.32 weights must sum to one")
    if bool((weights < -1e-12).any().any()):
        raise AssertionError("v4.32 weights cannot be negative")

    non_state0 = daily["position_state"].astype(int).ne(0)
    original = _source_weights(source)
    if not np.allclose(
        weights.loc[non_state0, ["QQQI", "QQQ", "TQQQ"]],
        original.loc[non_state0, ["QQQI", "QQQ", "TQQQ"]],
    ):
        raise AssertionError("v4.32 changed formal state 1/2 allocations")
    if bool(weights.loc[non_state0, cash_symbol].gt(0.0).any()):
        raise AssertionError("cash defense appeared outside state 0")
    return weights, eligible.astype(bool)


def run_fast_release_backtest(
    source: StrategyResult,
    bars: Mapping[str, pd.DataFrame],
    *,
    cash_symbol: str,
    strategy_key: str,
) -> StrategyResult:
    daily = source.daily.copy()
    trace = build_ma200_fast_release_trace(daily)
    weights, active = apply_fast_release_state0_defense(source, trace, cash_symbol=cash_symbol)
    daily = daily.join(trace)
    daily["ma200_fast_defense_active"] = active
    daily[f"{cash_symbol}_next_open_return"] = cash_next_open_return(
        bars, cash_symbol, daily.index
    )
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
    daily["transaction_cost"] = (
        turnover * TRANSACTION_COST_BPS_PER_TURNOVER_UNIT / 10_000.0
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    changes = weights.loc[daily.index].ne(weights.loc[daily.index].shift()).any(axis=1)
    active_dates = daily.index[daily["ma200_fast_defense_active"].fillna(False)]
    year_counts = pd.Series(active_dates.year).value_counts().sort_index()
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(int(changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "guard_sessions": int(len(active_dates)),
            "guard_years": int(len(year_counts)),
            "largest_guard_year_share": (
                float(year_counts.max() / year_counts.sum()) if len(year_counts) else 1.0
            ),
            "repair_release_sessions": int(
                (daily["position_state"].astype(int).eq(0) & daily["fast_repair_ready_at_close"].shift(1, fill_value=False)).sum()
            ),
        }
    )
    trades = daily.loc[changes].reset_index(names="date")
    return StrategyResult(strategy_key, daily, trades, metrics)


def run_v4_32_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    fear_greed: pd.DataFrame,
    *,
    cash_symbol: str,
) -> tuple[pd.DataFrame, dict[str, StrategyResult], dict[str, Any]]:
    _, base_results = run_panic_repair_comparison(bars, bridge_contract, fear_greed)
    baseline = base_results[BASELINE]
    panic = base_results[PANIC]
    for result in (baseline, panic):
        result.metrics.setdefault("guard_sessions", 0)
        result.metrics.setdefault("guard_years", 0)
        result.metrics.setdefault("largest_guard_year_share", 0.0)
        result.metrics.setdefault("repair_release_sessions", 0)
    guard = run_fast_release_backtest(
        baseline, bars, cash_symbol=cash_symbol, strategy_key=GUARD
    )
    joint = run_fast_release_backtest(
        panic, bars, cash_symbol=cash_symbol, strategy_key=JOINT
    )
    results = {BASELINE: baseline, PANIC: panic, GUARD: guard, JOINT: joint}
    if not all(
        result.daily["position_state"].equals(baseline.daily["position_state"])
        for result in results.values()
    ):
        raise AssertionError("v4.32 changed the formal v4.2 state trace")
    headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    diagnostics = {
        "same_formal_state_trace": True,
        "cash_symbol": cash_symbol,
        "guard_sessions": int(guard.metrics["guard_sessions"]),
        "guard_years": int(guard.metrics["guard_years"]),
        "largest_guard_year_share": float(guard.metrics["largest_guard_year_share"]),
        "repair_release_sessions": int(guard.metrics["repair_release_sessions"]),
        "joint_guard_sessions": int(joint.metrics["guard_sessions"]),
    }
    return headline, results, diagnostics
