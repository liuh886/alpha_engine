"""Long-history structural validation for the frozen v4.1 attack layer.

This study deliberately excludes QQQI because its live history begins in 2024.
Both defensive and ordinary attack states are economically mapped to QQQ; only
state 2 receives the frozen 25% QQQ / 75% TQQQ allocation. The signal rules are
not changed or tuned.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.breadth_vxn_rotation_experiment import VXN_SYMBOL, build_vxn_features
from src.research.etf_rotation_experiment import (
    RotationConfig,
    StrategyResult,
    _normalise_bars,
    _return_metrics,
    build_signal_frame,
)
from src.research.vix_rotation_experiment import (
    VIX_SYMBOL,
    VixRotationConfig,
    build_vix_features,
    config_from_contract,
    generate_vix_decision_states,
)
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
)

ATTACK_STATE_TO_LABEL = {0: "qqq", 1: "partial_leverage"}


def prepare_attack_layer_data(
    bars: Mapping[str, pd.DataFrame], contract: Mapping[str, Any]
) -> tuple[pd.DataFrame, VixRotationConfig]:
    """Build the longest reliable QQQ/TQQQ/VIX/VXN common sample."""

    required = {"QQQ", "TQQQ", VIX_SYMBOL, VXN_SYMBOL}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    config = config_from_contract(contract)
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
    normalised = {
        symbol: _normalise_bars(bars[symbol], symbol) for symbol in ("QQQ", "TQQQ")
    }
    common_index = normalised["QQQ"].index.intersection(normalised["TQQQ"].index)
    common_index = common_index.sort_values()
    if common_index.empty:
        raise ValueError("QQQ and TQQQ have no common sessions")

    signal = build_signal_frame(bars["QQQ"], base_config)
    qqq_close = normalised["QQQ"]["close"]
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
    short_rising = signal["ma_short_rising"].reindex(qqq_close.index).fillna(False)
    price["early_repair"] = (
        price["breakout_early"]
        | (qqq_close.gt(signal["ma_short"].reindex(qqq_close.index)) & short_rising)
    ).fillna(False)
    price["medium_repair"] = qqq_close.gt(price["ma_medium"]).fillna(False)
    price["secondary_confirmation"] = (
        price["breakout_confirm"] | short_rising
    ).fillna(False)
    price["long_break"] = qqq_close.lt(
        signal["ma_long"].reindex(qqq_close.index) * (1.0 - config.ma_long_buffer)
    ).fillna(False)
    price["stress_price_failure"] = qqq_close.lt(
        signal["ma_short"].reindex(qqq_close.index)
    ).fillna(False)

    frame = signal.reindex(common_index).copy()
    for symbol in ("QQQ", "TQQQ"):
        frame[f"{symbol}_open"] = normalised[symbol].reindex(common_index)["open"]
        frame[f"{symbol}_close"] = normalised[symbol].reindex(common_index)["close"]
        frame[f"{symbol}_next_open_return"] = (
            frame[f"{symbol}_open"].shift(-1) / frame[f"{symbol}_open"] - 1.0
        )
    frame = frame.join(price, how="left")
    frame = frame.join(build_vix_features(bars[VIX_SYMBOL], config), how="left")
    frame = frame.join(build_vxn_features(bars[VXN_SYMBOL], config), how="left")

    bool_columns = [
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
        "vxn_falling",
        "vxn_stress",
        "vxn_easing",
        "vxn_normalized",
    ]
    for column in bool_columns:
        frame[column] = frame[column].fillna(False).astype(bool)
    frame["vix_regime"] = frame["vix_regime"].fillna("unavailable")
    frame["vxn_regime"] = frame["vxn_regime"].fillna("unavailable")
    required_numeric = [
        "ma_long",
        "ma_short",
        "ma_medium",
        "vix_close",
        "vix_q_stress",
        "vix_q_normal",
        "vxn_close",
        "vxn_q_stress",
        "vxn_q_normal",
    ]
    frame = frame.dropna(subset=required_numeric).copy()
    if len(frame) < 756:
        raise ValueError("long-history attack-layer sample is shorter than three years")
    return frame, config


def _run_attack_backtest(
    prepared: pd.DataFrame,
    decisions: pd.DataFrame,
    config: VixRotationConfig,
    *,
    strategy_key: str,
    display_name: str,
) -> StrategyResult:
    """Map source states 0/1 to QQQ and source state 2 to 25% QQQ/75% TQQQ."""

    daily = prepared.join(decisions)
    daily["source_position_state"] = (
        daily["decision_state"].shift(1).fillna(0).astype(int)
    )
    daily["position_state"] = daily["source_position_state"].eq(2).astype(int)
    daily["position_label"] = daily["position_state"].map(ATTACK_STATE_TO_LABEL)
    daily["executed_reason"] = daily["decision_reason"].shift(1).fillna("initial_entry")
    leveraged = daily["position_state"].eq(1)
    daily["weight_QQQ"] = 1.0
    daily.loc[leveraged, "weight_QQQ"] = 1.0 - config.leveraged_tqqq_weight
    daily["weight_TQQQ"] = 0.0
    daily.loc[leveraged, "weight_TQQQ"] = config.leveraged_tqqq_weight
    daily["gross_return"] = (
        daily["weight_QQQ"] * daily["QQQ_next_open_return"]
        + daily["weight_TQQQ"] * daily["TQQQ_next_open_return"]
    )
    weights = daily[["weight_QQQ", "weight_TQQQ"]]
    turnover = weights.diff().abs().sum(axis=1)
    if config.charge_initial_entry and not turnover.empty:
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    elif not turnover.empty:
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
            "pct_time_qqq": float(daily["position_state"].eq(0).mean()),
            "pct_time_partial_tqqq": float(daily["position_state"].eq(1).mean()),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
        }
    )
    trade_mask = daily["position_state"].ne(daily["position_state"].shift())
    trade_columns = [
        "executed_reason",
        "source_position_state",
        "position_state",
        "position_label",
        "weight_QQQ",
        "weight_TQQQ",
        "turnover_units",
        "transaction_cost",
        "vix_close",
        "vxn_close",
        "vix_regime",
        "vxn_regime",
    ]
    trades = daily.loc[trade_mask, trade_columns].reset_index(names="date")
    return StrategyResult(display_name, daily, trades, metrics)


def _constant_decisions(index: pd.Index, state: int, reason: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"decision_state": state, "decision_reason": reason}, index=index
    )


def _leverage_capture(result: StrategyResult) -> dict[str, float | int]:
    values = result.daily.loc[result.daily["position_state"].eq(1), "net_return"].dropna()
    if values.empty:
        return {
            "sessions": 0,
            "cumulative_net_return": 0.0,
            "mean_daily_net_return": 0.0,
            "positive_session_rate": 0.0,
            "worst_daily_net_return": 0.0,
        }
    return {
        "sessions": int(len(values)),
        "cumulative_net_return": float((1.0 + values).prod() - 1.0),
        "mean_daily_net_return": float(values.mean()),
        "positive_session_rate": float(values.gt(0).mean()),
        "worst_daily_net_return": float(values.min()),
    }


def leverage_episodes(result: StrategyResult) -> pd.DataFrame:
    """Summarise contiguous leveraged holdings without tuning their boundaries."""

    daily = result.daily
    mask = daily["position_state"].eq(1)
    groups = mask.ne(mask.shift()).cumsum()
    rows: list[dict[str, Any]] = []
    for _, group in daily.loc[mask].groupby(groups.loc[mask]):
        returns = group["net_return"].dropna()
        rows.append(
            {
                "strategy": str(result.metrics["strategy"]),
                "start_date": group.index.min(),
                "end_date": group.index.max(),
                "sessions": int(len(group)),
                "cumulative_net_return": float((1.0 + returns).prod() - 1.0),
                "worst_daily_net_return": float(returns.min()),
                "positive_session_rate": float(returns.gt(0).mean()),
            }
        )
    return pd.DataFrame(rows)


def blocked_vxn_entries(
    prepared: pd.DataFrame,
    baseline_decisions: pd.DataFrame,
    overlay_decisions: pd.DataFrame,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Report every baseline leverage entry vetoed by VXN and later TQQQ outcomes."""

    previous = baseline_decisions["decision_state"].shift(1).fillna(0).astype(int)
    mask = (
        baseline_decisions["decision_state"].eq(2)
        & previous.ne(2)
        & overlay_decisions["decision_state"].ne(2)
    )
    rows: list[dict[str, Any]] = []
    for location in np.flatnonzero(mask.to_numpy(dtype=bool)):
        row: dict[str, Any] = {
            "signal_date": prepared.index[int(location)],
            "vix_close": float(prepared.iloc[int(location)]["vix_close"]),
            "vxn_close": float(prepared.iloc[int(location)]["vxn_close"]),
            "vxn_stress": bool(prepared.iloc[int(location)]["vxn_stress"]),
        }
        for horizon in horizons:
            window = prepared.iloc[int(location) + 1 : int(location) + 1 + int(horizon)]
            values = window["TQQQ_next_open_return"].dropna()
            row[f"TQQQ_return_{int(horizon)}d"] = (
                float((1.0 + values).prod() - 1.0)
                if len(values) == int(horizon)
                else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def period_metrics(
    results: Mapping[str, StrategyResult], periods: Mapping[str, Mapping[str, str]]
) -> pd.DataFrame:
    """Evaluate predeclared chronological and named stress windows."""

    rows: list[dict[str, Any]] = []
    for period_name, bounds in periods.items():
        start = pd.Timestamp(bounds["start"])
        end = pd.Timestamp(bounds["end"])
        for key, result in results.items():
            values = result.daily.loc[start:end, "net_return"]
            metrics = _return_metrics(values)
            rows.append({"period": period_name, "strategy": key, **metrics})
    return pd.DataFrame(rows)


def rolling_metrics(
    results: Mapping[str, StrategyResult], windows: Sequence[int]
) -> pd.DataFrame:
    """Produce rolling risk-adjusted metrics for fixed one- and three-year windows."""

    rows: list[dict[str, Any]] = []
    for key, result in results.items():
        values = result.daily["net_return"].dropna()
        for window in windows:
            size = int(window)
            if size <= 1:
                raise ValueError("rolling windows must exceed one session")
            for end_location in range(size - 1, len(values)):
                sample = values.iloc[end_location - size + 1 : end_location + 1]
                metrics = _return_metrics(sample)
                rows.append(
                    {
                        "date": sample.index[-1],
                        "strategy": key,
                        "window_sessions": size,
                        "cagr": metrics["cagr"],
                        "annual_volatility": metrics["annual_volatility"],
                        "sharpe": metrics["sharpe"],
                        "max_drawdown": metrics["max_drawdown"],
                        "calmar": metrics["calmar"],
                    }
                )
    return pd.DataFrame(rows)


def run_attack_layer_comparison(
    bars: Mapping[str, pd.DataFrame], contract: Mapping[str, Any]
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
]:
    """Run frozen v4.1 attack-layer comparisons and structural diagnostics."""

    prepared, config = prepare_attack_layer_data(bars, contract)
    vix_decisions = generate_vix_decision_states(prepared, config)
    vxn_decisions = generate_vxn_leverage_veto_states(prepared, config)
    results = {
        "buy_hold_QQQ": _run_attack_backtest(
            prepared,
            _constant_decisions(prepared.index, 0, "static_qqq"),
            config,
            strategy_key="buy_hold_QQQ",
            display_name="QQQ buy and hold",
        ),
        "static_qqq25_tqqq75": _run_attack_backtest(
            prepared,
            _constant_decisions(prepared.index, 2, "static_qqq25_tqqq75"),
            config,
            strategy_key="static_qqq25_tqqq75",
            display_name="Static 25% QQQ / 75% TQQQ",
        ),
        "attack_vix_v3_75": _run_attack_backtest(
            prepared,
            vix_decisions,
            config,
            strategy_key="attack_vix_v3_75",
            display_name="Frozen VIX v3 attack layer",
        ),
        "attack_vxn_v4_1_75": _run_attack_backtest(
            prepared,
            vxn_decisions,
            config,
            strategy_key="attack_vxn_v4_1_75",
            display_name="Frozen v4.1 VXN-veto attack layer",
        ),
    }
    metrics = pd.DataFrame(
        [dict(result.metrics) for result in results.values()]
    ).set_index("strategy")

    validation = contract["validation"]
    periods = period_metrics(results, validation["chronological_periods"])
    regimes = period_metrics(results, validation["regime_windows"])
    rolling = rolling_metrics(results, validation["rolling_windows_sessions"])
    episodes = pd.concat(
        [
            leverage_episodes(results["attack_vix_v3_75"]),
            leverage_episodes(results["attack_vxn_v4_1_75"]),
        ],
        ignore_index=True,
    )
    blocked = blocked_vxn_entries(
        prepared,
        vix_decisions,
        vxn_decisions,
        validation["event_horizons"],
    )

    cost_rows: list[dict[str, Any]] = []
    for cost_bps in validation["cost_sensitivity_bps"]:
        cost_config = replace(
            config, transaction_cost_bps_per_turnover_unit=float(cost_bps)
        )
        for key, decisions in (
            ("attack_vix_v3_75", vix_decisions),
            ("attack_vxn_v4_1_75", vxn_decisions),
        ):
            result = _run_attack_backtest(
                prepared,
                decisions,
                cost_config,
                strategy_key=key,
                display_name=key,
            )
            cost_rows.append(
                {
                    "cost_bps_per_turnover_unit": float(cost_bps),
                    **dict(result.metrics),
                }
            )
    cost_sensitivity = pd.DataFrame(cost_rows)

    diagnostics: dict[str, Any] = {
        "historical_structural_validation": True,
        "post_result_hypothesis": True,
        "qqqi_excluded": True,
        "state_mapping": {
            "source_state_0": "QQQ",
            "source_state_1": "QQQ",
            "source_state_2": "25% QQQ / 75% TQQQ",
        },
        "leverage_capture": {
            "vix_v3": _leverage_capture(results["attack_vix_v3_75"]),
            "vxn_v4_1": _leverage_capture(results["attack_vxn_v4_1_75"]),
        },
        "blocked_vxn_entry_count": int(len(blocked)),
        "same_price_and_vix_rules": True,
        "no_threshold_search": True,
    }
    tables = {
        "chronological_periods": periods,
        "regime_windows": regimes,
        "rolling_metrics": rolling,
        "leverage_episodes": episodes,
        "blocked_vxn_entries": blocked,
        "cost_sensitivity": cost_sensitivity,
        "vix_decisions": vix_decisions,
        "vxn_decisions": vxn_decisions,
    }
    return metrics.sort_index(), results, prepared, diagnostics, tables
