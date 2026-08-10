"""One-shot 50% TQQQ recovery-precursor experiment for the frozen v4.2 family.

This module tests exactly one bolder pre-state-2 allocation: when the already
frozen precursor is observable, executed state 1 becomes 50% QQQ / 50% TQQQ.
The precursor dates and formal v4.2 state-2 allocation are unchanged.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_sgov_defense_experiment import (
    ASSETS,
    V4_2_KEY,
    _chronological_metrics,
    _common_reference_daily,
)
from src.research.v4_2_sgov_episode_attribution_corrected import (
    attribute_sgov_drawdown_episodes_at_baseline_trough,
)
from src.research.v4_2_sgov_recovery_release_experiment import (
    leverage_precursor_decision,
    run_sgov_recovery_release_comparison,
)
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

BOLD_KEY = "tqqq_precursor_50"
PRIOR_KEY = "tqqq_release_on_precursor"


def _normalise_weights(raw: Mapping[str, Any], label: str) -> dict[str, float]:
    weights = {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}
    if any(value < 0.0 for value in weights.values()):
        raise ValueError(f"{label} contains a negative weight")
    if not np.isclose(sum(weights.values()), 1.0):
        raise ValueError(f"{label} weights must sum to one")
    return weights


def precursor_50_weights(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.Series]:
    """Map the frozen state trace to the single 50% TQQQ precursor allocation."""

    allocation = contract["allocation"]
    state_0 = _normalise_weights(allocation["state_0_blended"], "state_0_blended")
    state_1 = _normalise_weights(allocation["ordinary_state_1"], "ordinary_state_1")
    precursor = _normalise_weights(allocation["precursor_50"], "precursor_50")
    state_2 = _normalise_weights(allocation["formal_state_2"], "formal_state_2")

    states = reference_daily["position_state"].astype(int)
    weights = pd.DataFrame(0.0, index=reference_daily.index, columns=list(ASSETS))
    for state, state_weights in ((0, state_0), (1, state_1), (2, state_2)):
        mask = states.eq(state)
        for asset, value in state_weights.items():
            weights.loc[mask, asset] = value

    precursor_at_close = leverage_precursor_decision(reference_daily)
    precursor_at_open = precursor_at_close.shift(1).fillna(False).astype(bool)
    precursor_at_open &= states.eq(1)
    for asset, value in precursor.items():
        weights.loc[precursor_at_open, asset] = value

    cap = float(contract["precursor"]["maximum_tqqq_weight_before_state_2"])
    if float(weights.loc[states.ne(2), "TQQQ"].max()) > cap + 1e-12:
        raise AssertionError("pre-state-2 TQQQ weight exceeds the 50% cap")
    return weights, precursor_at_open


def run_precursor_50_backtest(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> StrategyResult:
    """Execute the 50% precursor on the unchanged v4.2 state trace."""

    daily = reference_daily.copy()
    weights, precursor_active = precursor_50_weights(daily, contract)
    daily["precursor_active"] = precursor_active
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]
    daily["release_stage"] = "defensive_blended"
    daily.loc[daily["position_state"].eq(1), "release_stage"] = "state_1"
    daily.loc[precursor_active, "release_stage"] = "tqqq_precursor_50"
    daily.loc[daily["position_state"].eq(2), "release_stage"] = "state_2"

    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"] for asset in ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    metrics = _return_metrics(daily["net_return"], annual_risk_free_rate=0.0)
    aligned_weights = weights.loc[daily.index]
    weight_changes = aligned_weights.ne(aligned_weights.shift()).any(axis=1)
    state_changes = daily["position_state"].ne(daily["position_state"].shift())
    metrics.update(
        {
            "strategy": BOLD_KEY,
            "state_switch_count": int(max(int(state_changes.sum()) - 1, 0)),
            "rebalance_count": int(max(int(weight_changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "precursor_sessions": int(daily["precursor_active"].sum()),
            "average_qqqi_weight": float(daily["weight_QQQI"].mean()),
            "average_qqq_weight": float(daily["weight_QQQ"].mean()),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
            "average_sgov_weight": float(daily["weight_SGOV"].mean()),
        }
    )
    trades = daily.loc[
        weight_changes,
        [
            "position_state",
            "position_label",
            "executed_reason",
            "release_stage",
            "precursor_active",
            "weight_QQQI",
            "weight_QQQ",
            "weight_TQQQ",
            "weight_SGOV",
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(BOLD_KEY, daily, trades, metrics)


def _event_comparison(
    candidate: StrategyResult,
    comparator: StrategyResult,
    horizons: list[int],
) -> pd.DataFrame:
    """Measure contiguous precursor events against a chosen comparator."""

    active = candidate.daily["precursor_active"].astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    index = candidate.daily.index
    rows: list[dict[str, Any]] = []
    for event_number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and bool(active.iloc[end_location + 1]):
            end_location += 1
        event_slice = slice(start_location, end_location + 1)
        candidate_event = candidate.daily["net_return"].iloc[event_slice]
        comparator_event = comparator.daily["net_return"].iloc[event_slice]
        event_log_relative = float(
            np.log1p(candidate_event).sum() - np.log1p(comparator_event).sum()
        )
        row: dict[str, Any] = {
            "event_id": f"precursor_{event_number:03d}",
            "start_date": start,
            "end_date": index[end_location],
            "sessions": int(end_location - start_location + 1),
            "event_log_relative": event_log_relative,
            "event_relative_return": float(np.exp(event_log_relative) - 1.0),
        }
        for horizon in horizons:
            stop = start_location + int(horizon)
            if stop > len(index):
                row[f"relative_return_{horizon}d"] = np.nan
                continue
            candidate_window = candidate.daily["net_return"].iloc[start_location:stop]
            comparator_window = comparator.daily["net_return"].iloc[start_location:stop]
            log_relative = float(
                np.log1p(candidate_window).sum() - np.log1p(comparator_window).sum()
            )
            row[f"relative_return_{horizon}d"] = float(np.exp(log_relative) - 1.0)
        rows.append(row)
    return pd.DataFrame(rows)


def _risk_worsening_pp(candidate: float, comparator: float) -> float:
    return max(0.0, (abs(float(candidate)) - abs(float(comparator))) * 100.0)


def _shadow_gate(
    bold: StrategyResult,
    prior: StrategyResult,
    v4_2: StrategyResult,
    episodes: pd.DataFrame,
    chronological: pd.DataFrame,
    marginal_events: pd.DataFrame,
    tail_bold: Mapping[str, Any],
    tail_prior: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["shadow_gate"]
    chrono = chronological.set_index(["strategy", "segment"])
    major = episodes.loc[episodes["major_episode"]].copy()
    resolved = major.loc[major["recovery_lag_sessions"].notna()]

    event_count = int(len(marginal_events))
    if event_count:
        values = marginal_events["event_log_relative"].astype(float)
        event_positive_rate = float(values.gt(0.0).mean())
        positive = values.clip(lower=0.0)
        largest_event_share = (
            float(positive.max() / positive.sum()) if float(positive.sum()) > 0.0 else 1.0
        )
    else:
        event_positive_rate = 0.0
        largest_event_share = 1.0

    metrics = {
        "precursor_event_count": event_count,
        "marginal_event_positive_rate_vs_25": event_positive_rate,
        "largest_marginal_event_benefit_share": largest_event_share,
        "full_sample_cagr_delta_vs_25_pp": (
            float(bold.metrics["cagr"]) - float(prior.metrics["cagr"])
        )
        * 100.0,
        "early_segment_cagr_delta_vs_25_pp": (
            float(chrono.loc[(BOLD_KEY, "early"), "cagr"])
            - float(chrono.loc[(PRIOR_KEY, "early"), "cagr"])
        )
        * 100.0,
        "late_segment_cagr_delta_vs_25_pp": (
            float(chrono.loc[(BOLD_KEY, "late"), "cagr"])
            - float(chrono.loc[(PRIOR_KEY, "late"), "cagr"])
        )
        * 100.0,
        "sharpe_delta_vs_25": float(bold.metrics["sharpe"]) - float(prior.metrics["sharpe"]),
        "maximum_drawdown_worsening_vs_25_pp": _risk_worsening_pp(
            float(bold.metrics["max_drawdown"]), float(prior.metrics["max_drawdown"])
        ),
        "expected_shortfall_95_worsening_vs_25_pp": _risk_worsening_pp(
            float(tail_bold["expected_shortfall_95"]),
            float(tail_prior["expected_shortfall_95"]),
        ),
        "worst_5d_worsening_vs_25_pp": _risk_worsening_pp(
            float(tail_bold["worst_5d_return"]),
            float(tail_prior["worst_5d_return"]),
        ),
        "worst_20d_worsening_vs_25_pp": _risk_worsening_pp(
            float(tail_bold["worst_20d_return"]),
            float(tail_prior["worst_20d_return"]),
        ),
        "major_episode_drawdown_improvement_rate_vs_v4_2": float(
            major["drawdown_improvement"].gt(0.0).mean()
        ),
        "median_major_episode_trough_protection_pp": float(
            major["drawdown_improvement_pp"].median()
        ),
        "median_resolved_recovery_lag_sessions": (
            float(resolved["recovery_lag_sessions"].median()) if len(resolved) else None
        ),
        "unresolved_major_episode_count": int(major["recovery_lag_sessions"].isna().sum()),
        "cagr_delta_vs_v4_2_pp": (float(bold.metrics["cagr"]) - float(v4_2.metrics["cagr"]))
        * 100.0,
    }
    checks = {
        "minimum_precursor_event_count": event_count
        >= int(thresholds["minimum_precursor_event_count"]),
        "marginal_event_positive_rate_vs_25": event_positive_rate
        >= float(thresholds["marginal_event_positive_rate_vs_25_min"]),
        "marginal_event_concentration": largest_event_share
        <= float(thresholds["largest_marginal_event_benefit_share_max"]),
        "full_sample_cagr_delta_vs_25": metrics["full_sample_cagr_delta_vs_25_pp"]
        >= float(thresholds["full_sample_cagr_delta_vs_25_pp_min"]),
        "early_segment_cagr_delta_vs_25": metrics["early_segment_cagr_delta_vs_25_pp"]
        >= float(thresholds["early_segment_cagr_delta_vs_25_pp_min"]),
        "late_segment_cagr_delta_vs_25": metrics["late_segment_cagr_delta_vs_25_pp"]
        >= float(thresholds["late_segment_cagr_delta_vs_25_pp_min"]),
        "sharpe_delta_vs_25": metrics["sharpe_delta_vs_25"]
        >= float(thresholds["sharpe_delta_vs_25_min"]),
        "maximum_drawdown_vs_25": metrics["maximum_drawdown_worsening_vs_25_pp"]
        <= float(thresholds["maximum_drawdown_worsening_vs_25_pp_max"]),
        "expected_shortfall_95_vs_25": metrics["expected_shortfall_95_worsening_vs_25_pp"]
        <= float(thresholds["expected_shortfall_95_worsening_vs_25_pp_max"]),
        "worst_5d_vs_25": metrics["worst_5d_worsening_vs_25_pp"]
        <= float(thresholds["worst_5d_worsening_vs_25_pp_max"]),
        "worst_20d_vs_25": metrics["worst_20d_worsening_vs_25_pp"]
        <= float(thresholds["worst_20d_worsening_vs_25_pp_max"]),
        "major_episode_drawdown_improvement_vs_v4_2": metrics[
            "major_episode_drawdown_improvement_rate_vs_v4_2"
        ]
        >= float(thresholds["major_episode_drawdown_improvement_rate_vs_v4_2_min"]),
        "median_major_episode_trough_protection": metrics[
            "median_major_episode_trough_protection_pp"
        ]
        >= float(thresholds["median_major_episode_trough_protection_pp_min"]),
        "unresolved_major_episodes": metrics["unresolved_major_episode_count"]
        <= int(thresholds["unresolved_major_episode_count_max"]),
    }
    return {
        "shadow_monitor_authorized": bool(all(checks.values())),
        "direct_promotion_authorized": False,
        "checks": checks,
        "metrics": metrics,
    }


def run_precursor_50_comparison(
    bars: Mapping[str, pd.DataFrame],
    baseline_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    prior_release_contract: Mapping[str, Any],
    bold_contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Compare the single 50% precursor with the frozen 25% precursor."""

    (
        _,
        prior_results,
        _,
        _,
        _,
        prior_diagnostics,
    ) = run_sgov_recovery_release_comparison(
        bars,
        baseline_contract,
        sgov_contract,
        attribution_contract,
        prior_release_contract,
    )
    _, bridge_results, _, _ = run_bridge_allocation_comparison(bars, baseline_contract)
    reference = _common_reference_daily(bridge_results[V4_2_KEY], bars)
    bold = run_precursor_50_backtest(reference, bold_contract)

    v4_2 = prior_results["current_v4_2"]
    static = prior_results["static_blended"]
    prior = prior_results[PRIOR_KEY]
    if (
        not bold.daily["position_state"]
        .astype(int)
        .equals(v4_2.daily["position_state"].astype(int))
    ):
        raise AssertionError("50% precursor changed the frozen v4.2 state trace")
    if (
        not bold.daily["precursor_active"]
        .astype(bool)
        .equals(prior.daily["precursor_active"].astype(bool))
    ):
        raise AssertionError("50% precursor dates differ from the frozen 25% precursor")
    state_two = bold.daily.loc[bold.daily["position_state"].eq(2)]
    if not (
        np.allclose(state_two["weight_QQQ"], 0.25)
        and np.allclose(state_two["weight_TQQQ"], 0.75)
        and np.allclose(state_two["weight_QQQI"], 0.0)
        and np.allclose(state_two["weight_SGOV"], 0.0)
    ):
        raise AssertionError("50% precursor changed the frozen state-2 allocation")

    results = {
        "current_v4_2": v4_2,
        "static_blended": static,
        PRIOR_KEY: prior,
        BOLD_KEY: bold,
    }
    headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
        "strategy"
    )
    train_fraction = float(bold_contract["validation"]["chronological_train_fraction"])
    chronological = pd.DataFrame(
        [
            row
            for result in results.values()
            for row in _chronological_metrics(result, train_fraction)
        ]
    )
    episodes, _ = attribute_sgov_drawdown_episodes_at_baseline_trough(
        v4_2, bold, attribution_contract
    )
    horizons = [int(value) for value in bold_contract["validation"]["event_horizons"]]
    events_vs_static = _event_comparison(bold, static, horizons)
    marginal_events = _event_comparison(bold, prior, horizons)
    tail = {key: tail_risk_metrics(result) for key, result in results.items()}
    gate = _shadow_gate(
        bold,
        prior,
        v4_2,
        episodes,
        chronological,
        marginal_events,
        tail[BOLD_KEY],
        tail[PRIOR_KEY],
        bold_contract,
    )
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "same_v4_2_state_trace": True,
        "same_precursor_dates_as_25": True,
        "same_state_2_allocation": True,
        "cost_bps_per_turnover_unit": float(
            bold_contract["boundaries"]["transaction_cost_bps_per_turnover_unit"]
        ),
        "common_sample_start": reference.index.min().date().isoformat(),
        "common_sample_end": reference.index.max().date().isoformat(),
        "observations": int(len(reference)),
        "tail_risk": tail,
        "shadow_gate": gate,
        "prior_25_percent_gate": prior_diagnostics["candidate_gates"][PRIOR_KEY],
        "direct_promotion_authorized": False,
    }
    return (
        headline.sort_index(),
        results,
        chronological,
        episodes,
        events_vs_static,
        marginal_events,
        diagnostics,
    )
