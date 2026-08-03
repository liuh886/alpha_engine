"""Frozen RSI × VIX adaptive SGOV overlay for the QQQI/QQQ/TQQQ v4.2 family.

The module keeps the v4.2 decision trace and state-2 allocation unchanged. It
tests whether a stateful SGOV sleeve can defend states 0/1 during joint price
and volatility deterioration, then release when both repair.
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
from src.research.vix_rotation_experiment import _normalise_close
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)


VARIANTS = (
    "vix_only_adaptive_sgov",
    "rsi_only_adaptive_sgov",
    "rsi_vix_adaptive_sgov",
)


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Return Wilder RSI with an explicit arithmetic seed and recursive smoothing."""

    if period <= 0:
        raise ValueError("period must be positive")
    values = pd.to_numeric(close, errors="coerce").astype(float)
    if not values.index.is_monotonic_increasing:
        raise ValueError("close index must be monotonic increasing")
    if values.index.has_duplicates:
        raise ValueError("close index must be unique")

    delta = values.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    result = pd.Series(np.nan, index=values.index, dtype=float, name=f"rsi_{period}")
    valid = values.notna()
    if int(valid.sum()) <= period:
        return result

    groups = valid.ne(valid.shift(fill_value=False)).cumsum()
    for _, mask in valid.groupby(groups):
        if not bool(mask.iloc[0]):
            continue
        block_index = mask.index[mask]
        if len(block_index) <= period:
            continue
        block_gain = gain.loc[block_index]
        block_loss = loss.loc[block_index]
        avg_gain = float(block_gain.iloc[1 : period + 1].mean())
        avg_loss = float(block_loss.iloc[1 : period + 1].mean())
        seed_index = block_index[period]

        def _rsi_from_averages(current_gain: float, current_loss: float) -> float:
            if np.isclose(current_loss, 0.0):
                return 100.0 if current_gain > 0.0 else 50.0
            if np.isclose(current_gain, 0.0):
                return 0.0
            relative_strength = current_gain / current_loss
            return float(100.0 - 100.0 / (1.0 + relative_strength))

        result.loc[seed_index] = _rsi_from_averages(avg_gain, avg_loss)
        for location in range(period + 1, len(block_index)):
            current_index = block_index[location]
            avg_gain = (
                avg_gain * (period - 1) + float(block_gain.loc[current_index])
            ) / period
            avg_loss = (
                avg_loss * (period - 1) + float(block_loss.loc[current_index])
            ) / period
            result.loc[current_index] = _rsi_from_averages(avg_gain, avg_loss)
    return result


def _overlay_close_trace(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    variant: str,
) -> pd.DataFrame:
    """Build the close-decided overlay trace before next-open shifting."""

    if variant not in VARIANTS:
        raise ValueError(f"unknown overlay variant: {variant}")
    required = {"rsi_14", "vix_stress", "vix_easing", "vix_normalized"}
    missing = sorted(required - set(reference_daily.columns))
    if missing:
        raise ValueError(f"reference daily missing overlay columns: {missing}")

    rules = contract["overlay_rules"]
    activation_threshold = float(rules["activation_rsi_below"])
    release_threshold = float(rules["release_rsi_above"])
    release_closes = int(rules["release_confirmation_closes"])
    if release_closes != 2:
        raise ValueError("the frozen experiment requires two release closes")

    rsi_valid = reference_daily["rsi_14"].notna()
    rsi_weak = reference_daily["rsi_14"].lt(activation_threshold) & rsi_valid
    rsi_repaired = reference_daily["rsi_14"].gt(release_threshold) & rsi_valid
    rsi_repair_count = (
        rsi_repaired.astype(int)
        .rolling(release_closes, min_periods=release_closes)
        .sum()
        .eq(release_closes)
    )
    vix_stressed = reference_daily["vix_stress"].fillna(False).astype(bool)
    vix_repaired = (
        ~vix_stressed
        & (
            reference_daily["vix_easing"].fillna(False).astype(bool)
            | reference_daily["vix_normalized"].fillna(False).astype(bool)
        )
    )

    if variant == "vix_only_adaptive_sgov":
        activation = vix_stressed
        release = vix_repaired
    elif variant == "rsi_only_adaptive_sgov":
        activation = rsi_weak
        release = rsi_repair_count
    else:
        activation = rsi_weak & vix_stressed
        release = rsi_repair_count & vix_repaired

    active = False
    states: list[bool] = []
    reasons: list[str] = []
    for activate, release_now in zip(activation, release, strict=True):
        reason = "hold_active" if active else "hold_inactive"
        if active and bool(release_now):
            active = False
            reason = "release_on_repair"
        elif not active and bool(activate):
            active = True
            reason = "activate_on_deterioration"
        states.append(active)
        reasons.append(reason)

    return pd.DataFrame(
        {
            "rsi_weak": rsi_weak.astype(bool),
            "rsi_repaired": rsi_repaired.astype(bool),
            "rsi_release_confirmed": rsi_repair_count.fillna(False).astype(bool),
            "vix_stressed_for_overlay": vix_stressed.astype(bool),
            "vix_repaired_for_overlay": vix_repaired.astype(bool),
            "overlay_activation": activation.astype(bool),
            "overlay_release": release.astype(bool),
            "overlay_active_at_close": pd.Series(
                states, index=reference_daily.index, dtype=bool
            ),
            "overlay_reason_at_close": reasons,
        },
        index=reference_daily.index,
    )


