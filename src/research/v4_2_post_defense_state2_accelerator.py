"""Post-defense formal-state-2 TQQQ accelerator for the QQQ v4.2 family.

The experiment reuses the frozen RSI×VIX defense trace from v4.9. A completed
defense episode arms one accelerator opportunity. Only the first subsequent
executed formal v4.2 state-2 episode receives 100% TQQQ; the arm is consumed at
entry and all later state-2 episodes remain at the ordinary 25% QQQ / 75% TQQQ
allocation until another defense episode completes.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_rsi_vix_sgov_experiment import (
    _opportunity_metrics,
    run_rsi_vix_sgov_comparison,
)
from src.research.v4_2_sgov_defense_experiment import (
    ASSETS,
    _chronological_metrics,
)
from src.research.v4_2_sgov_episode_attribution_corrected import (
    attribute_sgov_drawdown_episodes_at_baseline_trough,
)


BASELINE = "current_v4_2"
DEFENSE_ONLY = "rsi_vix_adaptive_sgov"
TAG_ONLY = "post_defense_state2_accelerator_tag_only"
COMBINED = "rsi_vix_defense_state2_accelerator"


def build_single_use_accelerator_trace(
    daily: pd.DataFrame,
) -> pd.DataFrame:
    """Create the deterministic arm/consume trace on executed sessions.

    ``overlay_active_at_close`` is shifted once to obtain the raw defense state
    effective at the next open. A true-to-false transition arms one opportunity.
    The first later executed state-2 episode consumes the arm and remains
    accelerated until the executed state leaves 2. A new defense activation
    cancels any stale arm.
    """

    required = {"position_state", "overlay_active_at_close"}
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"daily trace missing required columns: {missing}")
    if not daily.index.is_monotonic_increasing or daily.index.has_duplicates:
        raise ValueError("daily trace index must be monotonic and unique")

    raw_defense_at_open = (
        daily["overlay_active_at_close"].shift(1).fillna(False).astype(bool)
    )
    previous_raw_defense = raw_defense_at_open.shift(1, fill_value=False)
    defense_activation_execution = raw_defense_at_open & ~previous_raw_defense
    defense_release_execution = ~raw_defense_at_open & previous_raw_defense

    armed = False
    accelerating = False
    arm_id = 0
    current_arm_id: int | None = None
    current_release_execution: pd.Timestamp | None = None

    armed_rows: list[bool] = []
    accelerating_rows: list[bool] = []
    arm_ids: list[int | None] = []
    release_execution_dates: list[pd.Timestamp | None] = []
    reasons: list[str] = []

    for date, state, activation, release, defense_active in zip(
        daily.index,
        daily["position_state"].astype(int),
        defense_activation_execution,
        defense_release_execution,
        raw_defense_at_open,
        strict=True,
    ):
        reason = "hold_unarmed"
        if accelerating and (int(state) != 2 or bool(defense_active)):
            accelerating = False
            reason = "accelerator_exit"

        if bool(activation):
            armed = False
            current_arm_id = None
            current_release_execution = None
            if accelerating:
                accelerating = False
            reason = "defense_activation_resets_arm"

        if bool(release):
            arm_id += 1
            armed = True
            current_arm_id = arm_id
            current_release_execution = pd.Timestamp(date)
            reason = "defense_release_arms"

        if (
            not accelerating
            and armed
            and int(state) == 2
            and not bool(defense_active)
        ):
            accelerating = True
            armed = False
            reason = "formal_state2_consumes_arm"

        if accelerating:
            reason = (
                "formal_state2_consumes_arm"
                if reason == "formal_state2_consumes_arm"
                else "hold_accelerating"
            )
        elif armed and reason == "hold_unarmed":
            reason = "hold_armed"

        armed_rows.append(bool(armed))
        accelerating_rows.append(bool(accelerating))
        arm_ids.append(current_arm_id)
        release_execution_dates.append(current_release_execution)
        reasons.append(reason)

        if not accelerating and not armed and reason == "accelerator_exit":
            current_arm_id = None
            current_release_execution = None

    trace = pd.DataFrame(
        {
            "raw_defense_active_at_open": raw_defense_at_open,
            "defense_activation_execution": defense_activation_execution,
            "defense_release_execution": defense_release_execution,
            "accelerator_armed": pd.Series(armed_rows, index=daily.index, dtype=bool),
            "accelerator_active": pd.Series(
                accelerating_rows, index=daily.index, dtype=bool
            ),
            "accelerator_arm_id": pd.Series(arm_ids, index=daily.index, dtype="Int64"),
            "arm_release_execution_date": release_execution_dates,
            "accelerator_reason": reasons,
        },
        index=daily.index,
    )
    if bool(
        trace.loc[trace["accelerator_active"], "raw_defense_active_at_open"].any()
    ):
        raise AssertionError("accelerator cannot overlap raw defense at execution")
    if bool(
        daily.loc[trace["accelerator_active"], "position_state"].astype(int).ne(2).any()
    ):
        raise AssertionError("accelerator appeared outside formal state 2")
    return trace


def _candidate_weights(
    source: StrategyResult,
    trace: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Copy source weights and replace only accelerated state-2 sessions."""

    weights = source.daily[
        ["weight_QQQI", "weight_QQQ", "weight_TQQQ", "weight_SGOV"]
    ].rename(
        columns={
            "weight_QQQI": "QQQI",
            "weight_QQQ": "QQQ",
            "weight_TQQQ": "TQQQ",
            "weight_SGOV": "SGOV",
        }
    ).copy()
    acceleration = trace["accelerator_active"].reindex(weights.index).fillna(False)
    target = {
        asset: float(contract["allocations"]["accelerated_state_2"].get(asset, 0.0))
        for asset in ASSETS
    }
    if not np.isclose(sum(target.values()), 1.0):
        raise ValueError("accelerated state-2 allocation must sum to one")
    for asset, value in target.items():
        weights.loc[acceleration, asset] = value

    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("candidate weights must sum to one")
    if bool((weights < -1e-12).any().any()):
        raise AssertionError("candidate weights cannot be negative")
    non_accelerated_state_two = (
        source.daily["position_state"].astype(int).eq(2) & ~acceleration
    )
    if bool(non_accelerated_state_two.any()):
        if not (
            np.allclose(weights.loc[non_accelerated_state_two, "QQQ"], 0.25)
            and np.allclose(weights.loc[non_accelerated_state_two, "TQQQ"], 0.75)
            and np.allclose(weights.loc[non_accelerated_state_two, "QQQI"], 0.0)
            and np.allclose(weights.loc[non_accelerated_state_two, "SGOV"], 0.0)
        ):
            raise AssertionError("ordinary state-2 allocation drifted")
    return weights


