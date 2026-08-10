"""Episode attribution for the frozen QQQI/SGOV defensive challenger.

The analysis is descriptive and governance-oriented. It does not alter the
v4.2 signal trace, portfolio weights, thresholds, execution timing or cost
assumption.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult


def baseline_drawdown_episodes(result: StrategyResult) -> pd.DataFrame:
    """Return peak-to-recovery episodes defined by the baseline equity curve."""

    equity = result.daily["equity"].dropna().astype(float)
    if len(equity) < 2:
        return pd.DataFrame()

    peak_value = float(equity.iloc[0])
    peak_date = equity.index[0]
    active = False
    episode_peak_date = peak_date
    episode_peak_value = peak_value
    trough_date = peak_date
    trough_drawdown = 0.0
    rows: list[dict[str, Any]] = []

    for date, value_raw in equity.iloc[1:].items():
        value = float(value_raw)
        if value >= peak_value * (1.0 - 1e-12):
            if active:
                rows.append(
                    {
                        "episode_start": episode_peak_date,
                        "baseline_trough_date": trough_date,
                        "baseline_recovery_date": date,
                        "baseline_peak_equity": episode_peak_value,
                        "baseline_max_drawdown": trough_drawdown,
                        "baseline_recovered": True,
                    }
                )
                active = False
            if value > peak_value:
                peak_value = value
                peak_date = date
            continue

        drawdown = value / peak_value - 1.0
        if not active:
            active = True
            episode_peak_date = peak_date
            episode_peak_value = peak_value
            trough_date = date
            trough_drawdown = drawdown
        elif drawdown < trough_drawdown:
            trough_date = date
            trough_drawdown = drawdown

    if active:
        rows.append(
            {
                "episode_start": episode_peak_date,
                "baseline_trough_date": trough_date,
                "baseline_recovery_date": pd.NaT,
                "baseline_peak_equity": episode_peak_value,
                "baseline_max_drawdown": trough_drawdown,
                "baseline_recovered": False,
            }
        )

    episodes = pd.DataFrame(rows)
    if episodes.empty:
        return episodes
    episodes["episode_id"] = [f"dd_{index + 1:03d}" for index in range(len(episodes))]
    columns = ["episode_id", *[column for column in episodes.columns if column != "episode_id"]]
    return episodes[columns]


def _path_from_start(equity: pd.Series, start_date: pd.Timestamp) -> dict[str, Any]:
    path = equity.loc[start_date:].dropna().astype(float)
    if len(path) < 2:
        return {
            "trough_date": start_date,
            "max_drawdown": 0.0,
            "recovery_date": pd.NaT,
            "recovery_sessions": None,
            "recovered": False,
        }

    relative = path / float(path.iloc[0])
    after_start = relative.iloc[1:]
    trough_date = after_start.idxmin()
    max_drawdown = float(after_start.loc[trough_date] - 1.0)
    post_trough = relative.loc[trough_date:]
    recovered = post_trough.loc[post_trough.ge(1.0 - 1e-12)]
    recovery_date = recovered.index[0] if len(recovered) else pd.NaT
    recovery_sessions = int(path.index.get_loc(recovery_date)) if pd.notna(recovery_date) else None
    return {
        "trough_date": trough_date,
        "max_drawdown": max_drawdown,
        "recovery_date": recovery_date,
        "recovery_sessions": recovery_sessions,
        "recovered": bool(pd.notna(recovery_date)),
    }


def _session_distance(index: pd.Index, start: pd.Timestamp, end: Any) -> int | None:
    if pd.isna(end):
        return None
    return int(index.get_loc(end) - index.get_loc(start))


def _phase_mask(
    index: pd.Index,
    *,
    after: pd.Timestamp,
    through: Any,
) -> pd.Series:
    mask = pd.Series(index > after, index=index)
    if pd.notna(through):
        mask &= index <= through
    return mask


def _sum_by_state(
    values: pd.Series,
    states: pd.Series,
    mask: pd.Series,
    prefix: str,
) -> dict[str, float]:
    output: dict[str, float] = {}
    for state in (0, 1, 2):
        state_mask = mask & states.eq(state)
        output[f"{prefix}_state_{state}_log_relative"] = float(values.loc[state_mask].sum())
    output[f"{prefix}_total_log_relative"] = float(values.loc[mask].sum())
    return output


def attribute_sgov_drawdown_episodes(
    baseline: StrategyResult,
    challenger: StrategyResult,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attribute baseline drawdowns and evaluate the frozen blended challenger."""

    common = baseline.daily.index.intersection(challenger.daily.index)
    left = baseline.daily.loc[common].copy()
    right = challenger.daily.loc[common].copy()
    if not left["position_state"].astype(int).equals(right["position_state"].astype(int)):
        raise AssertionError("baseline and challenger must share the exact state trace")

    episodes = baseline_drawdown_episodes(
        StrategyResult(baseline.name, left, baseline.trades, baseline.metrics)
    )
    if episodes.empty:
        return episodes, {
            "prospective_monitor_authorized": False,
            "reason": "no_drawdown_episodes",
        }

    baseline_equity = left["equity"].astype(float)
    challenger_equity = right["equity"].astype(float)
    states = left["position_state"].astype(int)
    relative_log = np.log1p(right["net_return"].astype(float)) - np.log1p(
        left["net_return"].astype(float)
    )
    gross_delta = right["gross_return"].astype(float) - left["gross_return"].astype(float)
    cost_benefit = left["transaction_cost"].astype(float) - right["transaction_cost"].astype(float)

    rows: list[dict[str, Any]] = []
    for episode in episodes.to_dict(orient="records"):
        start = pd.Timestamp(episode["episode_start"])
        baseline_trough = pd.Timestamp(episode["baseline_trough_date"])
        baseline_recovery = episode["baseline_recovery_date"]
        challenger_path = _path_from_start(challenger_equity, start)
        challenger_recovery = challenger_path["recovery_date"]

        baseline_recovery_sessions = _session_distance(common, start, baseline_recovery)
        challenger_recovery_sessions = challenger_path["recovery_sessions"]
        recovery_lag = (
            challenger_recovery_sessions - baseline_recovery_sessions
            if baseline_recovery_sessions is not None and challenger_recovery_sessions is not None
            else None
        )

        stress_mask = _phase_mask(common, after=start, through=baseline_trough)
        recovery_mask = pd.Series(False, index=common)
        if pd.notna(baseline_recovery):
            recovery_mask = pd.Series(
                (common > baseline_trough) & (common <= baseline_recovery),
                index=common,
            )
        lag_mask = pd.Series(False, index=common)
        if (
            pd.notna(baseline_recovery)
            and pd.notna(challenger_recovery)
            and challenger_recovery > baseline_recovery
        ):
            lag_mask = pd.Series(
                (common > baseline_recovery) & (common <= challenger_recovery),
                index=common,
            )

        baseline_start_equity = float(baseline_equity.loc[start])
        challenger_start_equity = float(challenger_equity.loc[start])
        relative_at_trough = float(
            challenger_equity.loc[baseline_trough] / challenger_start_equity
            - baseline_equity.loc[baseline_trough] / baseline_start_equity
        )
        relative_at_baseline_recovery = None
        if pd.notna(baseline_recovery):
            relative_at_baseline_recovery = float(
                challenger_equity.loc[baseline_recovery] / challenger_start_equity
                - baseline_equity.loc[baseline_recovery] / baseline_start_equity
            )

        row: dict[str, Any] = {
            **episode,
            "challenger_trough_date": challenger_path["trough_date"],
            "challenger_recovery_date": challenger_recovery,
            "challenger_max_drawdown": challenger_path["max_drawdown"],
            "challenger_recovered": challenger_path["recovered"],
            "baseline_recovery_sessions": baseline_recovery_sessions,
            "challenger_recovery_sessions": challenger_recovery_sessions,
            "recovery_lag_sessions": recovery_lag,
            "drawdown_improvement": float(
                challenger_path["max_drawdown"] - episode["baseline_max_drawdown"]
            ),
            "relative_return_at_baseline_trough": relative_at_trough,
            "relative_return_at_baseline_recovery": relative_at_baseline_recovery,
            "stress_gross_delta": float(gross_delta.loc[stress_mask].sum()),
            "stress_cost_benefit": float(cost_benefit.loc[stress_mask].sum()),
            "recovery_gross_delta": float(gross_delta.loc[recovery_mask].sum()),
            "recovery_cost_benefit": float(cost_benefit.loc[recovery_mask].sum()),
            "lag_gross_delta": float(gross_delta.loc[lag_mask].sum()),
            "lag_cost_benefit": float(cost_benefit.loc[lag_mask].sum()),
            "stress_sessions": int(stress_mask.sum()),
            "recovery_sessions_observed": int(recovery_mask.sum()),
            "lag_sessions_observed": int(lag_mask.sum()),
        }
        row.update(_sum_by_state(relative_log, states, stress_mask, "stress"))
        row.update(_sum_by_state(relative_log, states, recovery_mask, "recovery"))
        row.update(_sum_by_state(relative_log, states, lag_mask, "lag"))
        rows.append(row)

    output = pd.DataFrame(rows)
    output["drawdown_improvement_pp"] = output["drawdown_improvement"] * 100.0
    output["relative_return_at_baseline_trough_pp"] = (
        output["relative_return_at_baseline_trough"] * 100.0
    )
    output["relative_return_at_baseline_recovery_pp"] = (
        output["relative_return_at_baseline_recovery"] * 100.0
    )
    output["severity_rank"] = (
        output["baseline_max_drawdown"].rank(method="first", ascending=True).astype(int)
    )
    major_count = min(int(contract["analysis"]["primary_major_episode_count"]), len(output))
    output["major_episode"] = output["severity_rank"].le(major_count)
    split_location = int(len(common) * float(contract["analysis"]["chronological_split_fraction"]))
    split_location = min(max(split_location, 1), len(common) - 1)
    split_date = common[split_location]
    output["chronological_segment"] = np.where(
        output["episode_start"] < split_date, "early", "late"
    )

    gate = evaluate_prospective_monitor_gate(output, baseline, challenger, contract)
    return output.sort_values("episode_start").reset_index(drop=True), gate


