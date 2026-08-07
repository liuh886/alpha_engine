"""Frozen panic-repair risk-budget overlay for the QQQ v4.2 family.

A deep panic event only arms an opportunity. Existing v4.2 repair semantics
decide when the opportunity becomes active. The overlay never changes the
formal v4.2 decision state and never changes formal state-2 weights.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

PANIC_RSI_THRESHOLD = 30.0
PANIC_FEAR_GREED_THRESHOLD = 10.0
TQQQ_BOOST = 0.25
TRANSACTION_COST_BPS_PER_TURNOVER_UNIT = 10.0


def _normalise_fear_greed(fear_greed: pd.DataFrame) -> pd.DataFrame:
    required = {"fear_greed_score"}
    missing = sorted(required - set(fear_greed.columns))
    if missing:
        raise ValueError(f"fear_greed missing columns: {missing}")
    out = fear_greed.copy()
    out.index = pd.to_datetime(out.index, errors="raise").tz_localize(None).normalize()
    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
    if out.index.has_duplicates:
        raise ValueError("fear_greed index must be unique")
    out["fear_greed_score"] = pd.to_numeric(out["fear_greed_score"], errors="coerce")
    invalid = out["fear_greed_score"].dropna().loc[
        lambda value: (value < 0.0) | (value > 100.0)
    ]
    if not invalid.empty:
        raise ValueError("fear_greed score must be in [0, 100]")
    return out


def build_panic_repair_trace(
    daily: pd.DataFrame,
    fear_greed: pd.DataFrame,
) -> pd.DataFrame:
    """Build a close-time arm/repair trace and shift it once for execution."""
    required = {
        "rsi_14",
        "decision_state",
        "early_repair",
        "stress_price_failure",
        "vix_easing",
        "vix_normalized",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"daily trace missing required columns: {missing}")
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")

    sentiment = _normalise_fear_greed(fear_greed)
    score = sentiment["fear_greed_score"].reindex(daily.index)
    rsi = pd.to_numeric(daily["rsi_14"], errors="coerce")
    panic = (
        rsi.lt(PANIC_RSI_THRESHOLD)
        & score.lt(PANIC_FEAR_GREED_THRESHOLD)
        & rsi.notna()
        & score.notna()
    )
    panic_start = panic & ~panic.shift(1, fill_value=False)
    repair_ready = (
        daily["early_repair"].fillna(False).astype(bool)
        & ~daily["stress_price_failure"].fillna(True).astype(bool)
        & (
            daily["vix_easing"].fillna(False).astype(bool)
            | daily["vix_normalized"].fillna(False).astype(bool)
        )
    )

    armed = False
    active = False
    event_number = 0
    current_event: int | None = None
    armed_rows: list[bool] = []
    active_rows: list[bool] = []
    event_rows: list[int | None] = []
    reasons: list[str] = []

    for panic_now, repair_now, failure, state in zip(
        panic_start,
        repair_ready,
        daily["stress_price_failure"].fillna(True).astype(bool),
        daily["decision_state"].astype(int),
        strict=True,
    ):
        reason = "hold_active" if active else ("hold_armed" if armed else "hold_idle")

        if bool(panic_now):
            event_number += 1
            current_event = event_number
            armed = True
            active = False
            reason = "panic_arms"
        elif int(state) == 2:
            if active:
                reason = "formal_state2_replaces_boost"
            elif armed:
                reason = "formal_state2_cancels_arm"
            active = False
            armed = False
            current_event = None
        elif active and bool(failure):
            active = False
            current_event = None
            reason = "repair_failure_exits_boost"
        elif armed and bool(repair_now) and int(state) in (0, 1):
            armed = False
            active = True
            reason = "repair_activates_boost"

        armed_rows.append(armed)
        active_rows.append(active)
        event_rows.append(current_event)
        reasons.append(reason)

    trace = pd.DataFrame(
        {
            "fear_greed_score": score,
            "panic_condition_at_close": panic.astype(bool),
            "panic_start_at_close": panic_start.astype(bool),
            "repair_ready_at_close": repair_ready.astype(bool),
            "panic_repair_armed_at_close": pd.Series(
                armed_rows, index=daily.index, dtype=bool
            ),
            "panic_repair_active_at_close": pd.Series(
                active_rows, index=daily.index, dtype=bool
            ),
            "panic_repair_event_id": pd.Series(
                event_rows, index=daily.index, dtype="Int64"
            ),
            "panic_repair_reason_at_close": reasons,
        },
        index=daily.index,
    )
    trace["panic_repair_active_at_open"] = (
        trace["panic_repair_active_at_close"].shift(1, fill_value=False).astype(bool)
    )
    trace["panic_repair_reason_at_open"] = (
        trace["panic_repair_reason_at_close"].shift(1).fillna("initial_entry")
    )
    return trace


def panic_repair_weights(
    daily: pd.DataFrame,
    trace: pd.DataFrame,
) -> pd.DataFrame:
    """Add one 25pp TQQQ risk-budget step in executed formal states 0/1."""
    required = {
        "position_state",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"daily trace missing weight columns: {missing}")

    assets = ["QQQI", "QQQ", "TQQQ"]
    weights = daily[[f"weight_{asset}" for asset in assets]].rename(
        columns={f"weight_{asset}": asset for asset in assets}
    ).astype(float).copy()

    active = (
        trace["panic_repair_active_at_open"].reindex(weights.index).fillna(False)
        & daily["position_state"].astype(int).isin([0, 1])
    )
    funding_assets = [asset for asset in assets if asset != "TQQQ"]
    funding = weights[funding_assets].sum(axis=1)
    if bool((funding.loc[active] < TQQQ_BOOST - 1e-12).any()):
        raise AssertionError("insufficient non-TQQQ sleeve for panic repair boost")

    for date in weights.index[active]:
        available = float(funding.loc[date])
        scale = (available - TQQQ_BOOST) / available
        weights.loc[date, funding_assets] *= scale
        weights.loc[date, "TQQQ"] += TQQQ_BOOST

    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("panic repair weights must sum to one")
    if bool((weights < -1e-12).any().any()):
        raise AssertionError("panic repair weights cannot be negative")

    formal_state_two = daily["position_state"].astype(int).eq(2)
    original = daily.loc[
        formal_state_two, [f"weight_{asset}" for asset in assets]
    ].rename(columns={f"weight_{asset}": asset for asset in assets})
    if bool(formal_state_two.any()) and not np.allclose(
        weights.loc[formal_state_two, assets],
        original[assets],
    ):
        raise AssertionError("formal state-2 weights changed")
    return weights


def run_panic_repair_backtest(
    source: Any,
    fear_greed: pd.DataFrame,
) -> Any:
    """Run the frozen overlay against one already-built v4.2 StrategyResult."""
    from src.research.etf_rotation_experiment import StrategyResult, _return_metrics

    daily = source.daily.copy()
    trace = build_panic_repair_trace(daily, fear_greed)
    daily = daily.join(trace)
    weights = panic_repair_weights(daily, trace)
    assets = list(weights.columns)
    for asset in assets:
        daily[f"weight_{asset}"] = weights[asset]

    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in assets
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
    metrics.update(
        {
            "strategy": "v4_27_panic_repair_boost",
            "switch_count": int(max(int(changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "panic_cluster_count": int(daily["panic_start_at_close"].sum()),
            "boost_sessions": int(daily["panic_repair_active_at_open"].sum()),
        }
    )
    trade_columns = [
        "position_state",
        "panic_start_at_close",
        "panic_repair_active_at_open",
        "panic_repair_reason_at_open",
        "fear_greed_score",
        "rsi_14",
        *[f"weight_{asset}" for asset in assets],
        "turnover_units",
        "transaction_cost",
    ]
    trades = daily.loc[changes, trade_columns].reset_index(names="date")
    return StrategyResult(
        "v4_27_panic_repair_boost",
        daily,
        trades,
        metrics,
    )


def run_panic_repair_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    fear_greed: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the unchanged v4.2 bridge baseline and one frozen challenger."""
    from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
    from src.research.v4_2_rsi_vix_sgov_experiment import wilder_rsi
    from src.research.vix_rotation_experiment import _normalise_close
    from src.research.vxn_bridge_allocation_experiment import (
        run_bridge_allocation_comparison,
    )

    _, bridge_results, _, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    baseline_source = bridge_results["rotation_vxn_bridge_v4_2_50_50"]
    daily = baseline_source.daily.copy()

    qqq_close = _normalise_close(bars["QQQ"], "QQQ")
    daily["rsi_14"] = wilder_rsi(qqq_close, period=14).reindex(daily.index)
    daily = daily.loc[daily["rsi_14"].notna()].copy()

    baseline_metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    baseline_metrics.update(
        {
            "strategy": "current_v4_2",
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
        }
    )
    baseline = StrategyResult(
        "current_v4_2",
        daily,
        baseline_source.trades,
        baseline_metrics,
    )
    candidate = run_panic_repair_backtest(baseline, fear_greed)
    results = {"current_v4_2": baseline, "v4_27_panic_repair_boost": candidate}
    headline = pd.DataFrame(
        {key: result.metrics for key, result in results.items()}
    ).T
    return headline, results
