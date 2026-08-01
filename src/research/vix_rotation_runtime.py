"""Runtime composition for the frozen VIX-aware rotation experiment.

This module deliberately reuses the MA20-derived columns produced by the base
rotation frame. It avoids duplicate-column joins and keeps one source of truth
for the short moving-average calculations.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from src.research.etf_rotation_experiment import (
    RotationConfig,
    StrategyResult,
    prepare_rotation_data,
    run_buy_and_hold,
    run_rotation_backtest,
)
from src.research.vix_rotation_experiment import (
    VIX_SYMBOL,
    VixRotationConfig,
    _normalise_close,
    build_vix_features,
    run_vix_rotation_backtest,
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


def run_vix_runtime_comparison(
    bars: Mapping[str, pd.DataFrame], config: VixRotationConfig
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame]:
    """Compare VIX v2 with QQQ, QQQI, TQQQ and price-only v1."""

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
    results["rotation_price_v1"] = run_rotation_backtest(prepared, base_config, version="B")
    results["rotation_vix_v2"] = run_vix_rotation_backtest(prepared, config)
    metrics = pd.DataFrame([result.metrics for result in results.values()]).set_index("strategy")
    return metrics.sort_index(), results, prepared
