"""Runtime composition for the frozen VIX-aware rotation experiment.

This module reuses the MA20-derived columns produced by the base rotation frame,
then evaluates two matched challengers:

- price-repair v2: revised shock/recovery logic without VIX gates;
- VIX v2: the same price logic plus VIX easing, normalization and stress gates.

The matched ablation prevents improvements from the revised price logic or
partial leverage from being incorrectly attributed to VIX.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from src.research.etf_rotation_experiment import (
    RotationConfig,
    StrategyResult,
    _return_metrics,
    prepare_rotation_data,
    run_buy_and_hold,
    run_rotation_backtest,
)
from src.research.vix_rotation_experiment import (
    STATE_TO_LABEL,
    VIX_SYMBOL,
    VixRotationConfig,
    _normalise_close,
    build_vix_features,
    generate_vix_decision_states,
)


def prepare_vix_rotation_runtime_data(
    bars: Mapping[str, pd.DataFrame], config: VixRotationConfig
) -> pd.DataFrame:
    """Align tradable returns, QQQ repair features and VIX states."""

    required = {"QQQI", "QQQ", "TQQQ", VIX_SYMBOL}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    base_config = RotationConfig(
        ma_long=config.ma_long,
        ma_short=config.ma_short,
        buffer=config.ma_long_buffer,
        n_rise=config.ma_rise_sessions,
        n_fall=config.ma_rise_sessions,
        n_exit_short=config.exit_below_ma_short_sessions,
        high_window=252,
        bollinger_window=config.ma_short,
        transaction_cost_bps_per_leg=config.transaction_cost_bps_per_turnover_unit,
        annual_risk_free_rate=config.annual_risk_free_rate,
        charge_initial_entry=config.charge_initial_entry,
    )
    prepared = prepare_rotation_data(
        {symbol: bars[symbol] for symbol in ("QQQI", "QQQ", "TQQQ")},
        base_config,
    )
    qqq_close = _normalise_close(bars["QQQ"], "QQQ")
    price = pd.DataFrame(index=qqq_close.index)
    price["ma_medium"] = qqq_close.rolling(
        config.ma_medium, min_periods=config.ma_medium
    ).mean()
    price["rolling_high_shock"] = qqq_close.rolling(
        config.shock_lookback_sessions,
        min_periods=config.shock_lookback_sessions,
    ).max()
    price["shock_drawdown_now"] = qqq_close / price["rolling_high_shock"] - 1.0
    price["shock_memory"] = (
        price["shock_drawdown_now"]
        .rolling(
            config.shock_memory_sessions,
            min_periods=config.shock_memory_sessions,
        )
        .min()
        .le(-config.shock_drawdown)
    )
    price["breakout_early"] = qqq_close.gt(
        qqq_close.rolling(
            config.early_breakout_sessions,
            min_periods=config.early_breakout_sessions,
        )
        .max()
        .shift(1)
    )
    price["breakout_confirm"] = qqq_close.gt(
        qqq_close.rolling(
            config.confirmation_breakout_sessions,
            min_periods=config.confirmation_breakout_sessions,
        )
        .max()
        .shift(1)
    )
    base_short_rising = prepared["ma_short_rising"].reindex(qqq_close.index).fillna(False)
    price["early_repair"] = (
        price["breakout_early"]
        | (qqq_close.gt(prepared["ma_short"].reindex(qqq_close.index)) & base_short_rising)
    ).fillna(False)
    price["medium_repair"] = qqq_close.gt(price["ma_medium"]).fillna(False)
    price["secondary_confirmation"] = (
        price["breakout_confirm"] | base_short_rising
    ).fillna(False)
    price["long_break"] = qqq_close.lt(
        prepared["ma_long"].reindex(qqq_close.index) * (1.0 - config.ma_long_buffer)
    ).fillna(False)
    price["stress_price_failure"] = qqq_close.lt(
        prepared["ma_short"].reindex(qqq_close.index)
    ).fillna(False)

    vix = build_vix_features(bars[VIX_SYMBOL], config)
    out = prepared.join(price, how="left").join(vix, how="left")
    feature_columns = [
        "shock_memory",
        "breakout_early",
        "breakout_confirm",
        "early_repair",
        "medium_repair",
        "secondary_confirmation",
        "long_break",
        "stress_price_failure",
        "vix_falling",
        "vix_stress",
        "vix_easing",
        "vix_normalized",
    ]
    for column in feature_columns:
        out[column] = out[column].fillna(False).astype(bool)
    out["vix_regime"] = out["vix_regime"].fillna("unavailable")
    required_numeric = ["vix_close", "vix_q_stress", "vix_q_normal", "ma_medium"]
    out = out.dropna(subset=required_numeric).copy()
    if len(out) < 40:
        raise ValueError("VIX-aware common sample is too short")
    return out


def generate_price_repair_decision_states(prepared: pd.DataFrame) -> pd.DataFrame:
    """Matched price-only ablation using the same repair stages and risk budget."""

    state = 0
    states: list[int] = []
    reasons: list[str] = []
    for row in prepared.itertuples():
        next_state = state
        reason = "hold"
        if bool(row.long_break):
            next_state = 0
            reason = "defensive_ma200_break"
        elif state == 0:
            if bool(row.shock_memory) and bool(row.early_repair):
                next_state = 1
                reason = "enter_qqq_early_price_repair"
        elif state == 1:
            leverage_ready = (
                bool(row.shock_memory)
                and bool(row.medium_repair)
                and bool(row.secondary_confirmation)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_ma50_confirmation"
        else:
            if bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_ma20"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons},
        index=prepared.index,
    )


def _weights_for_state(state: pd.Series, config: VixRotationConfig) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=state.index, columns=["QQQI", "QQQ", "TQQQ"])
    weights.loc[state.eq(0), "QQQI"] = 1.0
    weights.loc[state.eq(1), "QQQ"] = 1.0
    leveraged = state.eq(2)
    weights.loc[leveraged, "QQQ"] = 1.0 - config.leveraged_tqqq_weight
    weights.loc[leveraged, "TQQQ"] = config.leveraged_tqqq_weight
    return weights


def _run_weighted_state_backtest(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
    decisions: pd.DataFrame,
    *,
    strategy_key: str,
    display_name: str,
) -> StrategyResult:
    """Execute a supplied close-decision trace at the next open."""

    daily = prepared.join(decisions)
    daily["position_state"] = daily["decision_state"].shift(1).fillna(0).astype(int)
    daily["position_label"] = daily["position_state"].map(STATE_TO_LABEL)
    daily["executed_reason"] = daily["decision_reason"].shift(1).fillna("initial_entry")
    weights = _weights_for_state(daily["position_state"], config)
    for symbol in ("QQQI", "QQQ", "TQQQ"):
        daily[f"weight_{symbol}"] = weights[symbol]
    daily["gross_return"] = sum(
        daily[f"weight_{symbol}"] * daily[f"{symbol}_next_open_return"]
        for symbol in ("QQQI", "QQQ", "TQQQ")
    )
    turnover = weights.diff().abs().sum(axis=1)
    if config.charge_initial_entry and not turnover.empty:
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    else:
        turnover.iloc[0] = 0.0
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = (
        turnover * config.transaction_cost_bps_per_turnover_unit / 10_000.0
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(
        daily["net_return"], annual_risk_free_rate=config.annual_risk_free_rate
    )
    switches = daily["position_state"].ne(daily["position_state"].shift()).sum() - 1
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(switches, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "pct_time_qqqi": float(daily["position_state"].eq(0).mean()),
            "pct_time_qqq": float(daily["position_state"].eq(1).mean()),
            "pct_time_partial_tqqq": float(daily["position_state"].eq(2).mean()),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
        }
    )
    trade_mask = daily["position_state"].ne(daily["position_state"].shift())
    trade_columns = [
        "executed_reason",
        "position_state",
        "position_label",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "turnover_units",
        "transaction_cost",
        "vix_close",
        "vix_regime",
    ]
    trades = daily.loc[trade_mask, trade_columns].reset_index(names="date")
    return StrategyResult(display_name, daily, trades, metrics)


def state_reachability(result: StrategyResult) -> dict[str, Any]:
    """Report whether the matched challenger exercised all intended states."""

    counts = result.daily["position_state"].value_counts().reindex([0, 1, 2], fill_value=0)
    return {
        "state_counts": {STATE_TO_LABEL[state]: int(counts.loc[state]) for state in (0, 1, 2)},
        "all_states_reached": bool((counts > 0).all()),
    }


def run_vix_runtime_comparison(
    bars: Mapping[str, pd.DataFrame], config: VixRotationConfig
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame]:
    """Compare VIX v2 with baselines, price v1 and a matched price-only v2."""

    prepared = prepare_vix_rotation_runtime_data(bars, config)
    base_config = RotationConfig(
        ma_long=config.ma_long,
        ma_short=config.ma_short,
        buffer=config.ma_long_buffer,
        n_rise=config.ma_rise_sessions,
        n_exit_short=config.exit_below_ma_short_sessions,
        high_window=252,
        bollinger_window=config.ma_short,
        transaction_cost_bps_per_leg=config.transaction_cost_bps_per_turnover_unit,
        annual_risk_free_rate=config.annual_risk_free_rate,
        charge_initial_entry=config.charge_initial_entry,
    )
    results: dict[str, StrategyResult] = {}
    for symbol in ("QQQI", "QQQ", "TQQQ"):
        results[f"buy_hold_{symbol}"] = run_buy_and_hold(prepared, base_config, symbol=symbol)

    price_v1 = run_rotation_backtest(prepared, base_config, version="B")
    price_v1.metrics["strategy"] = "rotation_price_v1"
    results["rotation_price_v1"] = price_v1

    price_decisions = generate_price_repair_decision_states(prepared)
    results["rotation_price_repair_v2"] = _run_weighted_state_backtest(
        prepared,
        config,
        price_decisions,
        strategy_key="rotation_price_repair_v2",
        display_name="Rotation price-repair v2",
    )
    vix_decisions = generate_vix_decision_states(prepared, config)
    results["rotation_vix_v2"] = _run_weighted_state_backtest(
        prepared,
        config,
        vix_decisions,
        strategy_key="rotation_vix_v2",
        display_name="Rotation VIX v2",
    )

    metrics = pd.DataFrame([result.metrics for result in results.values()]).set_index("strategy")
    return metrics.sort_index(), results, prepared
