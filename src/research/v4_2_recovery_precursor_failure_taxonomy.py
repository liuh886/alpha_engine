"""Failure taxonomy for frozen v4.2 recovery-precursor events.

This module is diagnostic. It reuses the governed QQQ-proxy experiment, records
features that were observable at the signal close or next-session open, and
describes successful and failed 50%-versus-25% TQQQ precursor episodes without
fitting a classifier or changing any production rule.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.v4_2_qqq_proxy_long_history_experiment import (
    run_qqq_proxy_long_history_comparison,
)
from src.research.v4_2_sgov_precursor_50_experiment import BOLD_KEY, PRIOR_KEY


def _cumulative_return(series: pd.Series, start: int, horizon: int) -> float:
    values = series.iloc[start : start + horizon].dropna()
    if len(values) != horizon:
        return float("nan")
    return float((1.0 + values.astype(float)).prod() - 1.0)


def _excursion(series: pd.Series, start: int, horizon: int) -> tuple[float, float]:
    values = series.iloc[start : start + horizon].dropna()
    if values.empty:
        return float("nan"), float("nan")
    path = (1.0 + values.astype(float)).cumprod() - 1.0
    return float(path.max()), float(path.min())


def _state_run_context(
    states: pd.Series,
    position: int,
    target_state: int,
) -> tuple[int, int | None]:
    cursor = position
    while cursor >= 0 and int(states.iloc[cursor]) == target_state:
        cursor -= 1
    age = position - cursor
    previous_state = int(states.iloc[cursor]) if cursor >= 0 else None
    return int(age), previous_state


def _shock_memory_context(
    daily: pd.DataFrame,
    signal_position: int,
    trigger_drawdown: float,
    memory_sessions: int,
) -> tuple[int | None, int | None]:
    history = daily["shock_drawdown_now"].iloc[: signal_position + 1].astype(float)
    triggers = np.flatnonzero(history.to_numpy() <= -abs(float(trigger_drawdown)))
    if not len(triggers):
        return None, None
    age = int(signal_position - int(triggers[-1]))
    return age, int(max(memory_sessions - age, 0))


def _first_transition(
    states: pd.Series,
    start: int,
    horizon: int,
) -> tuple[int | None, int | None, str]:
    state_2: int | None = None
    state_0: int | None = None
    stop = min(len(states), start + horizon)
    for location in range(start, stop):
        state = int(states.iloc[location])
        offset = int(location - start)
        if state == 2 and state_2 is None:
            state_2 = offset
        if state == 0 and state_0 is None:
            state_0 = offset
    if state_2 is not None and (state_0 is None or state_2 < state_0):
        outcome = "state2_before_state0"
    elif state_0 is not None and (state_2 is None or state_0 < state_2):
        outcome = "state0_before_state2"
    else:
        outcome = "neither_within_horizon"
    return state_2, state_0, outcome


def _segment_bounds(chronological: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    rows = chronological.loc[
        (chronological["strategy"] == BOLD_KEY)
        & (chronological["segment"].isin(["early", "late"]))
    ].copy()
    if len(rows) != 2:
        raise ValueError("expected one early and one late chronological row")
    early_end = pd.Timestamp(rows.loc[rows["segment"] == "early", "end_date"].iloc[0])
    late_start = pd.Timestamp(rows.loc[rows["segment"] == "late", "start_date"].iloc[0])
    return early_end, late_start


def build_recovery_event_taxonomy(
    proxy_result: Mapping[str, Any],
    baseline_contract: Mapping[str, Any],
    taxonomy_contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Build one governed feature and outcome row per proxy precursor event."""

    bold = proxy_result["proxy_results"][BOLD_KEY]
    prior = proxy_result["proxy_results"][PRIOR_KEY]
    if not bold.daily["precursor_active"].astype(bool).equals(
        prior.daily["precursor_active"].astype(bool)
    ):
        raise AssertionError("25% and 50% precursor dates diverged")

    daily = bold.daily.copy()
    daily.index = pd.to_datetime(daily.index)
    events = proxy_result["proxy_marginal_events"].copy()
    for column in ("start_date", "end_date"):
        events[column] = pd.to_datetime(events[column])
    early_end, late_start = _segment_bounds(proxy_result["proxy_chronological"])

    horizons = [int(value) for value in taxonomy_contract["analysis"]["event_horizons"]]
    excursion_horizon = int(taxonomy_contract["analysis"]["excursion_horizon"])
    transition_horizon = int(taxonomy_contract["analysis"]["transition_horizon"])
    price_logic = baseline_contract["price_logic"]
    trigger_drawdown = float(price_logic["shock_drawdown"])
    memory_sessions = int(price_logic["shock_memory_sessions"])

    rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        execution_date = pd.Timestamp(event.start_date)
        if execution_date not in daily.index:
            raise ValueError(f"event start missing from daily trace: {execution_date}")
        execution_position = int(daily.index.get_loc(execution_date))
        if execution_position == 0:
            raise ValueError("event has no prior signal-close row")
        signal_position = execution_position - 1
        signal = daily.iloc[signal_position]
        execution = daily.iloc[execution_position]

        state_age, previous_decision_state = _state_run_context(
            daily["decision_state"],
            signal_position,
            target_state=1,
        )
        shock_age, shock_remaining = _shock_memory_context(
            daily,
            signal_position,
            trigger_drawdown=trigger_drawdown,
            memory_sessions=memory_sessions,
        )
        time_to_state_2, time_to_state_0, transition_outcome = _first_transition(
            daily["position_state"],
            execution_position,
            transition_horizon,
        )
        qqq_mfe, qqq_mae = _excursion(
            daily["QQQ_next_open_return"],
            execution_position,
            excursion_horizon,
        )
        tqqq_mfe, tqqq_mae = _excursion(
            daily["TQQQ_next_open_return"],
            execution_position,
            excursion_horizon,
        )

        marginal_success = bool(float(event.event_relative_return) > 0.0)
        if marginal_success:
            failure_type = "successful_recovery"
        elif transition_outcome == "state0_before_state2":
            failure_type = "failed_recovery_reverted_before_state2"
        else:
            failure_type = "failed_recovery_reached_state2_but_extra_leverage_lost"

        segment = (
            "early"
            if execution_date <= early_end
            else "late"
            if execution_date >= late_start
            else "boundary"
        )
        row: dict[str, Any] = {
            "event_id": event.event_id,
            "signal_close_date": daily.index[signal_position],
            "execution_date": execution_date,
            "event_end_date": pd.Timestamp(event.end_date),
            "chronological_segment": segment,
            "event_sessions": int(event.sessions),
            "marginal_50_vs_25_return": float(event.event_relative_return),
            "marginal_success": marginal_success,
            "failure_type": failure_type,
            "shock_memory_age_sessions": shock_age,
            "shock_memory_remaining_sessions": shock_remaining,
            "qqq_distance_ma_short": float(signal["qqq_close"] / signal["ma_short"] - 1.0),
            "qqq_distance_ma_medium": float(
                signal["qqq_close"] / signal["ma_medium"] - 1.0
            ),
            "qqq_distance_ma_long": float(signal["qqq_close"] / signal["ma_long"] - 1.0),
            "qqq_drawdown_at_signal": float(signal["drawdown"]),
            "qqq_return_63d_at_signal": float(signal["return_63d"]),
            "breakout_early_at_signal": bool(signal["breakout_early"]),
            "breakout_confirm_at_signal": bool(signal["breakout_confirm"]),
            "ma_short_rising_at_signal": bool(signal["ma_short_rising"]),
            "vix_close": float(signal["vix_close"]),
            "vix_normalization_margin": float(
                (signal["vix_q_normal"] - signal["vix_close"])
                / signal["vix_q_normal"]
            ),
            "vix_stress_margin": float(
                (signal["vix_q_stress"] - signal["vix_close"])
                / signal["vix_q_stress"]
            ),
            "vix_return_1d": float(signal["vix_return_1d"]),
            "vix_return_5d": float(signal["vix_return_5d"]),
            "vix_retreat_from_peak": float(signal["vix_retreat_from_peak"]),
            "vix_falling": bool(signal["vix_falling"]),
            "vxn_close": float(signal["vxn_close"]),
            "vxn_normalization_margin": float(
                (signal["vxn_q_normal"] - signal["vxn_close"])
                / signal["vxn_q_normal"]
            ),
            "vxn_stress_margin": float(
                (signal["vxn_q_stress"] - signal["vxn_close"])
                / signal["vxn_q_stress"]
            ),
            "vxn_return_1d": float(signal["vxn_return_1d"]),
            "vxn_return_5d": float(signal["vxn_return_5d"]),
            "vxn_retreat_from_peak": float(signal["vxn_retreat_from_peak"]),
            "vxn_falling": bool(signal["vxn_falling"]),
            "state_1_decision_age_sessions": state_age,
            "previous_decision_state": previous_decision_state,
            "position_state_at_signal_close": int(signal["position_state"]),
            "fresh_state_1_transition": bool(
                int(signal["position_state"]) != 1 and int(signal["decision_state"]) == 1
            ),
            "qqq_open_gap_at_execution": float(
                execution["QQQ_open"] / signal["QQQ_close"] - 1.0
            ),
            "tqqq_open_gap_at_execution": float(
                execution["TQQQ_open"] / signal["TQQQ_close"] - 1.0
            ),
            "time_to_formal_state_2_sessions": time_to_state_2,
            "time_to_revert_state_0_sessions": time_to_state_0,
            "transition_outcome": transition_outcome,
            "qqq_mfe_40d": qqq_mfe,
            "qqq_mae_40d": qqq_mae,
            "tqqq_mfe_40d": tqqq_mfe,
            "tqqq_mae_40d": tqqq_mae,
        }
        for horizon in horizons:
            row[f"qqq_return_{horizon}d"] = _cumulative_return(
                daily["QQQ_next_open_return"],
                execution_position,
                horizon,
            )
            row[f"tqqq_return_{horizon}d"] = _cumulative_return(
                daily["TQQQ_next_open_return"],
                execution_position,
                horizon,
            )
        rows.append(row)

    taxonomy = pd.DataFrame(rows).sort_values("execution_date").reset_index(drop=True)
    if int(taxonomy["event_id"].nunique()) != len(events):
        raise AssertionError("taxonomy lost or duplicated proxy events")
    return taxonomy


