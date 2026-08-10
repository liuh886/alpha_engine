"""Absolute QQQE breadth as soft 50%/75% TQQQ scaling for frozen v4.1."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.vix_rotation_experiment import VixRotationConfig, _normalise_close
from src.research.vxn_attack_layer_long_history import (
    period_metrics,
    prepare_attack_layer_data,
    rolling_metrics,
)
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
)

BREADTH_SYMBOL = "QQQE"


def build_absolute_breadth_features(
    breadth_bars: pd.DataFrame,
    *,
    ma_window: int = 20,
    momentum_sessions: int = 5,
) -> pd.DataFrame:
    """Build the frozen QQQE absolute-trend confirmation."""

    if ma_window <= 1 or momentum_sessions <= 0:
        raise ValueError("breadth windows must be positive")
    close = _normalise_close(breadth_bars, BREADTH_SYMBOL)
    features = pd.DataFrame(index=close.index)
    features["qqqe_close"] = close
    features["qqqe_ma"] = close.rolling(ma_window, min_periods=ma_window).mean()
    features["qqqe_momentum"] = close.pct_change(momentum_sessions)
    features["qqqe_above_ma"] = close.gt(features["qqqe_ma"])
    features["qqqe_positive_momentum"] = features["qqqe_momentum"].gt(0.0)
    features["absolute_breadth_confirmed"] = (
        features["qqqe_above_ma"] & features["qqqe_positive_momentum"]
    ).fillna(False)
    return features


def _run_scaled_attack_backtest(
    prepared: pd.DataFrame,
    decisions: pd.DataFrame,
    config: VixRotationConfig,
    *,
    strategy_key: str,
    display_name: str,
    weak_tqqq_weight: float,
    confirmed_tqqq_weight: float,
    dynamic_breadth: bool,
) -> StrategyResult:
    """Backtest the same decision trace with either fixed or breadth-scaled weights."""

    for weight in (weak_tqqq_weight, confirmed_tqqq_weight):
        if not 0.0 <= weight <= 1.0:
            raise ValueError("TQQQ weights must be in [0, 1]")
    if weak_tqqq_weight > confirmed_tqqq_weight:
        raise ValueError("weak breadth weight cannot exceed confirmed weight")

    daily = prepared.join(decisions)
    daily["source_position_state"] = daily["decision_state"].shift(1).fillna(0).astype(int)
    daily["position_state"] = daily["source_position_state"].eq(2).astype(int)
    daily["executed_reason"] = daily["decision_reason"].shift(1).fillna("initial_entry")
    daily["executed_breadth_confirmed"] = (
        daily["absolute_breadth_confirmed"].shift(1).fillna(False).astype(bool)
    )
    leveraged = daily["position_state"].eq(1)
    daily["weight_TQQQ"] = 0.0
    if dynamic_breadth:
        daily.loc[leveraged & ~daily["executed_breadth_confirmed"], "weight_TQQQ"] = (
            weak_tqqq_weight
        )
        daily.loc[leveraged & daily["executed_breadth_confirmed"], "weight_TQQQ"] = (
            confirmed_tqqq_weight
        )
    else:
        daily.loc[leveraged, "weight_TQQQ"] = confirmed_tqqq_weight
    daily["weight_QQQ"] = 1.0 - daily["weight_TQQQ"]
    daily["leverage_tier"] = "none"
    daily.loc[leveraged & daily["weight_TQQQ"].eq(weak_tqqq_weight), "leverage_tier"] = "reduced"
    daily.loc[leveraged & daily["weight_TQQQ"].eq(confirmed_tqqq_weight), "leverage_tier"] = "full"

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
    daily["transaction_cost"] = turnover * config.transaction_cost_bps_per_turnover_unit / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(
        daily["net_return"], annual_risk_free_rate=config.annual_risk_free_rate
    )
    state_switches = daily["position_state"].ne(daily["position_state"].shift()).sum() - 1
    weight_changes = daily["weight_TQQQ"].ne(daily["weight_TQQQ"].shift()).sum() - 1
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(state_switches, 0)),
            "weight_change_count": int(max(weight_changes, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "pct_time_qqq": float(daily["position_state"].eq(0).mean()),
            "pct_time_partial_tqqq": float(daily["position_state"].eq(1).mean()),
            "pct_time_reduced_tier": float(daily["leverage_tier"].eq("reduced").mean()),
            "pct_time_full_tier": float(daily["leverage_tier"].eq("full").mean()),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
        }
    )
    trade_mask = weights.ne(weights.shift()).any(axis=1)
    trades = daily.loc[
        trade_mask,
        [
            "executed_reason",
            "position_state",
            "leverage_tier",
            "executed_breadth_confirmed",
            "weight_QQQ",
            "weight_TQQQ",
            "turnover_units",
            "transaction_cost",
            "qqqe_close",
            "qqqe_ma",
            "qqqe_momentum",
        ],
    ].reset_index(names="date")
    return StrategyResult(display_name, daily, trades, metrics)


def tier_contribution(result: StrategyResult) -> pd.DataFrame:
    """Attribute return quality to none, reduced and full leverage tiers."""

    rows: list[dict[str, Any]] = []
    for tier in ("none", "reduced", "full"):
        values = result.daily.loc[result.daily["leverage_tier"].eq(tier), "net_return"]
        rows.append(
            {
                "strategy": str(result.metrics["strategy"]),
                "leverage_tier": tier,
                "sessions": int(len(values)),
                "cumulative_net_return": (
                    float((1.0 + values).prod() - 1.0) if len(values) else 0.0
                ),
                "mean_daily_net_return": float(values.mean()) if len(values) else 0.0,
                "positive_session_rate": (float(values.gt(0).mean()) if len(values) else 0.0),
                "worst_daily_net_return": float(values.min()) if len(values) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def run_absolute_breadth_scaling_comparison(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
]:
    """Compare fixed 75% v4.1 with one 50%/75% absolute-breadth schedule."""

    base_contract = contract["resolved_base_contract"]
    full_prepared, config = prepare_attack_layer_data(bars, base_contract)
    decisions = generate_vxn_leverage_veto_states(full_prepared, config)
    logic = contract["breadth_logic"]
    breadth = build_absolute_breadth_features(
        bars[BREADTH_SYMBOL],
        ma_window=int(logic["ma_window"]),
        momentum_sessions=int(logic["momentum_sessions"]),
    )
    prepared = full_prepared.join(breadth, how="left")
    prepared = prepared.dropna(subset=["qqqe_close", "qqqe_ma", "qqqe_momentum"]).copy()
    prepared["absolute_breadth_confirmed"] = (
        prepared["absolute_breadth_confirmed"].fillna(False).astype(bool)
    )
    decisions = decisions.reindex(prepared.index)
    if decisions.isna().any().any():
        raise ValueError("breadth common window lost frozen decisions")

    portfolio = contract["portfolio"]
    weak_weight = float(portfolio["unconfirmed_tqqq_weight"])
    confirmed_weight = float(portfolio["confirmed_tqqq_weight"])
    baseline = _run_scaled_attack_backtest(
        prepared,
        decisions,
        config,
        strategy_key="attack_vxn_v4_1_fixed_75",
        display_name="Frozen v4.1 fixed 75% TQQQ",
        weak_tqqq_weight=confirmed_weight,
        confirmed_tqqq_weight=confirmed_weight,
        dynamic_breadth=False,
    )
    challenger = _run_scaled_attack_backtest(
        prepared,
        decisions,
        config,
        strategy_key="attack_absolute_breadth_v4_2_soft_50_75",
        display_name="Absolute breadth soft 50%/75% TQQQ",
        weak_tqqq_weight=weak_weight,
        confirmed_tqqq_weight=confirmed_weight,
        dynamic_breadth=True,
    )
    results = {
        "attack_vxn_v4_1_fixed_75": baseline,
        "attack_absolute_breadth_v4_2_soft_50_75": challenger,
    }
    metrics = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )

    validation = contract["validation"]
    periods = period_metrics(results, validation["chronological_periods"])
    regimes = period_metrics(results, validation["regime_windows"])
    rolling = rolling_metrics(results, validation["rolling_windows_sessions"])
    tiers = pd.concat([tier_contribution(result) for result in results.values()])

    changed = pd.DataFrame(
        {
            "baseline_weight_TQQQ": baseline.daily["weight_TQQQ"],
            "challenger_weight_TQQQ": challenger.daily["weight_TQQQ"],
            "breadth_confirmed": challenger.daily["executed_breadth_confirmed"],
            "baseline_return": baseline.daily["net_return"],
            "challenger_return": challenger.daily["net_return"],
        }
    )
    changed = changed[changed["baseline_weight_TQQQ"].ne(changed["challenger_weight_TQQQ"])].copy()
    changed["challenger_minus_baseline"] = changed["challenger_return"] - changed["baseline_return"]
    changed = changed.reset_index(names="date")

    cost_rows: list[dict[str, Any]] = []
    for cost_bps in validation["cost_sensitivity_bps"]:
        cost_config = replace(config, transaction_cost_bps_per_turnover_unit=float(cost_bps))
        for key, dynamic, low in (
            ("attack_vxn_v4_1_fixed_75", False, confirmed_weight),
            ("attack_absolute_breadth_v4_2_soft_50_75", True, weak_weight),
        ):
            result = _run_scaled_attack_backtest(
                prepared,
                decisions,
                cost_config,
                strategy_key=key,
                display_name=key,
                weak_tqqq_weight=low,
                confirmed_tqqq_weight=confirmed_weight,
                dynamic_breadth=dynamic,
            )
            cost_rows.append(
                {"cost_bps_per_turnover_unit": float(cost_bps), **dict(result.metrics)}
            )
    cost_sensitivity = pd.DataFrame(cost_rows)

    diagnostics = {
        "decision_trace_identical": True,
        "relative_strength_not_used": True,
        "hard_gate_not_used": True,
        "breadth_ma_window": int(logic["ma_window"]),
        "breadth_momentum_sessions": int(logic["momentum_sessions"]),
        "weak_tqqq_weight": weak_weight,
        "confirmed_tqqq_weight": confirmed_weight,
        "changed_weight_sessions": int(len(changed)),
        "changed_session_return_delta_sum": float(changed["challenger_minus_baseline"].sum()),
        "no_parameter_grid": True,
    }
    tables = {
        "chronological_periods": periods,
        "regime_windows": regimes,
        "rolling_metrics": rolling,
        "tier_contribution": tiers,
        "changed_weight_sessions": changed,
        "cost_sensitivity": cost_sensitivity,
        "frozen_decisions": decisions,
    }
    return metrics.sort_index(), results, prepared, diagnostics, tables
