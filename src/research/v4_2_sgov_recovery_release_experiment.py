"""Controlled SGOV recovery-release ablations for the frozen v4.2 family.

The experiment does not change the v4.2 decision state machine. It only tests
when the already-defined 25% or 50% SGOV defensive sleeve is released during a
recovery. All allocation decisions are made from close-time information and
executed at the next session open.
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
    run_state_weight_backtest,
)
from src.research.v4_2_sgov_episode_attribution_corrected import (
    attribute_sgov_drawdown_episodes_at_baseline_trough,
)
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)


def _normalise_weights(raw: Mapping[str, Any], label: str) -> dict[str, float]:
    weights = {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}
    if any(value < 0.0 for value in weights.values()):
        raise ValueError(f"{label} contains a negative weight")
    if not np.isclose(sum(weights.values()), 1.0):
        raise ValueError(f"{label} weights must sum to one")
    return weights


def leverage_precursor_decision(reference_daily: pd.DataFrame) -> pd.Series:
    """Return the frozen close-time precursor, before execution shifting."""

    required = {
        "shock_memory",
        "medium_repair",
        "vix_normalized",
        "vxn_stress",
    }
    missing = sorted(required - set(reference_daily.columns))
    if missing:
        raise ValueError(f"reference daily missing precursor columns: {missing}")
    return (
        reference_daily["shock_memory"].astype(bool)
        & reference_daily["medium_repair"].astype(bool)
        & reference_daily["vix_normalized"].astype(bool)
        & ~reference_daily["vxn_stress"].astype(bool)
    )


def recovery_release_weights(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    variant: str,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build next-open weights for one predeclared release variant."""

    variants = contract["variants"]
    if variant not in variants:
        raise ValueError(f"unknown release variant: {variant}")
    spec = variants[variant]
    allocations = contract["frozen_allocations"]
    state_0 = _normalise_weights(allocations["state_0_blended"], "state_0_blended")
    state_1 = _normalise_weights(
        allocations[
            "state_1_qqqi_release"
            if bool(spec["release_sgov_to_qqqi_on_state_1"])
            else "state_1_blended"
        ],
        "state_1",
    )
    precursor = _normalise_weights(
        allocations["state_1_tqqq_precursor"], "state_1_tqqq_precursor"
    )
    state_2 = _normalise_weights(allocations["state_2_frozen"], "state_2_frozen")

    states = reference_daily["position_state"].astype(int)
    weights = pd.DataFrame(0.0, index=reference_daily.index, columns=list(ASSETS))
    for state, state_weights in ((0, state_0), (1, state_1), (2, state_2)):
        mask = states.eq(state)
        for asset, value in state_weights.items():
            weights.loc[mask, asset] = value

    precursor_at_close = leverage_precursor_decision(reference_daily)
    precursor_at_open = precursor_at_close.shift(1).fillna(False).astype(bool)
    precursor_at_open &= states.eq(1)
    if bool(spec["use_tqqq_precursor"]):
        for asset, value in precursor.items():
            weights.loc[precursor_at_open, asset] = value
    else:
        precursor_at_open[:] = False

    maximum = float(contract["precursor"]["maximum_tqqq_weight_before_state_2"])
    pre_state_two = states.ne(2)
    if float(weights.loc[pre_state_two, "TQQQ"].max()) > maximum + 1e-12:
        raise AssertionError("pre-state-2 TQQQ weight exceeds the frozen cap")
    return weights, precursor_at_open