def _pairwise_probability(success: pd.Series, failure: pd.Series) -> float:
    if success.empty or failure.empty:
        return float("nan")
    left = success.to_numpy(dtype=float)[:, None]
    right = failure.to_numpy(dtype=float)[None, :]
    return float((left > right).mean() + 0.5 * (left == right).mean())


def _median_gap(frame: pd.DataFrame, feature: str) -> float:
    success = frame.loc[frame["marginal_success"], feature].dropna().astype(float)
    failure = frame.loc[~frame["marginal_success"], feature].dropna().astype(float)
    if success.empty or failure.empty:
        return float("nan")
    return float(success.median() - failure.median())


def _loo_rows(frame: pd.DataFrame, feature: str, segment: str) -> list[dict[str, Any]]:
    full_gap = _median_gap(frame, feature)
    full_sign = float(np.sign(full_gap)) if np.isfinite(full_gap) else float("nan")
    rows: list[dict[str, Any]] = []
    for event_id in frame["event_id"]:
        subset = frame.loc[frame["event_id"] != event_id]
        gap = _median_gap(subset, feature)
        rows.append(
            {
                "feature": feature,
                "segment": segment,
                "excluded_event_id": event_id,
                "median_gap_success_minus_failure": gap,
                "same_direction_as_full_segment": bool(
                    np.isfinite(gap)
                    and np.isfinite(full_sign)
                    and np.sign(gap) == full_sign
                ),
            }
        )
    return rows


