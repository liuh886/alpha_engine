"""QQQ realized downside volatility as an independent leverage-layer veto."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vix_rotation_experiment import VixRotationConfig
from src.research.vxn_attack_layer_long_history import (
    _run_attack_backtest,
    leverage_episodes,
    period_metrics,
    prepare_attack_layer_data,
    rolling_metrics,
)
from src.research.vxn_leverage_overlay_experiment import (
    generate_vxn_leverage_veto_states,
)


def build_downside_volatility_features(
    qqq_close: pd.Series,
    *,
    lookback_sessions: int = 10,
    threshold_window_sessions: int = 252,
    threshold_quantile: float = 0.80,
    minimum_threshold_history_sessions: int = 126,
) -> pd.DataFrame:
    """Build a scale-free trailing downside-deviation stress flag."""

    if lookback_sessions <= 1:
        raise ValueError("lookback_sessions must exceed one")
    if threshold_window_sessions <= lookback_sessions:
        raise ValueError("threshold window must exceed downside lookback")
    if not 0.0 < threshold_quantile < 1.0:
        raise ValueError("threshold_quantile must be in (0, 1)")
    if not lookback_sessions <= minimum_threshold_history_sessions <= threshold_window_sessions:
        raise ValueError("minimum threshold history is inconsistent")

    close = pd.to_numeric(qqq_close, errors="coerce")
    returns = close.pct_change()
    negative = returns.clip(upper=0.0)
    downside = (
        negative.pow(2)
        .rolling(lookback_sessions, min_periods=lookback_sessions)
        .mean()
        .pow(0.5)
        * np.sqrt(252.0)
    )
    threshold = downside.rolling(
        threshold_window_sessions,
        min_periods=minimum_threshold_history_sessions,
    ).quantile(threshold_quantile)

    features = pd.DataFrame(index=close.index)
    features["qqq_close_return"] = returns
    features["qqq_downside_volatility"] = downside
    features["qqq_downside_volatility_threshold"] = threshold
    features["qqq_downside_volatility_stress"] = downside.gt(threshold).fillna(False)
    return features


def generate_downside_volatility_veto_states(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
) -> pd.DataFrame:
    """Add downside-volatility vetoes only to the v4.1 leveraged layer."""

    state = 0
    states: list[int] = []
    reasons: list[str] = []
    for row in prepared.itertuples():
        next_state = state
        reason = "hold"
        severe_defense = bool(row.long_break) or (
            bool(row.vix_stress) and bool(row.stress_price_failure)
        )
        if severe_defense:
            next_state = 0
            reason = "defensive_price_or_vix_stress"
        elif state == 0:
            if bool(row.shock_memory) and bool(row.early_repair) and bool(row.vix_easing):
                next_state = 1
                reason = "enter_qqq_early_repair_vix_easing"
        elif state == 1:
            leverage_ready = (
                bool(row.shock_memory)
                and bool(row.medium_repair)
                and bool(row.secondary_confirmation)
                and bool(row.vix_normalized)
                and not bool(row.vxn_stress)
                and not bool(row.qqq_downside_volatility_stress)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_v4_1_downside_vol_not_stressed"
        else:
            if bool(row.vix_stress) or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_or_ma20"
            elif bool(row.vxn_stress):
                next_state = 1
                reason = "exit_partial_tqqq_vxn_stress"
            elif bool(row.qqq_downside_volatility_stress):
                next_state = 1
                reason = "exit_partial_tqqq_downside_volatility_stress"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons},
        index=prepared.index,
    )


def _future_return(
    prepared: pd.DataFrame, location: int, column: str, horizon: int
) -> float:
    window = prepared.iloc[location + 1 : location + 1 + int(horizon)]
    values = window[column].dropna()
    if len(values) != int(horizon):
        return np.nan
    return float((1.0 + values).prod() - 1.0)


def changed_transition_events(
    prepared: pd.DataFrame,
    baseline_decisions: pd.DataFrame,
    challenger_decisions: pd.DataFrame,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Report every close where downside volatility changes the next state."""

    changed = baseline_decisions["decision_state"].ne(
        challenger_decisions["decision_state"]
    )
    rows: list[dict[str, Any]] = []
    for location in np.flatnonzero(changed.to_numpy(dtype=bool)):
        baseline_state = int(baseline_decisions.iloc[location]["decision_state"])
        challenger_state = int(challenger_decisions.iloc[location]["decision_state"])
        row: dict[str, Any] = {
            "signal_date": prepared.index[int(location)],
            "baseline_state": baseline_state,
            "challenger_state": challenger_state,
            "event_type": (
                "blocked_entry" if baseline_state == 2 and challenger_state == 1 else "early_exit"
            ),
            "downside_volatility": float(
                prepared.iloc[int(location)]["qqq_downside_volatility"]
            ),
            "downside_volatility_threshold": float(
                prepared.iloc[int(location)]["qqq_downside_volatility_threshold"]
            ),
            "vix_stress": bool(prepared.iloc[int(location)]["vix_stress"]),
            "vxn_stress": bool(prepared.iloc[int(location)]["vxn_stress"]),
        }
        for horizon in horizons:
            row[f"QQQ_return_{int(horizon)}d"] = _future_return(
                prepared, int(location), "QQQ_next_open_return", int(horizon)
            )
            row[f"TQQQ_return_{int(horizon)}d"] = _future_return(
                prepared, int(location), "TQQQ_next_open_return", int(horizon)
            )
        rows.append(row)
    return pd.DataFrame(rows)