def _weights_from_overlay(
    reference_daily: pd.DataFrame,
    trace: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.Series]:
    """Map the close trace to next-open weights without changing v4.2 state 2."""

    allocations = contract["allocations"]
    states = reference_daily["position_state"].astype(int)
    active_at_open = (
        trace["overlay_active_at_close"].shift(1).fillna(False).astype(bool)
    )
    active_at_open &= states.isin([0, 1])

    weights = pd.DataFrame(0.0, index=reference_daily.index, columns=list(ASSETS))
    for state, allocation_key in (
        (0, "base_state_0"),
        (1, "base_state_1"),
        (2, "state_2_frozen"),
    ):
        mask = states.eq(state)
        raw = allocations[allocation_key]
        for asset in ASSETS:
            weights.loc[mask, asset] = float(raw.get(asset, 0.0))

    for state, allocation_key in ((0, "overlay_state_0"), (1, "overlay_state_1")):
        mask = states.eq(state) & active_at_open
        raw = allocations[allocation_key]
        for asset in ASSETS:
            weights.loc[mask, asset] = float(raw.get(asset, 0.0))

    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("overlay weights must sum to one")
    if (weights < -1e-12).any().any():
        raise AssertionError("overlay weights cannot be negative")
    state_two = states.eq(2)
    expected_state_two = allocations["state_2_frozen"]
    for asset in ASSETS:
        if not np.allclose(
            weights.loc[state_two, asset],
            float(expected_state_two.get(asset, 0.0)),
        ):
            raise AssertionError("overlay changed the frozen state-2 allocation")
    if bool(weights.loc[~states.isin([0, 1]), "SGOV"].gt(0.0).any()):
        raise AssertionError("SGOV appeared outside states 0/1")
    return weights, active_at_open


