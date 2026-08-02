"""Path-efficiency decomposition for frozen v4.2 recovery precursors.

This module explains post-execution outcomes. It does not select thresholds,
change weights, fit a classifier, or authorize a production rule.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.v4_2_recovery_precursor_failure_taxonomy import (
    run_recovery_precursor_failure_taxonomy,
)
from src.research.v4_2_sgov_precursor_50_experiment import BOLD_KEY


def _cumulative_return(series: pd.Series) -> float:
    values = series.dropna().astype(float)
    if values.empty:
        return float("nan")
    return float((1.0 + values).prod() - 1.0)


def _annualized_volatility(series: pd.Series) -> float:
    values = series.dropna().astype(float)
    if len(values) < 2:
        return float("nan")
    return float(values.std(ddof=1) * np.sqrt(252.0))


def _sign_reversals(series: pd.Series) -> int:
    signs = np.sign(series.dropna().astype(float)).replace(0.0, np.nan).dropna()
    if len(signs) < 2:
        return 0
    return int((signs.diff().abs() == 2.0).sum())


def _path_excursion(series: pd.Series) -> tuple[float, float, int | None]:
    values = series.dropna().astype(float)
    if values.empty:
        return float("nan"), float("nan"), None
    path = (1.0 + values).cumprod() - 1.0
    adverse_position = int(np.argmin(path.to_numpy())) + 1
    return float(path.max()), float(path.min()), adverse_position


def _open_to_open_components(
    daily: pd.DataFrame,
    symbol: str,
    start: int,
    horizon: int,
) -> tuple[float, float]:
    frame = daily.iloc[start : start + horizon]
    if len(frame) != horizon:
        return float("nan"), float("nan")
    intraday = frame[f"{symbol}_close"].astype(float) / frame[
        f"{symbol}_open"
    ].astype(float) - 1.0
    next_open = daily[f"{symbol}_open"].shift(-1).iloc[start : start + horizon]
    overnight = next_open.astype(float) / frame[f"{symbol}_close"].astype(float) - 1.0
    if intraday.isna().any() or overnight.isna().any():
        return float("nan"), float("nan")
    return float(np.log1p(intraday).sum()), float(np.log1p(overnight).sum())


def _horizon_metrics(
    daily: pd.DataFrame,
    start: int,
    horizon: int,
    counterfactual_leverage: float,
) -> dict[str, Any]:
    frame = daily.iloc[start : start + horizon]
    if len(frame) != horizon:
        return {}
    qqq = frame["QQQ_next_open_return"].astype(float)
    tqqq = frame["TQQQ_next_open_return"].astype(float)
    if qqq.isna().any() or tqqq.isna().any():
        return {}

    qqq_return = _cumulative_return(qqq)
    tqqq_return = _cumulative_return(tqqq)
    counterfactual = _cumulative_return(counterfactual_leverage * qqq)
    qqq_mfe, qqq_mae, qqq_mae_session = _path_excursion(qqq)
    tqqq_mfe, tqqq_mae, tqqq_mae_session = _path_excursion(tqqq)
    qqq_intraday, qqq_overnight = _open_to_open_components(
        daily, "QQQ", start, horizon
    )
    tqqq_intraday, tqqq_overnight = _open_to_open_components(
        daily, "TQQQ", start, horizon
    )
    denominator = counterfactual_leverage * qqq_return
    efficiency = (
        float(tqqq_return / denominator)
        if np.isfinite(denominator) and abs(denominator) > 1e-12
        else float("nan")
    )
    suffix = f"{horizon}d"
    return {
        f"qqq_return_{suffix}": qqq_return,
        f"tqqq_return_{suffix}": tqqq_return,
        f"counterfactual_3x_qqq_return_{suffix}": counterfactual,
        f"tqqq_tracking_compounding_residual_{suffix}": tqqq_return
        - counterfactual,
        f"tqqq_realized_leverage_efficiency_{suffix}": efficiency,
        f"qqq_mfe_{suffix}": qqq_mfe,
        f"qqq_mae_{suffix}": qqq_mae,
        f"qqq_mae_session_{suffix}": qqq_mae_session,
        f"tqqq_mfe_{suffix}": tqqq_mfe,
        f"tqqq_mae_{suffix}": tqqq_mae,
        f"tqqq_mae_session_{suffix}": tqqq_mae_session,
        f"qqq_realized_volatility_{suffix}": _annualized_volatility(qqq),
        f"tqqq_realized_volatility_{suffix}": _annualized_volatility(tqqq),
        f"qqq_sign_reversals_{suffix}": _sign_reversals(qqq),
        f"qqq_intraday_log_return_{suffix}": qqq_intraday,
        f"qqq_overnight_log_return_{suffix}": qqq_overnight,
        f"tqqq_intraday_log_return_{suffix}": tqqq_intraday,
        f"tqqq_overnight_log_return_{suffix}": tqqq_overnight,
    }


def build_path_efficiency_table(
    taxonomy_result: Mapping[str, Any],
    path_contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Build event-level post-execution path attribution."""

    taxonomy = taxonomy_result["event_taxonomy"].copy()
    daily = taxonomy_result["proxy_result"]["proxy_results"][BOLD_KEY].daily.copy()
    daily.index = pd.to_datetime(daily.index)
    horizons = [int(value) for value in path_contract["analysis"]["fixed_horizons"]]
    leverage = float(path_contract["analysis"]["counterfactual_daily_leverage"])
    extra_weight = float(path_contract["analysis"]["extra_tqqq_weight"])

    rows: list[dict[str, Any]] = []
    for event in taxonomy.itertuples(index=False):
        execution_date = pd.Timestamp(event.execution_date)
        end_date = pd.Timestamp(event.event_end_date)
        if execution_date not in daily.index or end_date not in daily.index:
            raise ValueError(f"event dates missing from daily trace: {event.event_id}")
        start = int(daily.index.get_loc(execution_date))
        end = int(daily.index.get_loc(end_date))
        event_horizon = int(end - start + 1)
        if event_horizon != int(event.event_sessions):
            raise AssertionError(f"event session mismatch: {event.event_id}")

        row: dict[str, Any] = {
            "event_id": event.event_id,
            "execution_date": execution_date,
            "event_end_date": end_date,
            "chronological_segment": event.chronological_segment,
            "failure_type": event.failure_type,
            "marginal_success": bool(event.marginal_success),
            "event_sessions": event_horizon,
            "strategy_marginal_50_vs_25_return": float(
                event.marginal_50_vs_25_return
            ),
            "time_to_formal_state_2_sessions": event.time_to_formal_state_2_sessions,
            "time_to_revert_state_0_sessions": event.time_to_revert_state_0_sessions,
        }
        for horizon in horizons:
            row.update(_horizon_metrics(daily, start, horizon, leverage))

        event_metrics = _horizon_metrics(daily, start, event_horizon, leverage)
        qqq_event = float(event_metrics[f"qqq_return_{event_horizon}d"])
        tqqq_event = float(event_metrics[f"tqqq_return_{event_horizon}d"])
        counterfactual_event = float(
            event_metrics[f"counterfactual_3x_qqq_return_{event_horizon}d"]
        )
        directional_component = extra_weight * (counterfactual_event - qqq_event)
        tracking_component = extra_weight * (tqqq_event - counterfactual_event)
        raw_component = extra_weight * (tqqq_event - qqq_event)
        row.update(
            {
                "event_qqq_return": qqq_event,
                "event_tqqq_return": tqqq_event,
                "event_counterfactual_3x_qqq_return": counterfactual_event,
                "event_directional_leverage_component": directional_component,
                "event_tracking_compounding_component": tracking_component,
                "event_raw_extra_25_component": raw_component,
                "strategy_minus_raw_component": float(
                    event.marginal_50_vs_25_return
                )
                - raw_component,
                "event_tqqq_tracking_compounding_residual": tqqq_event
                - counterfactual_event,
                "event_tqqq_realized_leverage_efficiency": (
                    tqqq_event / (leverage * qqq_event)
                    if abs(leverage * qqq_event) > 1e-12
                    else float("nan")
                ),
                "event_qqq_realized_volatility": event_metrics[
                    f"qqq_realized_volatility_{event_horizon}d"
                ],
                "event_qqq_sign_reversals": event_metrics[
                    f"qqq_sign_reversals_{event_horizon}d"
                ],
            }
        )
        if not np.isclose(
            directional_component + tracking_component,
            raw_component,
            atol=1e-12,
        ):
            raise AssertionError("path decomposition does not reconcile")
        rows.append(row)

    table = pd.DataFrame(rows).sort_values("execution_date").reset_index(drop=True)
    if table["event_id"].nunique() != len(taxonomy):
        raise AssertionError("path table lost or duplicated events")
    return table


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


