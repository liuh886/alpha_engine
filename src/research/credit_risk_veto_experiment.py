"""HYG/SHY adjusted-price trend as an independent leverage-layer veto."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult
from src.research.vix_rotation_experiment import VixRotationConfig, _normalise_close
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

HIGH_YIELD_SYMBOL = "HYG"
SHORT_TREASURY_SYMBOL = "SHY"


def build_credit_proxy_features(
    hyg_bars: pd.DataFrame,
    shy_bars: pd.DataFrame,
    prepared_index: pd.Index,
    *,
    moving_average_sessions: int = 50,
    minimum_common_sessions: int = 756,
    minimum_coverage_ratio_within_common_span: float = 0.98,
    maximum_absolute_daily_ratio_return: float = 0.20,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build and validate the adjusted-close HYG/SHY trend proxy."""

    if moving_average_sessions <= 1:
        raise ValueError("moving_average_sessions must exceed one")
    if minimum_common_sessions < moving_average_sessions:
        raise ValueError("minimum_common_sessions is too short")
    if not 0.0 < minimum_coverage_ratio_within_common_span <= 1.0:
        raise ValueError("coverage ratio must be in (0, 1]")
    if maximum_absolute_daily_ratio_return <= 0.0:
        raise ValueError("maximum ratio return must be positive")

    hyg = _normalise_close(hyg_bars, HIGH_YIELD_SYMBOL)
    shy = _normalise_close(shy_bars, SHORT_TREASURY_SYMBOL)
    common = hyg.index.intersection(shy.index).intersection(prepared_index).sort_values()
    if len(common) < minimum_common_sessions:
        raise ValueError(
            f"credit proxy common history {len(common)} is below {minimum_common_sessions}"
        )
    span_index = prepared_index[
        (prepared_index >= common.min()) & (prepared_index <= common.max())
    ]
    coverage_ratio = float(len(common) / len(span_index)) if len(span_index) else 0.0
    if coverage_ratio < minimum_coverage_ratio_within_common_span:
        raise ValueError(
            "credit proxy coverage ratio "
            f"{coverage_ratio:.4f} is below {minimum_coverage_ratio_within_common_span:.4f}"
        )

    ratio = (hyg.reindex(common) / shy.reindex(common)).rename("hyg_shy_ratio")
    if ratio.isna().any() or ratio.le(0.0).any():
        raise ValueError("credit proxy contains missing or non-positive values")
    ratio_return = ratio.pct_change()
    max_abs_return = float(ratio_return.abs().max())
    if max_abs_return > maximum_absolute_daily_ratio_return:
        raise ValueError(
            f"credit proxy daily return {max_abs_return:.4f} exceeds quality guard"
        )

    features = pd.DataFrame(index=common)
    features["hyg_close"] = hyg.reindex(common)
    features["shy_close"] = shy.reindex(common)
    features["hyg_shy_ratio"] = ratio
    features["hyg_shy_ratio_return"] = ratio_return
    features["hyg_shy_ma"] = ratio.rolling(
        moving_average_sessions, min_periods=moving_average_sessions
    ).mean()
    features["credit_risk_stress"] = ratio.lt(features["hyg_shy_ma"]).fillna(False)

    missing_dates = span_index.difference(common)
    diagnostics = {
        "high_yield_symbol": HIGH_YIELD_SYMBOL,
        "short_treasury_symbol": SHORT_TREASURY_SYMBOL,
        "common_start": common.min().date().isoformat(),
        "common_end": common.max().date().isoformat(),
        "common_sessions": int(len(common)),
        "prepared_sessions_within_common_span": int(len(span_index)),
        "coverage_ratio_within_common_span": coverage_ratio,
        "missing_sessions_within_common_span": int(len(missing_dates)),
        "maximum_absolute_daily_ratio_return": max_abs_return,
        "all_adjusted_closes_positive": True,
        "quality_passed": True,
        "proxy_is_not_pure_credit_spread": True,
    }
    return features, diagnostics