def run_adaptive_overlay_backtest(
    reference_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    variant: str,
) -> StrategyResult:
    """Run one frozen adaptive overlay on the unchanged v4.2 state trace."""

    daily = reference_daily.copy()
    trace = _overlay_close_trace(daily, contract, variant)
    daily = daily.join(trace)
    weights, active_at_open = _weights_from_overlay(daily, trace, contract)
    daily["overlay_active"] = active_at_open
    daily["overlay_reason"] = (
        daily["overlay_reason_at_close"].shift(1).fillna("initial_entry")
    )
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
    weight_changes = weights.loc[daily.index].ne(weights.loc[daily.index].shift()).any(axis=1)
    metrics.update(
        {
            "strategy": variant,
            "switch_count": int(max(int(weight_changes.sum()) - 1, 0)),
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "overlay_sessions": int(daily["overlay_active"].sum()),
            "overlay_session_rate": float(daily["overlay_active"].mean()),
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
        "overlay_active",
        "overlay_reason",
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
    return StrategyResult(variant, daily, trades, metrics)


def _overlay_episodes(
    candidate: StrategyResult,
    baseline: StrategyResult,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Attribute every contiguous SGOV episode against the current v4.2 baseline."""

    active = candidate.daily["overlay_active"].astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    index = candidate.daily.index
    rows: list[dict[str, Any]] = []
    false_defense_threshold = float(
        contract["validation"]["false_defense_forward_drawdown_threshold"]
    )
    horizons = [int(value) for value in contract["validation"]["event_horizons"]]
    for event_number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and bool(active.iloc[end_location + 1]):
            end_location += 1
        end = index[end_location]
        candidate_slice = candidate.daily.iloc[start_location : end_location + 1]
        baseline_slice = baseline.daily.iloc[start_location : end_location + 1]
        candidate_log = float(np.log1p(candidate_slice["net_return"]).sum())
        baseline_log = float(np.log1p(baseline_slice["net_return"]).sum())
        baseline_equity = (1.0 + baseline_slice["net_return"]).cumprod()
        forward_drawdown = float(baseline_equity.div(baseline_equity.cummax()).sub(1.0).min())
        row: dict[str, Any] = {
            "event_id": f"overlay_{event_number:03d}",
            "start_date": start,
            "end_date": end,
            "sessions": int(end_location - start_location + 1),
            "entry_state": int(candidate.daily.loc[start, "position_state"]),
            "entry_rsi_14": float(candidate.daily.loc[start, "rsi_14"]),
            "entry_vix_close": float(candidate.daily.loc[start, "vix_close"]),
            "candidate_return": float(np.exp(candidate_log) - 1.0),
            "v4_2_return": float(np.exp(baseline_log) - 1.0),
            "relative_return": float(np.exp(candidate_log - baseline_log) - 1.0),
            "v4_2_episode_drawdown": forward_drawdown,
            "false_defense": bool(forward_drawdown > -false_defense_threshold),
        }
        release_location = end_location + 1
        for horizon in horizons:
            stop = release_location + horizon
            if release_location >= len(index) or stop > len(index):
                row[f"post_release_relative_return_{horizon}d"] = np.nan
                continue
            candidate_window = candidate.daily["net_return"].iloc[
                release_location:stop
            ]
            baseline_window = baseline.daily["net_return"].iloc[
                release_location:stop
            ]
            row[f"post_release_relative_return_{horizon}d"] = float(
                np.exp(
                    np.log1p(candidate_window).sum()
                    - np.log1p(baseline_window).sum()
                )
                - 1.0
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _capture_ratio(strategy: pd.Series, benchmark: pd.Series, up: bool) -> float | None:
    aligned = pd.concat([strategy, benchmark], axis=1).dropna()
    if aligned.empty:
        return None
    mask = aligned.iloc[:, 1].gt(0.0) if up else aligned.iloc[:, 1].lt(0.0)
    sample = aligned.loc[mask]
    if sample.empty:
        return None
    strategy_return = float((1.0 + sample.iloc[:, 0]).prod() - 1.0)
    benchmark_return = float((1.0 + sample.iloc[:, 1]).prod() - 1.0)
    if np.isclose(benchmark_return, 0.0):
        return None
    return float(strategy_return / benchmark_return)


def _opportunity_metrics(result: StrategyResult) -> dict[str, Any]:
    daily = result.daily
    qqq = daily["QQQ_next_open_return"].astype(float)
    threshold = float(qqq.quantile(0.90))
    top = qqq.ge(threshold)
    sgov_active = daily["weight_SGOV"].gt(0.0)
    return {
        "upside_capture_vs_qqq": _capture_ratio(daily["net_return"], qqq, True),
        "downside_capture_vs_qqq": _capture_ratio(daily["net_return"], qqq, False),
        "qqq_top_decile_return_threshold": threshold,
        "qqq_top_decile_sessions": int(top.sum()),
        "qqq_top_decile_sessions_with_sgov": int((top & sgov_active).sum()),
        "qqq_top_decile_sgov_exposure_rate": (
            float((top & sgov_active).sum() / top.sum()) if int(top.sum()) else None
        ),
    }


def _gate(
    joint: StrategyResult,
    baseline: StrategyResult,
    single_factor_results: Mapping[str, StrategyResult],
    episodes: pd.DataFrame,
    chronological: pd.DataFrame,
    drawdown_episodes: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["promotion_gate"]
    major = drawdown_episodes.loc[drawdown_episodes["major_episode"]].copy()
    resolved = major.loc[major["recovery_lag_sessions"].notna()]
    median_lag = (
        float(resolved["recovery_lag_sessions"].median()) if len(resolved) else None
    )
    max_drawdown_improvement = (
        float(joint.metrics["max_drawdown"]) - float(baseline.metrics["max_drawdown"])
    ) * 100.0
    cagr_sacrifice = (
        float(baseline.metrics["cagr"]) - float(joint.metrics["cagr"])
    ) * 100.0
    improvement_rate = float(major["drawdown_improvement"].gt(0.0).mean())
    median_protection = float(major["drawdown_improvement_pp"].median())

    event_values = (
        episodes["relative_return"].astype(float)
        if not episodes.empty
        else pd.Series(dtype=float)
    )
    positive = event_values.clip(lower=0.0)
    largest_share = (
        float(positive.max() / positive.sum())
        if len(positive) and float(positive.sum()) > 0.0
        else 1.0
    )

    chrono = chronological.set_index(["strategy", "segment"])
    chronological_pass = True
    for segment in ("early", "late"):
        joint_calmar = float(chrono.loc[(joint.metrics["strategy"], segment), "calmar"])
        baseline_calmar = float(
            chrono.loc[(baseline.metrics["strategy"], segment), "calmar"]
        )
        chronological_pass &= joint_calmar >= baseline_calmar

    comparisons: dict[str, dict[str, bool]] = {}
    win_counts: dict[str, int] = {}
    for key, comparator in single_factor_results.items():
        checks = {
            "calmar": float(joint.metrics["calmar"]) > float(comparator.metrics["calmar"]),
            "sortino": float(joint.metrics["sortino"])
            > float(comparator.metrics["sortino"]),
            "max_drawdown": float(joint.metrics["max_drawdown"])
            > float(comparator.metrics["max_drawdown"]),
            "recovery_lag": False,
        }
        comparisons[key] = checks
        win_counts[key] = int(sum(checks.values()))

    turnover_limit = float(baseline.metrics["turnover_units"]) * (
        1.0 + float(thresholds["turnover_increase_max"])
    )
    checks = {
        "max_drawdown_improvement": max_drawdown_improvement
        >= float(thresholds["max_drawdown_improvement_pp_min"]),
        "major_trough_improvement_rate": improvement_rate
        >= float(thresholds["major_trough_improvement_rate_min"]),
        "median_major_trough_protection": median_protection > 0.0,
        "cagr_sacrifice": cagr_sacrifice
        <= float(thresholds["cagr_sacrifice_pp_max"]),
        "median_recovery_lag": median_lag is not None
        and median_lag <= float(thresholds["median_recovery_lag_sessions_max"]),
        "beats_vix_only_on_two_metrics": win_counts.get(
            "vix_only_adaptive_sgov", 0
        )
        >= int(thresholds["single_factor_metrics_to_beat_min"]),
        "beats_rsi_only_on_two_metrics": win_counts.get(
            "rsi_only_adaptive_sgov", 0
        )
        >= int(thresholds["single_factor_metrics_to_beat_min"]),
        "chronological_stability": bool(chronological_pass),
        "event_concentration": largest_share
        <= float(thresholds["largest_positive_event_share_max"]),
        "turnover": float(joint.metrics["turnover_units"]) <= turnover_limit,
    }
    return {
        "checks": checks,
        "metrics": {
            "max_drawdown_improvement_pp": max_drawdown_improvement,
            "major_trough_improvement_rate": improvement_rate,
            "median_major_trough_protection_pp": median_protection,
            "cagr_sacrifice_pp": cagr_sacrifice,
            "median_recovery_lag_sessions": median_lag,
            "largest_positive_event_share": largest_share,
            "turnover_limit": turnover_limit,
            "single_factor_comparisons": comparisons,
            "single_factor_win_counts": win_counts,
        },
        "shadow_candidate_authorized": bool(all(checks.values())),
        "direct_promotion_authorized": False,
    }


def run_rsi_vix_sgov_comparison(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    overlay_contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    dict[str, StrategyResult],
    pd.DataFrame,
    dict[str, pd.DataFrame],
    dict[str, Any],
]:
    """Run the frozen baseline, static SGOV and three adaptive ablations."""

    _, bridge_results, _, _ = run_bridge_allocation_comparison(
        bars, bridge_contract
    )
    reference = _common_reference_daily(bridge_results[V4_2_KEY], bars)
    qqq_close = _normalise_close(bars["QQQ"], "QQQ")
    reference = reference.join(qqq_close.rename("qqq_close"), how="left")
    reference["rsi_14"] = wilder_rsi(
        reference["qqq_close"], period=int(overlay_contract["overlay_rules"]["rsi_period"])
    )
    reference = reference.dropna(subset=["rsi_14"]).copy()

    baseline = run_state_weight_backtest(reference, sgov_contract, "current_v4_2")
    static = run_state_weight_backtest(
        reference, sgov_contract, "qqqi_sgov_blended_defense"
    )
    static.metrics["strategy"] = "static_blended_sgov"
    static.name = "static_blended_sgov"
    results: dict[str, StrategyResult] = {
        "current_v4_2": baseline,
        "static_blended_sgov": static,
    }
    for variant in VARIANTS:
        results[variant] = run_adaptive_overlay_backtest(
            reference, overlay_contract, variant
        )

    baseline_states = baseline.daily["position_state"].astype(int)
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
        overlay_contract["validation"]["chronological_train_fraction"]
    )
    chronological = pd.DataFrame(
        [
            row
            for result in results.values()
            for row in _chronological_metrics(result, train_fraction)
        ]
    )

    overlay_episodes: dict[str, pd.DataFrame] = {}
    drawdown_episodes: dict[str, pd.DataFrame] = {}
    for key in ("static_blended_sgov", *VARIANTS):
        drawdowns, _ = attribute_sgov_drawdown_episodes_at_baseline_trough(
            baseline, results[key], attribution_contract
        )
        drawdown_episodes[key] = drawdowns
        if key in VARIANTS:
            overlay_episodes[key] = _overlay_episodes(
                results[key], baseline, overlay_contract
            )

    gate = _gate(
        results["rsi_vix_adaptive_sgov"],
        baseline,
        {
            "vix_only_adaptive_sgov": results["vix_only_adaptive_sgov"],
            "rsi_only_adaptive_sgov": results["rsi_only_adaptive_sgov"],
        },
        overlay_episodes["rsi_vix_adaptive_sgov"],
        chronological,
        drawdown_episodes["rsi_vix_adaptive_sgov"],
        overlay_contract,
    )

    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "same_v4_2_state_trace": True,
        "same_state_2_allocation": True,
        "sample": {
            "start": reference.index.min().date().isoformat(),
            "end": reference.index.max().date().isoformat(),
            "observations": int(len(reference)),
        },
        "tail_risk": {
            key: tail_risk_metrics(result) for key, result in results.items()
        },
        "opportunity_metrics": {
            key: _opportunity_metrics(result) for key, result in results.items()
        },
        "false_defense": {
            key: {
                "episode_count": int(len(table)),
                "false_defense_count": int(table["false_defense"].sum())
                if not table.empty
                else 0,
                "false_defense_rate": float(table["false_defense"].mean())
                if not table.empty
                else None,
            }
            for key, table in overlay_episodes.items()
        },
        "promotion_gate": gate,
        "decision": (
            "joint_overlay_shadow_supported"
            if gate["shadow_candidate_authorized"]
            else "adaptive_overlay_not_supported"
        ),
        "direct_promotion_authorized": False,
    }
    all_episodes = {
        **{f"overlay_{key}": value for key, value in overlay_episodes.items()},
        **{f"drawdown_{key}": value for key, value in drawdown_episodes.items()},
    }
    return headline.sort_index(), results, chronological, all_episodes, diagnostics