def stress_overlap(prepared: pd.DataFrame) -> dict[str, Any]:
    """Measure whether downside stress is redundant with VIX and VXN stress."""

    downside = prepared["qqq_downside_volatility_stress"].astype(bool)
    vix = prepared["vix_stress"].astype(bool)
    vxn = prepared["vxn_stress"].astype(bool)
    return {
        "downside_stress_sessions": int(downside.sum()),
        "vix_stress_sessions": int(vix.sum()),
        "vxn_stress_sessions": int(vxn.sum()),
        "downside_and_vix_sessions": int((downside & vix).sum()),
        "downside_and_vxn_sessions": int((downside & vxn).sum()),
        "downside_and_either_implied_vol_sessions": int((downside & (vix | vxn)).sum()),
        "downside_only_vs_vix_vxn_sessions": int((downside & ~vix & ~vxn).sum()),
        "downside_share_overlapping_vxn": (
            float((downside & vxn).sum() / downside.sum()) if downside.sum() else 0.0
        ),
        "downside_share_unique_vs_vix_vxn": (
            float((downside & ~vix & ~vxn).sum() / downside.sum())
            if downside.sum()
            else 0.0
        ),
    }


def economic_position_differences(
    baseline: StrategyResult, challenger: StrategyResult
) -> pd.DataFrame:
    """Return economic sessions where the downside veto changes holdings."""

    joined = pd.DataFrame(
        {
            "baseline_state": baseline.daily["position_state"],
            "challenger_state": challenger.daily["position_state"],
            "baseline_return": baseline.daily["net_return"],
            "challenger_return": challenger.daily["net_return"],
            "downside_volatility": challenger.daily["qqq_downside_volatility"],
            "downside_volatility_threshold": challenger.daily[
                "qqq_downside_volatility_threshold"
            ],
        }
    )
    changed = joined[joined["baseline_state"].ne(joined["challenger_state"])].copy()
    changed["challenger_minus_baseline"] = (
        changed["challenger_return"] - changed["baseline_return"]
    )
    return changed.reset_index(names="date")


