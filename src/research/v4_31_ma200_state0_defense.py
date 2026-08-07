"""Frozen falling-MA200 defensive escalation inside formal QQQ v4.2 state 0.

The selector uses only the existing v4.2 SMA(200). A falling one-day SMA(200)
change is a long-horizon sign because it is proportional to close[t]-close[t-200].
No new lookback, slope magnitude or persistence parameter is introduced.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars, _return_metrics
from src.research.v4_2_panic_repair_boost import run_panic_repair_comparison

BASELINE = "current_v4_2"
PANIC = "v4_27_panic_repair_boost"
GUARD = "v4_31_ma200_state0_defense"
JOINT = "v4_31_panic_repair_ma200_state0_defense"
DEFENSIVE_EQUITY_WEIGHT = 0.50
DEFENSIVE_CASH_WEIGHT = 0.50
TRANSACTION_COST_BPS_PER_TURNOVER_UNIT = 10.0


def build_ma200_trend_trace(daily: pd.DataFrame) -> pd.DataFrame:
    """Build close-time MA200 direction and shift once for next-open execution."""
    if "ma_long" not in daily.columns:
        raise ValueError("daily trace missing ma_long")
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")
    ma_long = pd.to_numeric(daily["ma_long"], errors="coerce")
    falling = ma_long.notna() & ma_long.shift(1).notna() & ma_long.lt(ma_long.shift(1))
    trace = pd.DataFrame(
        {
            "ma200": ma_long,
            "ma200_falling_at_close": falling.astype(bool),
        },
        index=daily.index,
    )
    trace["ma200_falling_at_open"] = trace["ma200_falling_at_close"].shift(
        1, fill_value=False
    )
    return trace


def _source_weights(source: StrategyResult) -> pd.DataFrame:
    columns = ["weight_QQQI", "weight_QQQ", "weight_TQQQ"]
    missing = sorted(set(columns) - set(source.daily.columns))
    if missing:
        raise ValueError(f"source missing weight columns: {missing}")
    return source.daily[columns].rename(
        columns={
            "weight_QQQI": "QQQI",
            "weight_QQQ": "QQQ",
            "weight_TQQQ": "TQQQ",
        }
    ).astype(float).copy()


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
        if len(missing) != 1 or missing[0] != index[-1]:
            raise ValueError(f"{symbol} cash proxy missing strategy-session returns")
    return aligned.rename(f"{symbol}_next_open_return")


def apply_ma200_state0_defense(
    source: StrategyResult,
    trace: pd.DataFrame,
    *,
    cash_symbol: str,
) -> tuple[pd.DataFrame, pd.Series]:
    """Override only falling-MA200 executed state-0 sessions with 50% cash."""
    daily = source.daily
    weights = _source_weights(source)
    weights[cash_symbol] = 0.0
    falling_at_open = trace["ma200_falling_at_open"].reindex(weights.index).fillna(False)
    eligible = daily["position_state"].astype(int).eq(0) & falling_at_open.astype(bool)

    weights.loc[eligible, "QQQI"] = DEFENSIVE_EQUITY_WEIGHT
    weights.loc[eligible, "QQQ"] = 0.0
    weights.loc[eligible, "TQQQ"] = 0.0
    weights.loc[eligible, cash_symbol] = DEFENSIVE_CASH_WEIGHT

    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("MA200 defensive weights must sum to one")
    if bool((weights < -1e-12).any().any()):
        raise AssertionError("MA200 defensive weights cannot be negative")

    non_state0 = daily["position_state"].astype(int).ne(0)
    original = _source_weights(source)
    if not np.allclose(
        weights.loc[non_state0, ["QQQI", "QQQ", "TQQQ"]],
        original.loc[non_state0, ["QQQI", "QQQ", "TQQQ"]],
    ):
        raise AssertionError("MA200 defense changed formal state 1/2 allocations")
    if bool(weights.loc[non_state0, cash_symbol].gt(0.0).any()):
        raise AssertionError("cash defense appeared outside formal state 0")
    return weights, eligible.astype(bool)


def run_ma200_defensive_backtest(
    source: StrategyResult,
    bars: Mapping[str, pd.DataFrame],
    *,
    cash_symbol: str,
    strategy_key: str,
) -> StrategyResult:
    """Apply the frozen falling-MA200 state-0 defense to one source result."""
    daily = source.daily.copy()
    trace = build_ma200_trend_trace(daily)
    weights, active = apply_ma200_state0_defense(source, trace, cash_symbol=cash_symbol)
    daily = daily.join(trace)
    daily["ma200_state0_defense_active"] = active
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
    active_dates = daily.index[daily["ma200_state0_defense_active"].fillna(False)]
    year_counts = pd.Series(active_dates.year).value_counts().sort_index()
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(int(changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "ma200_guard_sessions": int(len(active_dates)),
            "ma200_guard_years": int(len(year_counts)),
            "largest_guard_year_share": (
                float(year_counts.max() / year_counts.sum()) if len(year_counts) else 1.0
            ),
        }
    )
    trade_columns = [
        "position_state",
        "ma200",
        "ma200_falling_at_open",
        "ma200_state0_defense_active",
        *[f"weight_{asset}" for asset in weights.columns],
        "turnover_units",
        "transaction_cost",
    ]
    trades = daily.loc[changes, trade_columns].reset_index(names="date")
    return StrategyResult(strategy_key, daily, trades, metrics)


def run_ma200_state0_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    fear_greed: pd.DataFrame,
    *,
    cash_symbol: str,
) -> tuple[pd.DataFrame, dict[str, StrategyResult], dict[str, Any]]:
    """Run v4.2, v4.27, MA200 guard and the frozen joint candidate."""
    _, base_results = run_panic_repair_comparison(bars, bridge_contract, fear_greed)
    baseline = base_results[BASELINE]
    panic = base_results[PANIC]
    for result in (baseline, panic):
        result.metrics.setdefault("ma200_guard_sessions", 0)
        result.metrics.setdefault("ma200_guard_years", 0)
        result.metrics.setdefault("largest_guard_year_share", 0.0)
    guard = run_ma200_defensive_backtest(
        baseline,
        bars,
        cash_symbol=cash_symbol,
        strategy_key=GUARD,
    )
    joint = run_ma200_defensive_backtest(
        panic,
        bars,
        cash_symbol=cash_symbol,
        strategy_key=JOINT,
    )
    results = {BASELINE: baseline, PANIC: panic, GUARD: guard, JOINT: joint}
    same_trace = all(
        result.daily["position_state"].equals(baseline.daily["position_state"])
        for result in results.values()
    )
    if not same_trace:
        raise AssertionError("v4.31 changed the formal v4.2 state trace")
    headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    diagnostics = {
        "same_formal_state_trace": True,
        "cash_symbol": cash_symbol,
        "guard_sessions": int(guard.metrics["ma200_guard_sessions"]),
        "guard_years": int(guard.metrics["ma200_guard_years"]),
        "largest_guard_year_share": float(guard.metrics["largest_guard_year_share"]),
        "joint_guard_sessions": int(joint.metrics["ma200_guard_sessions"]),
    }
    return headline, results, diagnostics