def run_accelerated_backtest(
    source: StrategyResult,
    trace: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    strategy_key: str,
) -> StrategyResult:
    """Apply the same accelerator trace to one pre-state-2 allocation source."""

    daily = source.daily.copy()
    trace = trace.reindex(daily.index)
    if trace.index.intersection(daily.index).empty:
        raise ValueError("accelerator trace does not overlap source daily data")
    daily = daily.join(trace)
    weights = _candidate_weights(source, trace, contract)
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]

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
    weight_changes = weights.loc[daily.index].ne(
        weights.loc[daily.index].shift()
    ).any(axis=1)
    metrics.update(
        {
            "strategy": strategy_key,
            "switch_count": int(max(int(weight_changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "accelerated_sessions": int(daily["accelerator_active"].sum()),
            "accelerator_event_count": int(
                (
                    daily["accelerator_active"]
                    & ~daily["accelerator_active"].shift(1, fill_value=False)
                ).sum()
            ),
            "average_sgov_weight": float(daily["weight_SGOV"].mean()),
            "average_qqqi_weight": float(daily["weight_QQQI"].mean()),
            "average_qqq_weight": float(daily["weight_QQQ"].mean()),
            "average_tqqq_weight": float(daily["weight_TQQQ"].mean()),
        }
    )
    trade_columns = [
        "position_state",
        "position_label",
        "executed_reason",
        "raw_defense_active_at_open",
        "defense_activation_execution",
        "defense_release_execution",
        "accelerator_armed",
        "accelerator_active",
        "accelerator_arm_id",
        "arm_release_execution_date",
        "accelerator_reason",
        "rsi_14",
        "vix_close",
        "vix_regime",
        "weight_QQQI",
        "weight_QQQ",
        "weight_TQQQ",
        "weight_SGOV",
        "turnover_units",
        "transaction_cost",
    ]
    trades = daily.loc[weight_changes, trade_columns].reset_index(names="date")
    return StrategyResult(strategy_key, daily, trades, metrics)


def _compounded(series: pd.Series) -> float:
    clean = series.dropna().astype(float)
    return float((1.0 + clean).prod() - 1.0) if len(clean) else 0.0


def accelerator_episode_attribution(
    candidate: StrategyResult,
    ordinary: StrategyResult,
    *,
    horizons: Sequence[int] = (1, 2, 3, 5, 10),
) -> pd.DataFrame:
    """Attribute each contiguous accelerated formal-state-2 episode."""

    daily = candidate.daily
    active = daily["accelerator_active"].astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    rows: list[dict[str, Any]] = []
    for event_number, entry_date in enumerate(daily.index[starts], start=1):
        start = int(daily.index.get_loc(entry_date))
        end = start
        while end + 1 < len(daily) and bool(active.iloc[end + 1]):
            end += 1
        exit_date = daily.index[end]
        window = daily.iloc[start : end + 1]
        ordinary_window = ordinary.daily.reindex(window.index)
        qqq_path = (1.0 + window["QQQ_next_open_return"]).cumprod() - 1.0
        tqqq_path = (1.0 + window["TQQQ_next_open_return"]).cumprod() - 1.0

        release_execution = window.iloc[0]["arm_release_execution_date"]
        release_execution_date = (
            pd.Timestamp(release_execution)
            if pd.notna(release_execution)
            else pd.NaT
        )
        release_signal_date = pd.NaT
        if pd.notna(release_execution_date):
            location = daily.index.get_indexer([release_execution_date])[0]
            if location > 0:
                release_signal_date = daily.index[location - 1]

        entry_location = start
        state2_signal_date = (
            daily.index[entry_location - 1] if entry_location > 0 else pd.NaT
        )
        next_state = (
            int(daily.iloc[end + 1]["position_state"])
            if end + 1 < len(daily)
            else None
        )
        candidate_return = _compounded(window["net_return"])
        ordinary_return = _compounded(ordinary_window["net_return"])
        row: dict[str, Any] = {
            "event_id": f"accelerator_{event_number:03d}",
            "arm_id": (
                int(window.iloc[0]["accelerator_arm_id"])
                if pd.notna(window.iloc[0]["accelerator_arm_id"])
                else None
            ),
            "defense_release_signal_date": release_signal_date,
            "defense_release_execution_date": release_execution_date,
            "state2_signal_date": state2_signal_date,
            "state2_entry_date": entry_date,
            "state2_exit_date": exit_date,
            "accelerated_sessions": int(end - start + 1),
            "next_executed_state": next_state,
            "candidate_return": candidate_return,
            "ordinary_75_tqqq_return": ordinary_return,
            "marginal_return": float(
                np.exp(
                    np.log1p(window["net_return"]).sum()
                    - np.log1p(ordinary_window["net_return"]).sum()
                )
                - 1.0
            ),
            "qqq_episode_return": _compounded(window["QQQ_next_open_return"]),
            "tqqq_episode_return": _compounded(window["TQQQ_next_open_return"]),
            "qqq_mfe": float(qqq_path.max()) if len(qqq_path) else None,
            "qqq_mae": float(qqq_path.min()) if len(qqq_path) else None,
            "tqqq_mfe": float(tqqq_path.max()) if len(tqqq_path) else None,
            "tqqq_mae": float(tqqq_path.min()) if len(tqqq_path) else None,
        }
        for horizon in horizons:
            stop = start + int(horizon)
            for symbol in ("QQQ", "TQQQ"):
                values = daily[f"{symbol}_next_open_return"].iloc[start:stop]
                row[f"{symbol.lower()}_return_{horizon}d"] = (
                    _compounded(values) if len(values) == int(horizon) else np.nan
                )
        rows.append(row)
    return pd.DataFrame(rows)


def _accelerator_summary(events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {
            "event_count": 0,
            "positive_event_count": 0,
            "positive_event_rate": None,
            "largest_positive_event_share": 1.0,
            "total_positive_marginal_return": 0.0,
            "total_negative_marginal_return": 0.0,
        }
    marginal = events["marginal_return"].astype(float)
    positive = marginal.clip(lower=0.0)
    negative = marginal.clip(upper=0.0)
    positive_sum = float(positive.sum())
    return {
        "event_count": int(len(events)),
        "positive_event_count": int(marginal.gt(0.0).sum()),
        "positive_event_rate": float(marginal.gt(0.0).mean()),
        "largest_positive_event_share": (
            float(positive.max() / positive_sum) if positive_sum > 0.0 else 1.0
        ),
        "total_positive_marginal_return": positive_sum,
        "total_negative_marginal_return": float(negative.sum()),
        "median_marginal_return": float(marginal.median()),
    }


def _scope_gate(
    baseline: StrategyResult,
    defense: StrategyResult,
    candidate: StrategyResult,
    chronological: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["promotion_gate"]
    baseline_tail = tail_risk_metrics(baseline)
    candidate_tail = tail_risk_metrics(candidate)
    baseline_cagr = float(baseline.metrics["cagr"])
    defense_cagr = float(defense.metrics["cagr"])
    candidate_cagr = float(candidate.metrics["cagr"])
    sacrifice = baseline_cagr - candidate_cagr
    defense_sacrifice = baseline_cagr - defense_cagr
    recovered_fraction = (
        (candidate_cagr - defense_cagr) / defense_sacrifice
        if defense_sacrifice > 0.0
        else 0.0
    )
    max_drawdown_improvement_pp = (
        float(candidate.metrics["max_drawdown"])
        - float(baseline.metrics["max_drawdown"])
    ) * 100.0
    chrono = chronological.set_index(["strategy", "segment"])
    late_candidate_calmar = float(chrono.loc[(COMBINED, "late"), "calmar"])
    late_baseline_calmar = float(chrono.loc[(BASELINE, "late"), "calmar"])
    event_summary = _accelerator_summary(events)
    turnover_limit = float(baseline.metrics["turnover_units"]) * (
        1.0 + float(thresholds["turnover_increase_max"])
    )
    worst_20d_delta_pp = (
        float(candidate_tail["worst_20d_return"])
        - float(baseline_tail["worst_20d_return"])
    ) * 100.0
    checks = {
        "max_drawdown_improvement": max_drawdown_improvement_pp
        >= float(thresholds["max_drawdown_improvement_pp_min"]),
        "cagr_gap": sacrifice * 100.0
        <= float(thresholds["cagr_gap_pp_max"]),
        "defense_cagr_sacrifice_recovered": recovered_fraction
        >= float(thresholds["defense_cagr_sacrifice_recovered_min"]),
        "full_sample_calmar": float(candidate.metrics["calmar"])
        >= float(baseline.metrics["calmar"]),
        "late_segment_calmar": late_candidate_calmar >= late_baseline_calmar,
        "worst_20d": worst_20d_delta_pp
        >= -float(thresholds["worst_20d_worsening_pp_max"]),
        "accelerator_event_positive_rate": (
            event_summary["positive_event_rate"] is not None
            and float(event_summary["positive_event_rate"])
            >= float(thresholds["accelerator_event_positive_rate_min"])
        ),
        "event_concentration": float(event_summary["largest_positive_event_share"])
        <= float(thresholds["largest_positive_event_share_max"]),
        "turnover": float(candidate.metrics["turnover_units"]) <= turnover_limit,
    }
    return {
        "checks": checks,
        "metrics": {
            "max_drawdown_improvement_pp": max_drawdown_improvement_pp,
            "cagr_gap_pp": sacrifice * 100.0,
            "defense_cagr_sacrifice_pp": defense_sacrifice * 100.0,
            "defense_cagr_sacrifice_recovered_fraction": recovered_fraction,
            "late_candidate_calmar": late_candidate_calmar,
            "late_baseline_calmar": late_baseline_calmar,
            "worst_20d_delta_pp": worst_20d_delta_pp,
            "turnover_limit": turnover_limit,
            "accelerator_event_summary": event_summary,
        },
        "scope_checks_pass": bool(all(checks.values())),
    }


def run_post_defense_state2_accelerator_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    defense_contract: Mapping[str, Any],
    accelerator_contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run v4.2, defense-only, tag-only and defense-plus-accelerator."""

    _, inherited_results, _, inherited_episodes, inherited_diagnostics = (
        run_rsi_vix_sgov_comparison(
            bars,
            bridge_contract,
            sgov_contract,
            attribution_contract,
            defense_contract,
        )
    )
    baseline = inherited_results[BASELINE]
    defense = inherited_results[DEFENSE_ONLY]
    trace = build_single_use_accelerator_trace(defense.daily)

    tag_only = run_accelerated_backtest(
        baseline,
        trace,
        accelerator_contract,
        strategy_key=TAG_ONLY,
    )
    combined = run_accelerated_backtest(
        defense,
        trace,
        accelerator_contract,
        strategy_key=COMBINED,
    )
    results = {
        BASELINE: baseline,
        DEFENSE_ONLY: defense,
        TAG_ONLY: tag_only,
        COMBINED: combined,
    }
    baseline_states = baseline.daily["position_state"].astype(int)
    for key, result in results.items():
        if not baseline_states.equals(result.daily["position_state"].astype(int)):
            raise AssertionError(f"{key} changed the frozen v4.2 state trace")

    headline = pd.DataFrame(
        [dict(result.metrics) for result in results.values()]
    ).set_index("strategy")
    fraction = float(
        accelerator_contract["validation"]["chronological_train_fraction"]
    )
    chronological = pd.DataFrame(
        [
            row
            for result in results.values()
            for row in _chronological_metrics(result, fraction)
        ]
    )
    tag_events = accelerator_episode_attribution(
        tag_only,
        baseline,
        horizons=accelerator_contract["validation"]["event_horizons"],
    )
    combined_events = accelerator_episode_attribution(
        combined,
        defense,
        horizons=accelerator_contract["validation"]["event_horizons"],
    )
    drawdowns, _ = attribute_sgov_drawdown_episodes_at_baseline_trough(
        baseline, combined, attribution_contract
    )
    gate = _scope_gate(
        baseline,
        defense,
        combined,
        chronological,
        combined_events,
        accelerator_contract,
    )
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "same_v4_2_state_trace": True,
        "defense_trace_reused_without_change": True,
        "sample": {
            "start": baseline.daily.index.min().date().isoformat(),
            "end": baseline.daily.index.max().date().isoformat(),
            "observations": int(len(baseline.daily)),
        },
        "tail_risk": {
            key: tail_risk_metrics(result) for key, result in results.items()
        },
        "opportunity_metrics": {
            key: _opportunity_metrics(result) for key, result in results.items()
        },
        "accelerator_summary": {
            TAG_ONLY: _accelerator_summary(tag_events),
            COMBINED: _accelerator_summary(combined_events),
        },
        "scope_gate": gate,
        "inherited_v4_9_decision": inherited_diagnostics["decision"],
        "direct_promotion_authorized": False,
    }
    episodes = {
        "accelerator_tag_only": tag_events,
        "accelerator_combined": combined_events,
        "drawdown_combined": drawdowns,
        "inherited_defense_overlay": inherited_episodes[
            "overlay_rsi_vix_adaptive_sgov"
        ],
    }
    return headline.sort_index(), results, chronological, episodes, diagnostics
