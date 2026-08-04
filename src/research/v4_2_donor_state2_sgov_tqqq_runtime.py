"""Target-safe runtime for the v4.13 donor formal-state2 experiment.

Donor episodes require complete BIL labels. Target episodes do not: they require
only the formal v4.2 state-2 boundary and close-observable entry features. This
separation prevents target prediction coverage from being silently reduced by
cash-label or terminal-return availability.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_2_cross_asset_sgov_tqqq_transfer_runtime import (
    _v4_2_result_on_index,
)
from src.research.v4_2_donor_state2_sgov_tqqq import (
    BASELINE_KEY,
    VARIANTS,
    DonorState2Model,
    _contradiction_gate,
    _donor_gate,
    _primary_gate,
    _scope_index,
    _state_age,
    _target_feature_frame,
    build_donor_state2_panel,
    fit_donor_state2_model,
    predict_target_episodes_walk_forward,
    run_state2_cash_budget,
    state2_episode_attribution,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS as V4_2_ASSETS,
    run_bridge_allocation_comparison,
)


def build_target_state2_prediction_rows(
    baseline_daily: pd.DataFrame,
    feature_frame: pd.DataFrame,
    *,
    features: Sequence[str],
) -> pd.DataFrame:
    """Build every formal state-2 target episode without requiring outcome labels."""

    state = baseline_daily["position_state"].astype(int)
    starts = state.eq(2) & state.shift(1, fill_value=0).ne(2)
    index = baseline_daily.index
    rows: list[dict[str, Any]] = []
    for number, execution_date in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(execution_date))
        if start_location <= 0:
            continue
        end_location = start_location
        while (
            end_location + 1 < len(index)
            and int(state.iloc[end_location + 1]) == 2
        ):
            end_location += 1
        signal_close_date = index[start_location - 1]
        if signal_close_date not in feature_frame.index:
            continue
        signal = feature_frame.loc[signal_close_date]
        if isinstance(signal, pd.DataFrame):
            raise AssertionError("target feature frame contains duplicate dates")
        if signal[list(features)].isna().any():
            continue
        row: dict[str, Any] = {
            "asset_episode_id": f"QQQ_{number:03d}",
            "underlying": "QQQ",
            "leveraged": "TQQQ",
            "signal_close_date": signal_close_date,
            "execution_date": execution_date,
            "episode_end_date": index[end_location],
            "holding_sessions": int(end_location - start_location + 1),
        }
        for feature in features:
            row[str(feature)] = float(signal[str(feature)])
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("no target formal state-2 prediction rows were generated")
    return result.sort_values("execution_date").reset_index(drop=True)


def build_target_state2_predictions(
    bars: Mapping[str, pd.DataFrame],
    baseline: Any,
    breadth: pd.DataFrame,
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    cash: str,
    donor_episodes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build target features, all formal episodes and donor-only probabilities."""

    feature_frame = _target_feature_frame(
        bars, baseline, breadth, bridge_contract, cash
    )
    rows = build_target_state2_prediction_rows(
        baseline.daily,
        feature_frame,
        features=[str(value) for value in contract["features"]],
    )
    predictions = predict_target_episodes_walk_forward(
        rows, donor_episodes, contract
    )
    return predictions, feature_frame