def run_downside_volatility_veto_comparison(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
]:
    """Compare frozen v4.1 with one realized downside-volatility veto."""

    base_contract = contract["resolved_base_contract"]
    prepared, config = prepare_attack_layer_data(bars, base_contract)
    logic = contract["downside_volatility"]
    features = build_downside_volatility_features(
        prepared["QQQ_close"],
        lookback_sessions=int(logic["lookback_sessions"]),
        threshold_window_sessions=int(logic["threshold_window_sessions"]),
        threshold_quantile=float(logic["threshold_quantile"]),
        minimum_threshold_history_sessions=int(
            logic["minimum_threshold_history_sessions"]
        ),
    )
    prepared = prepared.join(features, how="left")
    prepared = prepared.dropna(
        subset=["qqq_downside_volatility", "qqq_downside_volatility_threshold"]
    ).copy()
    prepared["qqq_downside_volatility_stress"] = prepared[
        "qqq_downside_volatility_stress"
    ].fillna(False).astype(bool)

    baseline_decisions = generate_vxn_leverage_veto_states(prepared, config)
    challenger_decisions = generate_downside_volatility_veto_states(prepared, config)
    baseline = _run_attack_backtest(
        prepared,
        baseline_decisions,
        config,
        strategy_key="attack_vxn_v4_1_75",
        display_name="Frozen v4.1 VXN veto",
    )
    challenger = _run_attack_backtest(
        prepared,
        challenger_decisions,
        config,
        strategy_key="attack_downside_volatility_v4_2_75",
        display_name="v4.1 + QQQ downside-volatility veto",
    )
    results = {
        "attack_vxn_v4_1_75": baseline,
        "attack_downside_volatility_v4_2_75": challenger,
    }
    metrics = pd.DataFrame(
        [dict(result.metrics) for result in results.values()]
    ).set_index("strategy")

    validation = contract["validation"]
    periods = period_metrics(results, validation["chronological_periods"])
    regimes = period_metrics(results, validation["regime_windows"])
    rolling = rolling_metrics(results, validation["rolling_windows_sessions"])
    episodes = pd.concat(
        [leverage_episodes(result) for result in results.values()],
        ignore_index=True,
    )
    transition_events = changed_transition_events(
        prepared,
        baseline_decisions,
        challenger_decisions,
        validation["event_horizons"],
    )
    differences = economic_position_differences(baseline, challenger)

    cost_rows: list[dict[str, Any]] = []
    for cost_bps in validation["cost_sensitivity_bps"]:
        cost_config = replace(
            config, transaction_cost_bps_per_turnover_unit=float(cost_bps)
        )
        for key, decisions in (
            ("attack_vxn_v4_1_75", baseline_decisions),
            ("attack_downside_volatility_v4_2_75", challenger_decisions),
        ):
            result = _run_attack_backtest(
                prepared,
                decisions,
                cost_config,
                strategy_key=key,
                display_name=key,
            )
            cost_rows.append(
                {"cost_bps_per_turnover_unit": float(cost_bps), **dict(result.metrics)}
            )
    cost_sensitivity = pd.DataFrame(cost_rows)

    overlap = stress_overlap(prepared)
    diagnostics = {
        "only_new_factor": "QQQ_ten_session_downside_volatility",
        "lookback_sessions": int(logic["lookback_sessions"]),
        "threshold_window_sessions": int(logic["threshold_window_sessions"]),
        "threshold_quantile": float(logic["threshold_quantile"]),
        "minimum_threshold_history_sessions": int(
            logic["minimum_threshold_history_sessions"]
        ),
        "entry_veto": True,
        "existing_leverage_exit": True,
        "changed_transition_dates": int(len(transition_events)),
        "changed_economic_sessions": int(len(differences)),
        "changed_session_return_delta_sum": float(
            differences["challenger_minus_baseline"].sum()
        ),
        "stress_overlap": overlap,
        "no_parameter_grid": True,
    }
    tables = {
        "chronological_periods": periods,
        "regime_windows": regimes,
        "rolling_metrics": rolling,
        "leverage_episodes": episodes,
        "transition_events": transition_events,
        "economic_position_differences": differences,
        "cost_sensitivity": cost_sensitivity,
        "baseline_decisions": baseline_decisions,
        "challenger_decisions": challenger_decisions,
    }
    return metrics.sort_index(), results, prepared, diagnostics, tables