def feature_separation_analysis(
    taxonomy: pd.DataFrame,
    taxonomy_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare successful and failed events without fitting thresholds."""

    features = list(taxonomy_contract["analysis"]["pre_execution_numeric_features"])
    missing = sorted(set(features) - set(taxonomy.columns))
    if missing:
        raise ValueError(f"taxonomy missing configured features: {missing}")

    separation_rows: list[dict[str, Any]] = []
    loo_rows: list[dict[str, Any]] = []
    for feature in features:
        full = taxonomy
        early = taxonomy.loc[taxonomy["chronological_segment"] == "early"]
        late = taxonomy.loc[taxonomy["chronological_segment"] == "late"]
        full_success = full.loc[full["marginal_success"], feature].dropna().astype(float)
        full_failure = full.loc[~full["marginal_success"], feature].dropna().astype(float)
        early_success = early.loc[early["marginal_success"], feature].dropna().astype(float)
        early_failure = early.loc[~early["marginal_success"], feature].dropna().astype(float)

        full_gap = _median_gap(full, feature)
        early_gap = _median_gap(early, feature)
        full_loo = _loo_rows(full, feature, "full")
        early_loo = _loo_rows(early, feature, "early")
        loo_rows.extend(full_loo)
        loo_rows.extend(early_loo)
        full_stability = float(
            np.mean([row["same_direction_as_full_segment"] for row in full_loo])
        )
        early_stability = float(
            np.mean([row["same_direction_as_full_segment"] for row in early_loo])
        )
        pairwise = _pairwise_probability(full_success, full_failure)
        early_pairwise = _pairwise_probability(early_success, early_failure)
        same_direction = bool(
            np.isfinite(full_gap)
            and np.isfinite(early_gap)
            and np.sign(full_gap) == np.sign(early_gap)
        )
        separation_rows.append(
            {
                "feature": feature,
                "success_count_full": int(len(full_success)),
                "failure_count_full": int(len(full_failure)),
                "success_median_full": (
                    float(full_success.median()) if len(full_success) else np.nan
                ),
                "failure_median_full": (
                    float(full_failure.median()) if len(full_failure) else np.nan
                ),
                "median_gap_full": full_gap,
                "pairwise_probability_success_gt_failure_full": pairwise,
                "loo_direction_stability_full": full_stability,
                "success_count_early": int(len(early_success)),
                "failure_count_early": int(len(early_failure)),
                "success_median_early": (
                    float(early_success.median()) if len(early_success) else np.nan
                ),
                "failure_median_early": (
                    float(early_failure.median()) if len(early_failure) else np.nan
                ),
                "median_gap_early": early_gap,
                "pairwise_probability_success_gt_failure_early": early_pairwise,
                "loo_direction_stability_early": early_stability,
                "success_count_late": int(late["marginal_success"].sum()),
                "failure_count_late": int((~late["marginal_success"]).sum()),
                "same_direction_full_and_early": same_direction,
            }
        )

    separation = pd.DataFrame(separation_rows)
    validation = taxonomy_contract["validation"]
    min_stability = float(validation["minimum_loo_direction_stability"])
    min_pairwise_distance = float(validation["minimum_pairwise_distance_from_half"])
    separation["pairwise_distance_from_half_full"] = (
        separation["pairwise_probability_success_gt_failure_full"] - 0.5
    ).abs()
    separation["descriptively_stable"] = (
        separation["same_direction_full_and_early"]
        & (separation["loo_direction_stability_full"] >= min_stability)
        & (separation["loo_direction_stability_early"] >= min_stability)
        & (
            separation["pairwise_distance_from_half_full"]
            >= min_pairwise_distance
        )
    )
    separation = separation.sort_values(
        ["descriptively_stable", "pairwise_distance_from_half_full"],
        ascending=[False, False],
    ).reset_index(drop=True)
    return separation, pd.DataFrame(loo_rows)


def diagnostic_decision(
    taxonomy: pd.DataFrame,
    separation: pd.DataFrame,
    taxonomy_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a governance decision for diagnostic follow-up only."""

    validation = taxonomy_contract["validation"]
    stable = separation.loc[separation["descriptively_stable"]]
    late = taxonomy.loc[taxonomy["chronological_segment"] == "late"]
    late_has_both_outcomes = bool(late["marginal_success"].nunique() == 2)
    candidate_limit = int(validation["maximum_candidate_monitor_features"])
    candidate_features = stable["feature"].head(candidate_limit).tolist()

    checks = {
        "minimum_event_count": len(taxonomy)
        >= int(validation["minimum_event_count"]),
        "minimum_failed_event_count": int((~taxonomy["marginal_success"]).sum())
        >= int(validation["minimum_failed_event_count"]),
        "minimum_stable_feature_count": len(stable)
        >= int(validation["minimum_stable_feature_count"]),
        "late_segment_contains_success_and_failure": late_has_both_outcomes,
    }
    return {
        "research_only": True,
        "trade_ready": False,
        "model_change_authorized": False,
        "actionable_alert_authorized": False,
        "prospective_feature_monitoring_justified": bool(
            checks["minimum_event_count"]
            and checks["minimum_failed_event_count"]
            and checks["minimum_stable_feature_count"]
        ),
        "new_preregistered_trading_hypothesis_justified": bool(all(checks.values())),
        "checks": checks,
        "metrics": {
            "event_count": int(len(taxonomy)),
            "successful_event_count": int(taxonomy["marginal_success"].sum()),
            "failed_event_count": int((~taxonomy["marginal_success"]).sum()),
            "early_successful_event_count": int(
                taxonomy.loc[
                    taxonomy["chronological_segment"] == "early",
                    "marginal_success",
                ].sum()
            ),
            "early_failed_event_count": int(
                (
                    ~taxonomy.loc[
                        taxonomy["chronological_segment"] == "early",
                        "marginal_success",
                    ]
                ).sum()
            ),
            "late_successful_event_count": int(
                taxonomy.loc[
                    taxonomy["chronological_segment"] == "late",
                    "marginal_success",
                ].sum()
            ),
            "late_failed_event_count": int(
                (
                    ~taxonomy.loc[
                        taxonomy["chronological_segment"] == "late",
                        "marginal_success",
                    ]
                ).sum()
            ),
            "descriptively_stable_feature_count": int(len(stable)),
            "candidate_monitor_features": candidate_features,
            "failure_type_counts": {
                str(key): int(value)
                for key, value in taxonomy["failure_type"].value_counts().items()
            },
        },
        "decision": (
            "preregistered_rule_hypothesis_permitted"
            if all(checks.values())
            else "monitor_features_prospectively_without_new_rule"
        ),
    }


def run_recovery_precursor_failure_taxonomy(
    bars: Mapping[str, pd.DataFrame],
    baseline_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    prior_release_contract: Mapping[str, Any],
    bold_contract: Mapping[str, Any],
    proxy_contract: Mapping[str, Any],
    taxonomy_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the frozen proxy experiment and produce the diagnostic taxonomy."""

    proxy_result = run_qqq_proxy_long_history_comparison(
        bars,
        baseline_contract,
        sgov_contract,
        attribution_contract,
        prior_release_contract,
        bold_contract,
        proxy_contract,
    )
    taxonomy = build_recovery_event_taxonomy(
        proxy_result,
        baseline_contract,
        taxonomy_contract,
    )
    separation, leave_one_out = feature_separation_analysis(
        taxonomy,
        taxonomy_contract,
    )
    decision = diagnostic_decision(taxonomy, separation, taxonomy_contract)
    return {
        "proxy_result": proxy_result,
        "event_taxonomy": taxonomy,
        "feature_separation": separation,
        "leave_one_event_out": leave_one_out,
        "failure_type_summary": (
            taxonomy.groupby(
                ["chronological_segment", "failure_type"],
                dropna=False,
            )
            .agg(
                events=("event_id", "count"),
                median_marginal_return=("marginal_50_vs_25_return", "median"),
                mean_marginal_return=("marginal_50_vs_25_return", "mean"),
            )
            .reset_index()
        ),
        "decision": decision,
    }