def _improvement_rate(sample: pd.DataFrame) -> float | None:
    if sample.empty:
        return None
    return float(sample["drawdown_improvement"].gt(0.0).mean())


def evaluate_prospective_monitor_gate(
    episodes: pd.DataFrame,
    baseline: StrategyResult,
    challenger: StrategyResult,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the predeclared monitor-only gate to major drawdown episodes."""

    major = episodes.loc[episodes["major_episode"]].copy()
    thresholds = contract["prospective_monitor_gate"]
    improvement_rate = _improvement_rate(major)
    median_improvement_pp = float(major["drawdown_improvement_pp"].median())
    recovered_major = major.loc[major["recovery_lag_sessions"].notna()]
    median_lag = (
        float(recovered_major["recovery_lag_sessions"].median()) if len(recovered_major) else None
    )
    unresolved_major = int(major["recovery_lag_sessions"].isna().sum())
    early_rate = _improvement_rate(major.loc[major["chronological_segment"].eq("early")])
    late_rate = _improvement_rate(major.loc[major["chronological_segment"].eq("late")])
    positive = major["drawdown_improvement"].clip(lower=0.0)
    largest_share = float(positive.max() / positive.sum()) if float(positive.sum()) > 0.0 else 1.0
    cagr_sacrifice_pp = float(
        (float(baseline.metrics["cagr"]) - float(challenger.metrics["cagr"])) * 100.0
    )

    checks = {
        "major_episode_drawdown_improvement_rate": bool(
            improvement_rate is not None
            and improvement_rate >= float(thresholds["major_episode_drawdown_improvement_rate_min"])
        ),
        "median_major_episode_drawdown_improvement": bool(
            median_improvement_pp
            >= float(thresholds["median_major_episode_drawdown_improvement_pp_min"])
        ),
        "major_episode_recovery_lag": bool(
            unresolved_major == 0
            and median_lag is not None
            and median_lag <= float(thresholds["median_major_episode_recovery_lag_sessions_max"])
        ),
        "early_episode_consistency": bool(
            early_rate is not None
            and early_rate >= float(thresholds["early_major_episode_improvement_rate_min"])
        ),
        "late_episode_consistency": bool(
            late_rate is not None
            and late_rate >= float(thresholds["late_major_episode_improvement_rate_min"])
        ),
        "episode_concentration": bool(
            largest_share <= float(thresholds["largest_episode_improvement_share_max"])
        ),
        "cagr_sacrifice": bool(
            cagr_sacrifice_pp <= float(thresholds["full_sample_cagr_sacrifice_pp_max"])
        ),
    }
    authorized = bool(all(checks.values()))
    return {
        "prospective_monitor_authorized": authorized,
        "decision": (
            "authorize_separate_research_monitor_only"
            if authorized
            else "retain_descriptive_drawdown_profile_only"
        ),
        "major_episode_count": int(len(major)),
        "metrics": {
            "major_episode_drawdown_improvement_rate": improvement_rate,
            "median_major_episode_drawdown_improvement_pp": median_improvement_pp,
            "median_major_episode_recovery_lag_sessions": median_lag,
            "unresolved_major_episode_count": unresolved_major,
            "early_major_episode_improvement_rate": early_rate,
            "late_major_episode_improvement_rate": late_rate,
            "largest_episode_improvement_share": largest_share,
            "full_sample_cagr_sacrifice_pp": cagr_sacrifice_pp,
        },
        "checks": checks,
    }