def _overlapping_predictions(
    predictions: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Retain episodes that overlap a scope, including cross-boundary episodes."""

    execution = pd.to_datetime(predictions["execution_date"])
    episode_end = pd.to_datetime(predictions["episode_end_date"])
    selected = predictions.loc[
        episode_end.ge(start) & execution.le(end)
    ].copy()
    if selected.empty:
        raise ValueError("target scope has no overlapping state-2 predictions")
    return selected.sort_values("execution_date").reset_index(drop=True)


def _assert_scope_probability_coverage(
    baseline: Any,
    predictions: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> None:
    """Verify every exact-calendar state-2 date belongs to one predicted episode."""

    state2_dates = index[
        baseline.daily.reindex(index)["position_state"].astype(int).eq(2)
    ]
    covered = pd.Series(False, index=index)
    for episode in predictions.itertuples(index=False):
        covered.loc[
            (covered.index >= pd.Timestamp(episode.execution_date))
            & (covered.index <= pd.Timestamp(episode.episode_end_date))
        ] = True
    missing = state2_dates[~covered.reindex(state2_dates).to_numpy(dtype=bool)]
    if len(missing):
        raise AssertionError(
            f"scope has {len(missing)} state-2 dates without target probabilities"
        )


def run_donor_state2_sgov_tqqq(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[
    DonorState2Model,
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
    dict[str, dict[str, Any]],
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run donor evidence and target-safe state2-only comparisons."""

    required = {str(value) for value in contract["data"]["required_symbols"]}
    missing = sorted(required - set(bars))
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")

    donor_episodes, breadth = build_donor_state2_panel(
        bars, bridge_contract, contract
    )
    model = fit_donor_state2_model(donor_episodes, contract)

    _, actual_base_results, _, _ = run_bridge_allocation_comparison(
        bars, bridge_contract
    )
    _, proxy_base_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    actual_full = actual_base_results[BASELINE_KEY]
    proxy_full = proxy_base_results[BASELINE_KEY]

    proxy_predictions, proxy_feature_frame = build_target_state2_predictions(
        bars,
        proxy_full,
        breadth,
        bridge_contract,
        contract,
        cash=str(contract["data"]["donor_cash_proxy"]),
        donor_episodes=donor_episodes,
    )
    actual_predictions, actual_feature_frame = build_target_state2_predictions(
        bars,
        actual_full,
        breadth,
        bridge_contract,
        contract,
        cash=str(contract["data"]["actual_cash_asset"]),
        donor_episodes=donor_episodes,
    )

    scopes: dict[str, dict[str, Any]] = {
        "primary": {
            "baseline": proxy_full,
            "feature_frame": proxy_feature_frame,
            "predictions": proxy_predictions,
            "start": pd.Timestamp(
                contract["validation"]["primary_target_start"]
            ),
            "end": pd.Timestamp(contract["validation"]["primary_target_end"]),
        },
        "quarantine": {
            "baseline": proxy_full,
            "feature_frame": proxy_feature_frame,
            "predictions": proxy_predictions,
            "start": pd.Timestamp(
                contract["validation"]["quarantine_proxy_start"]
            ),
            "end": pd.Timestamp(
                contract["validation"]["quarantine_proxy_end"]
            ),
        },
        "actual": {
            "baseline": actual_full,
            "feature_frame": actual_feature_frame,
            "predictions": actual_predictions,
            "start": max(
                pd.Timestamp(contract["validation"]["actual_start"]),
                actual_full.daily.index.min(),
            ),
            "end": min(
                actual_full.daily.index.max(),
                actual_feature_frame.index.max(),
            ),
        },
    }

    results_by_scope: dict[str, dict[str, Any]] = {}
    attribution_by_scope: dict[str, pd.DataFrame] = {}
    headline_by_scope: dict[str, pd.DataFrame] = {}
    predictions_by_scope: dict[str, pd.DataFrame] = {}

    for scope, spec in scopes.items():
        cash_returns = spec["feature_frame"]["cash_next_open_return"]
        index = _scope_index(
            spec["baseline"], cash_returns, spec["start"], spec["end"]
        )
        predictions = _overlapping_predictions(
            spec["predictions"], start=spec["start"], end=spec["end"]
        )
        _assert_scope_probability_coverage(
            spec["baseline"], predictions, index
        )
        baseline = _v4_2_result_on_index(
            spec["baseline"], index, contract, "frozen_v4_2"
        )
        scope_results: dict[str, Any] = {"frozen_v4_2": baseline}
        for variant in VARIANTS:
            result = run_state2_cash_budget(
                spec["baseline"],
                cash_returns,
                predictions,
                index,
                contract,
                variant,
            )
            if not baseline.daily["position_state"].equals(
                result.daily["position_state"]
            ):
                raise AssertionError(
                    f"{scope} {variant} changed the v4.2 state trace"
                )
            outside_state2 = baseline.daily["position_state"].astype(int).ne(2)
            for asset in V4_2_ASSETS:
                if not np.allclose(
                    baseline.daily.loc[outside_state2, f"weight_{asset}"],
                    result.daily.loc[outside_state2, f"weight_{asset}"],
                ):
                    raise AssertionError(
                        f"{scope} {variant} changed state0/state1 {asset} weights"
                    )
            scope_results[variant] = result
        results_by_scope[scope] = scope_results
        predictions_by_scope[scope] = predictions
        headline_by_scope[scope] = pd.DataFrame(
            [dict(result.metrics) for result in scope_results.values()]
        ).set_index("strategy")
        attribution_by_scope[scope] = state2_episode_attribution(
            predictions,
            scope_results["state2_joint_donor_budget"],
            baseline,
        )

    donor_gate = _donor_gate(model, contract)
    primary_gate = _primary_gate(
        results_by_scope["primary"],
        attribution_by_scope["primary"],
        contract,
    )
    contradiction_gate = _contradiction_gate(
        results_by_scope["quarantine"],
        results_by_scope["actual"],
        contract,
    )
    shadow = bool(
        donor_gate["passed"]
        and primary_gate["passed"]
        and contradiction_gate["passed"]
    )
    if not donor_gate["passed"]:
        decision = "donor_formal_state2_transfer_signal_not_stable"
    elif not primary_gate["passed"]:
        decision = "state2_cash_budget_does_not_beat_v4_2_primary_window"
    elif not contradiction_gate["passed"]:
        decision = "state2_cash_budget_blocked_by_later_contradiction"
    else:
        decision = "state2_cash_budget_prospective_shadow_supported"

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "post_result_hypothesis": True,
        "target_excluded_from_training": True,
        "target_rows_separated_from_outcome_labels": True,
        "state_trace_unchanged": True,
        "state_0_state_1_allocations_unchanged": True,
        "donor_gate": donor_gate,
        "primary_gate": primary_gate,
        "contradiction_gate": contradiction_gate,
        "scope_samples": {
            scope: {
                "start": results["frozen_v4_2"].daily.index.min(),
                "end": results["frozen_v4_2"].daily.index.max(),
                "observations": int(len(results["frozen_v4_2"].daily)),
                "predicted_episodes": int(len(predictions_by_scope[scope])),
                "bucket_counts": predictions_by_scope[scope][
                    "probability_bucket"
                ].value_counts().to_dict(),
            }
            for scope, results in results_by_scope.items()
        },
        "tail_risk": {
            scope: {
                key: tail_risk_metrics(result)
                for key, result in results.items()
            }
            for scope, results in results_by_scope.items()
        },
        "decision": decision,
        "shadow_candidate_authorized": shadow,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return (
        model,
        predictions_by_scope,
        headline_by_scope,
        results_by_scope,
        attribution_by_scope,
        diagnostics,
    )