def generate_credit_risk_veto_states(
    prepared: pd.DataFrame,
    config: VixRotationConfig,
) -> pd.DataFrame:
    """Add credit-risk vetoes only to the frozen v4.1 leveraged layer."""

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
                and not bool(row.credit_risk_stress)
            )
            if leverage_ready:
                next_state = 2
                reason = "enter_partial_tqqq_v4_1_credit_not_stressed"
        else:
            if bool(row.vix_stress) or bool(row.below_ma_short_n):
                next_state = 1
                reason = "exit_partial_tqqq_vix_or_ma20"
            elif bool(row.vxn_stress):
                next_state = 1
                reason = "exit_partial_tqqq_vxn_stress"
            elif bool(row.credit_risk_stress):
                next_state = 1
                reason = "exit_partial_tqqq_credit_risk_stress"
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
    """Report every close where the credit proxy changes the next state."""

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
            "hyg_shy_ratio": float(prepared.iloc[int(location)]["hyg_shy_ratio"]),
            "hyg_shy_ma": float(prepared.iloc[int(location)]["hyg_shy_ma"]),
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
    """Measure overlap between credit risk-off and implied-volatility stress."""

    credit = prepared["credit_risk_stress"].astype(bool)
    vix = prepared["vix_stress"].astype(bool)
    vxn = prepared["vxn_stress"].astype(bool)
    return {
        "credit_stress_sessions": int(credit.sum()),
        "vix_stress_sessions": int(vix.sum()),
        "vxn_stress_sessions": int(vxn.sum()),
        "credit_and_vix_sessions": int((credit & vix).sum()),
        "credit_and_vxn_sessions": int((credit & vxn).sum()),
        "credit_and_either_implied_vol_sessions": int((credit & (vix | vxn)).sum()),
        "credit_only_vs_vix_vxn_sessions": int((credit & ~vix & ~vxn).sum()),
        "credit_share_overlapping_vxn": (
            float((credit & vxn).sum() / credit.sum()) if credit.sum() else 0.0
        ),
        "credit_share_unique_vs_vix_vxn": (
            float((credit & ~vix & ~vxn).sum() / credit.sum())
            if credit.sum()
            else 0.0
        ),
    }


def economic_position_differences(
    baseline: StrategyResult, challenger: StrategyResult
) -> pd.DataFrame:
    """Return economic sessions where the credit veto changes holdings."""

    joined = pd.DataFrame(
        {
            "baseline_state": baseline.daily["position_state"],
            "challenger_state": challenger.daily["position_state"],
            "baseline_return": baseline.daily["net_return"],
            "challenger_return": challenger.daily["net_return"],
            "hyg_shy_ratio": challenger.daily["hyg_shy_ratio"],
            "hyg_shy_ma": challenger.daily["hyg_shy_ma"],
        }
    )
    changed = joined[joined["baseline_state"].ne(joined["challenger_state"])].copy()
    changed["challenger_minus_baseline"] = (
        changed["challenger_return"] - changed["baseline_return"]
    )
    return changed.reset_index(names="date")


def run_credit_risk_veto_comparison(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
]:
    """Compare frozen v4.1 with one HYG/SHY MA50 leverage veto."""

    base_contract = contract["resolved_base_contract"]
    prepared, config = prepare_attack_layer_data(bars, base_contract)
    logic = contract["credit_logic"]
    quality = contract["data_quality"]
    credit_features, quality_diagnostics = build_credit_proxy_features(
        bars[HIGH_YIELD_SYMBOL],
        bars[SHORT_TREASURY_SYMBOL],
        prepared.index,
        moving_average_sessions=int(logic["moving_average_sessions"]),
        minimum_common_sessions=int(quality["minimum_common_sessions"]),
        minimum_coverage_ratio_within_common_span=float(
            quality["minimum_coverage_ratio_within_common_span"]
        ),
        maximum_absolute_daily_ratio_return=float(
            quality["maximum_absolute_daily_ratio_return"]
        ),
    )
    prepared = prepared.join(credit_features, how="left")
    prepared = prepared.dropna(subset=["hyg_shy_ratio", "hyg_shy_ma"]).copy()
    prepared["credit_risk_stress"] = prepared["credit_risk_stress"].fillna(False).astype(bool)

    baseline_decisions = generate_vxn_leverage_veto_states(prepared, config)
    challenger_decisions = generate_credit_risk_veto_states(prepared, config)
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
        strategy_key="attack_credit_risk_v4_2_75",
        display_name="v4.1 + HYG/SHY credit-risk veto",
    )
    results = {
        "attack_vxn_v4_1_75": baseline,
        "attack_credit_risk_v4_2_75": challenger,
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
            ("attack_credit_risk_v4_2_75", challenger_decisions),
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
        "only_new_factor": "adjusted_close_HYG_divided_by_SHY_below_MA50",
        "moving_average_sessions": int(logic["moving_average_sessions"]),
        "entry_veto": True,
        "existing_leverage_exit": True,
        "changed_transition_dates": int(len(transition_events)),
        "changed_economic_sessions": int(len(differences)),
        "changed_session_return_delta_sum": float(
            differences["challenger_minus_baseline"].sum()
        ),
        "data_quality": quality_diagnostics,
        "stress_overlap": overlap,
        "proxy_is_not_pure_credit_spread": True,
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