def path_feature_separation(
    table: pd.DataFrame,
    path_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Describe stable post-execution mechanisms without fitting a rule."""

    features = list(path_contract["analysis"]["path_features"])
    missing = sorted(set(features) - set(table.columns))
    if missing:
        raise ValueError(f"path table missing configured features: {missing}")
    validation = path_contract["validation"]
    min_stability = float(validation["minimum_loo_direction_stability"])
    min_distance = float(validation["minimum_pairwise_distance_from_half"])
    rows: list[dict[str, Any]] = []
    loo_rows: list[dict[str, Any]] = []

    for feature in features:
        full = table
        early = table.loc[table["chronological_segment"] == "early"]
        full_gap = _median_gap(full, feature)
        early_gap = _median_gap(early, feature)
        feature_loo: list[dict[str, Any]] = []
        for segment_name, frame in (("full", full), ("early", early)):
            segment_gap = _median_gap(frame, feature)
            segment_sign = np.sign(segment_gap) if np.isfinite(segment_gap) else np.nan
            for event_id in frame["event_id"]:
                subset = frame.loc[frame["event_id"] != event_id]
                gap = _median_gap(subset, feature)
                item = {
                    "feature": feature,
                    "segment": segment_name,
                    "excluded_event_id": event_id,
                    "median_gap_success_minus_failure": gap,
                    "same_direction_as_full_segment": bool(
                        np.isfinite(gap)
                        and np.isfinite(segment_sign)
                        and np.sign(gap) == segment_sign
                    ),
                }
                feature_loo.append(item)
                loo_rows.append(item)
        full_loo = [r for r in feature_loo if r["segment"] == "full"]
        early_loo = [r for r in feature_loo if r["segment"] == "early"]
        full_success = full.loc[full["marginal_success"], feature].dropna().astype(float)
        full_failure = full.loc[~full["marginal_success"], feature].dropna().astype(float)
        pairwise = _pairwise_probability(full_success, full_failure)
        rows.append(
            {
                "feature": feature,
                "success_median_full": float(full_success.median()),
                "failure_median_full": float(full_failure.median()),
                "median_gap_full": full_gap,
                "median_gap_early": early_gap,
                "pairwise_probability_success_gt_failure_full": pairwise,
                "pairwise_distance_from_half_full": abs(pairwise - 0.5),
                "loo_direction_stability_full": float(
                    np.mean([r["same_direction_as_full_segment"] for r in full_loo])
                ),
                "loo_direction_stability_early": float(
                    np.mean([r["same_direction_as_full_segment"] for r in early_loo])
                ),
                "same_direction_full_and_early": bool(
                    np.isfinite(full_gap)
                    and np.isfinite(early_gap)
                    and np.sign(full_gap) == np.sign(early_gap)
                ),
            }
        )

    separation = pd.DataFrame(rows)
    separation["descriptively_stable"] = (
        separation["same_direction_full_and_early"]
        & (separation["loo_direction_stability_full"] >= min_stability)
        & (separation["loo_direction_stability_early"] >= min_stability)
        & (separation["pairwise_distance_from_half_full"] >= min_distance)
    )
    separation = separation.sort_values(
        ["descriptively_stable", "pairwise_distance_from_half_full"],
        ascending=[False, False],
    ).reset_index(drop=True)
    return separation, pd.DataFrame(loo_rows)


def path_mechanism_summary(table: pd.DataFrame) -> pd.DataFrame:
    """Summarize path attribution by the frozen failure taxonomy."""

    columns = [
        "strategy_marginal_50_vs_25_return",
        "event_qqq_return",
        "event_tqqq_return",
        "event_directional_leverage_component",
        "event_tracking_compounding_component",
        "qqq_return_1d",
        "qqq_return_5d",
        "qqq_mae_5d",
        "qqq_mfe_5d",
        "qqq_realized_volatility_5d",
        "qqq_sign_reversals_5d",
        "qqq_intraday_log_return_5d",
        "qqq_overnight_log_return_5d",
    ]
    rows: list[dict[str, Any]] = []
    for failure_type, frame in table.groupby("failure_type", sort=False):
        row: dict[str, Any] = {
            "failure_type": failure_type,
            "event_count": int(len(frame)),
        }
        for column in columns:
            row[f"{column}_median"] = float(frame[column].median())
            row[f"{column}_mean"] = float(frame[column].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def path_efficiency_decision(
    table: pd.DataFrame,
    separation: pd.DataFrame,
    path_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a diagnostic governance decision."""

    validation = path_contract["validation"]
    failed = table.loc[~table["marginal_success"]]
    late = table.loc[table["chronological_segment"] == "late"]
    early = table.loc[table["chronological_segment"] == "early"]
    stable = separation.loc[separation["descriptively_stable"]]

    directional_loss = float(
        -failed["event_directional_leverage_component"].clip(upper=0.0).sum()
    )
    tracking_loss = float(
        -failed["event_tracking_compounding_component"].clip(upper=0.0).sum()
    )
    total_attributed_loss = directional_loss + tracking_loss
    directional_loss_share = (
        directional_loss / total_attributed_loss if total_attributed_loss > 0.0 else np.nan
    )
    failure_subtypes = int(failed["failure_type"].nunique())
    checks = {
        "minimum_event_count": len(table) >= int(validation["minimum_event_count"]),
        "minimum_successful_event_count": int(table["marginal_success"].sum())
        >= int(validation["minimum_successful_event_count"]),
        "minimum_failed_event_count": int((~table["marginal_success"]).sum())
        >= int(validation["minimum_failed_event_count"]),
        "minimum_failure_subtype_count": failure_subtypes
        >= int(validation["minimum_failure_subtype_count"]),
        "early_segment_contains_success_and_failure": bool(
            early["marginal_success"].nunique() == 2
        ),
        "late_segment_contains_success_and_failure": bool(
            late["marginal_success"].nunique() == 2
        ),
    }
    mechanism_fields = stable["feature"].head(
        int(validation["maximum_mechanism_fields"])
    ).tolist()
    explanation_justified = bool(
        checks["minimum_event_count"]
        and checks["minimum_successful_event_count"]
        and checks["minimum_failed_event_count"]
        and checks["minimum_failure_subtype_count"]
        and checks["early_segment_contains_success_and_failure"]
    )
    new_hypothesis = bool(explanation_justified and all(checks.values()))
    return {
        "research_only": True,
        "trade_ready": False,
        "model_change_authorized": False,
        "actionable_alert_authorized": False,
        "path_mechanism_explanation_justified": explanation_justified,
        "prospective_path_monitoring_justified": explanation_justified,
        "new_preregistered_trading_hypothesis_justified": new_hypothesis,
        "checks": checks,
        "metrics": {
            "event_count": int(len(table)),
            "successful_event_count": int(table["marginal_success"].sum()),
            "failed_event_count": int((~table["marginal_success"]).sum()),
            "failure_subtype_count": failure_subtypes,
            "directional_loss_component": directional_loss,
            "tracking_compounding_loss_component": tracking_loss,
            "directional_loss_share": float(directional_loss_share),
            "stable_path_feature_count": int(len(stable)),
            "candidate_prospective_path_fields": mechanism_fields,
        },
        "mechanism": (
            "underlying_path_and_entry_timing_dominate_tracking_residual"
            if directional_loss_share >= 0.5
            else "tracking_and_compounding_residual_is_material"
        ),
        "decision": (
            "preregistered_path_hypothesis_permitted"
            if new_hypothesis
            else "monitor_path_mechanism_prospectively_without_new_rule"
        ),
    }


def run_tqqq_path_efficiency_analysis(
    bars: Mapping[str, pd.DataFrame],
    baseline_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    prior_release_contract: Mapping[str, Any],
    bold_contract: Mapping[str, Any],
    proxy_contract: Mapping[str, Any],
    taxonomy_contract: Mapping[str, Any],
    path_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the frozen taxonomy and produce path-efficiency attribution."""

    taxonomy_result = run_recovery_precursor_failure_taxonomy(
        bars,
        baseline_contract,
        sgov_contract,
        attribution_contract,
        prior_release_contract,
        bold_contract,
        proxy_contract,
        taxonomy_contract,
    )
    table = build_path_efficiency_table(taxonomy_result, path_contract)
    separation, leave_one_out = path_feature_separation(table, path_contract)
    summary = path_mechanism_summary(table)
    decision = path_efficiency_decision(table, separation, path_contract)
    return {
        "taxonomy_result": taxonomy_result,
        "path_efficiency_table": table,
        "path_feature_separation": separation,
        "leave_one_event_out": leave_one_out,
        "path_mechanism_summary": summary,
        "decision": decision,
    }