def run_recovery_release_backtest(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    variant: str,
) -> StrategyResult:
    """Execute one release allocation on the unchanged v4.2 state trace."""

    daily = reference_daily.copy()
    weights, precursor_active = recovery_release_weights(daily, contract, variant)
    daily["precursor_active"] = precursor_active
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]
    daily["release_stage"] = "defensive_blended"
    daily.loc[daily["position_state"].eq(1), "release_stage"] = "state_1"
    daily.loc[precursor_active, "release_stage"] = "tqqq_precursor"
    daily.loc[daily["position_state"].eq(2), "release_stage"] = "state_2"

    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in ASSETS
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
    weight_changes = weights.loc[daily.index].ne(weights.loc[daily.index].shift()).any(axis=1)
    state_changes = daily["position_state"].ne(daily["position_state"].shift())
    metrics.update(
        {
            "strategy": variant,
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
    return StrategyResult(variant, daily, trades, metrics)


def _precursor_episode_rows(
    candidate: StrategyResult,
    static_blended: StrategyResult,
    horizons: list[int],
) -> pd.DataFrame:
    """Measure each contiguous precursor episode against the static blend."""

    active = candidate.daily["precursor_active"].astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    rows: list[dict[str, Any]] = []
    index = candidate.daily.index
    for event_number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and bool(active.iloc[end_location + 1]):
            end_location += 1
        event_slice = slice(start_location, end_location + 1)
        candidate_event = candidate.daily["net_return"].iloc[event_slice]
        static_event = static_blended.daily["net_return"].iloc[event_slice]
        event_log_relative = float(
            np.log1p(candidate_event).sum() - np.log1p(static_event).sum()
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
            static_window = static_blended.daily["net_return"].iloc[start_location:stop]
            log_relative = float(
                np.log1p(candidate_window).sum() - np.log1p(static_window).sum()
            )
            row[f"relative_return_{horizon}d"] = float(np.exp(log_relative) - 1.0)
        rows.append(row)
    return pd.DataFrame(rows)


def _candidate_gate(
    candidate: StrategyResult,
    v4_2: StrategyResult,
    static_blended: StrategyResult,
    episodes: pd.DataFrame,
    chronological: pd.DataFrame,
    precursor_events: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    uses_precursor: bool,
) -> dict[str, Any]:
    thresholds = contract["validation"]["candidate_gate"]
    major = episodes.loc[episodes["major_episode"]].copy()
    improvement_rate = float(major["drawdown_improvement"].gt(0.0).mean())
    median_protection = float(major["drawdown_improvement_pp"].median())
    resolved = major.loc[major["recovery_lag_sessions"].notna()]
    median_lag = (
        float(resolved["recovery_lag_sessions"].median()) if len(resolved) else None
    )
    unresolved = int(major["recovery_lag_sessions"].isna().sum())
    cagr_sacrifice = float(
        (float(v4_2.metrics["cagr"]) - float(candidate.metrics["cagr"])) * 100.0
    )
    drawdown_worsening = max(
        0.0,
        (
            abs(float(candidate.metrics["max_drawdown"]))
            - abs(float(v4_2.metrics["max_drawdown"]))
        )
        * 100.0,
    )

    chrono = chronological.set_index(["strategy", "segment"])
    early_delta = float(
        (
            chrono.loc[(candidate.metrics["strategy"], "early"), "cagr"]
            - chrono.loc[(static_blended.metrics["strategy"], "early"), "cagr"]
        )
        * 100.0
    )
    late_delta = float(
        (
            chrono.loc[(candidate.metrics["strategy"], "late"), "cagr"]
            - chrono.loc[(static_blended.metrics["strategy"], "late"), "cagr"]
        )
        * 100.0
    )

    event_positive_rate: float | None = None
    largest_event_share: float | None = None
    if uses_precursor:
        if precursor_events.empty:
            event_positive_rate = 0.0
            largest_event_share = 1.0
        else:
            values = precursor_events["event_log_relative"].astype(float)
            event_positive_rate = float(values.gt(0.0).mean())
            positive = values.clip(lower=0.0)
            largest_event_share = (
                float(positive.max() / positive.sum())
                if float(positive.sum()) > 0.0
                else 1.0
            )

    checks = {
        "major_episode_drawdown_improvement_rate": improvement_rate
        >= float(thresholds["major_episode_drawdown_improvement_rate_min"]),
        "median_major_episode_trough_protection": median_protection
        >= float(thresholds["median_major_episode_trough_protection_pp_min"]),
        "median_major_episode_recovery_lag": median_lag is not None
        and median_lag
        <= float(thresholds["median_major_episode_recovery_lag_sessions_max"]),
        "unresolved_major_episodes": unresolved
        <= int(thresholds["unresolved_major_episode_count_max"]),
        "cagr_sacrifice_vs_v4_2": cagr_sacrifice
        <= float(thresholds["full_sample_cagr_sacrifice_vs_v4_2_pp_max"]),
        "maximum_drawdown_vs_v4_2": drawdown_worsening
        <= float(thresholds["maximum_drawdown_vs_v4_2_worsening_pp_max"]),
        "early_segment_improvement_vs_static": early_delta
        >= float(thresholds["early_segment_cagr_delta_vs_static_blended_pp_min"]),
        "late_segment_improvement_vs_static": late_delta
        >= float(thresholds["late_segment_cagr_delta_vs_static_blended_pp_min"]),
        "precursor_event_positive_rate": (
            True
            if not uses_precursor
            else event_positive_rate is not None
            and event_positive_rate
            >= float(thresholds["precursor_event_positive_rate_min"])
        ),
        "precursor_event_concentration": (
            True
            if not uses_precursor
            else largest_event_share is not None
            and largest_event_share
            <= float(thresholds["largest_precursor_event_benefit_share_max"])
        ),
    }
    return {
        "prospective_challenger_authorized": bool(all(checks.values())),
        "direct_promotion_authorized": False,
        "checks": checks,
        "metrics": {
            "major_episode_drawdown_improvement_rate": improvement_rate,
            "median_major_episode_trough_protection_pp": median_protection,
            "median_major_episode_recovery_lag_sessions": median_lag,
            "unresolved_major_episode_count": unresolved,
            "full_sample_cagr_sacrifice_vs_v4_2_pp": cagr_sacrifice,
            "maximum_drawdown_worsening_vs_v4_2_pp": drawdown_worsening,
            "early_segment_cagr_delta_vs_static_blended_pp": early_delta,
            "late_segment_cagr_delta_vs_static_blended_pp": late_delta,
            "precursor_event_positive_rate": event_positive_rate,
            "largest_precursor_event_benefit_share": largest_event_share,
        },
    }


def run_sgov_recovery_release_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    release_contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run all three frozen recovery-release ablations."""

    _, bridge_results, _, _ = run_bridge_allocation_comparison(bars, bridge_contract)
    reference = _common_reference_daily(bridge_results[V4_2_KEY], bars)
    v4_2 = run_state_weight_backtest(reference, sgov_contract, "current_v4_2")
    static_blended = run_state_weight_backtest(
        reference, sgov_contract, "qqqi_sgov_blended_defense"
    )
    static_blended.metrics["strategy"] = "static_blended"
    static_blended.name = "static_blended"

    results: dict[str, StrategyResult] = {
        "current_v4_2": v4_2,
        "static_blended": static_blended,
    }
    for variant in (
        "qqqi_release_on_state_1",
        "tqqq_release_on_precursor",
        "staged_qqqi_then_tqqq_release",
    ):
        results[variant] = run_recovery_release_backtest(
            reference, release_contract, variant
        )

    baseline_states = v4_2.daily["position_state"].astype(int)
    for key, result in results.items():
        if not baseline_states.equals(result.daily["position_state"].astype(int)):
            raise AssertionError(f"{key} changed the frozen v4.2 state trace")
        state_two = result.daily.loc[result.daily["position_state"].eq(2)]
        if not (
            np.allclose(state_two["weight_QQQ"], 0.25)
            and np.allclose(state_two["weight_TQQQ"], 0.75)
            and np.allclose(state_two["weight_QQQI"], 0.0)
            and np.allclose(state_two["weight_SGOV"], 0.0)
        ):
            raise AssertionError(f"{key} changed the frozen state-2 allocation")

    headline = pd.DataFrame(
        [dict(result.metrics) for result in results.values()]
    ).set_index("strategy")
    train_fraction = float(
        release_contract["validation"]["chronological_train_fraction"]
    )
    chronological = pd.DataFrame(
        [
            row
            for result in results.values()
            for row in _chronological_metrics(result, train_fraction)
        ]
    )
    horizons = [int(value) for value in release_contract["validation"]["event_horizons"]]
    episodes: dict[str, pd.DataFrame] = {}
    precursor_events: dict[str, pd.DataFrame] = {}
    gates: dict[str, Any] = {}
    for variant in (
        "static_blended",
        "qqqi_release_on_state_1",
        "tqqq_release_on_precursor",
        "staged_qqqi_then_tqqq_release",
    ):
        episode_table, _ = attribute_sgov_drawdown_episodes_at_baseline_trough(
            v4_2,
            results[variant],
            attribution_contract,
        )
        episodes[variant] = episode_table
        events = _precursor_episode_rows(results[variant], static_blended, horizons)
        precursor_events[variant] = events
        if variant != "static_blended":
            gates[variant] = _candidate_gate(
                results[variant],
                v4_2,
                static_blended,
                episode_table,
                chronological,
                events,
                release_contract,
                uses_precursor=bool(
                    release_contract["variants"][variant]["use_tqqq_precursor"]
                ),
            )

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "same_v4_2_state_trace": True,
        "same_state_2_allocation": True,
        "cost_bps_per_turnover_unit": float(
            release_contract["boundaries"][
                "transaction_cost_bps_per_turnover_unit"
            ]
        ),
        "common_sample_start": reference.index.min().date().isoformat(),
        "common_sample_end": reference.index.max().date().isoformat(),
        "observations": int(len(reference)),
        "tail_risk": {
            key: tail_risk_metrics(result) for key, result in results.items()
        },
        "candidate_gates": gates,
        "authorized_candidates": [
            key
            for key, gate in gates.items()
            if bool(gate["prospective_challenger_authorized"])
        ],
        "direct_promotion_authorized": False,
    }
    return (
        headline.sort_index(),
        results,
        chronological,
        episodes,
        precursor_events,
        diagnostics,
    )
