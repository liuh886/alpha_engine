#!/usr/bin/env python3
"""Evaluate the frozen Issue #738 BYD event-triggered recovery lifecycle.

This challenger keeps the recovery detector and +25pp re-risk magnitude fixed,
but separates event detection from exit lifecycle. Historical evidence is
consumed and cannot authorize promotion.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.byd_515180_allocation import WINDOWS, metrics, prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    build_decisions as build_v12_decisions,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    run_financed_allocation,
)
from src.research.rules_based_allocation_experiment_runner import (
    _extract_inputs,
    _formal_daily,
    _formal_section,
    _load_formal,
    _load_spec,
    _trace_reproduction,
)

SPEC = PROJECT_ROOT / "configs/research_experiments/byd_v1_3_min_hold_bear_defense_certification_v1.yaml"
CHALLENGER = "byd_recovery_event_hold20_v1"
POINTWISE = "byd_recovery_pointwise_v1"
RECOVERY_THRESHOLD = 0.026937
HOLD_ELIGIBLE_SESSIONS = 20
PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
EPS = 1e-12


def _wealth(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod()) if not clean.empty else 1.0


def _window_metrics(daily: pd.DataFrame, window: str) -> dict[str, float]:
    start, end = WINDOWS[window]
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    output = metrics(block)
    returns = block["net_return"].dropna()
    output["financed_sessions"] = float(
        block.loc[returns.index, "borrowed_weight"].gt(EPS).sum()
    )
    output["transaction_cost_paid"] = float(block.loc[returns.index, "cost"].sum())
    output["financing_cost_paid"] = float(
        block.loc[returns.index, "financing_cost"].sum()
    )
    return output


def _relative_wealth(candidate: pd.DataFrame, baseline: pd.DataFrame, start: str, end: str) -> float:
    c = _wealth(candidate.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"])
    b = _wealth(baseline.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"])
    return c / b - 1.0


def _build_detector(base: pd.Series, factor: pd.Series) -> pd.Series:
    return (base.eq(0.75) & factor.ge(RECOVERY_THRESHOLD)).astype(bool)


def _pointwise_decision(
    champion_decision: pd.DataFrame,
    detector: pd.Series,
) -> pd.DataFrame:
    decision = champion_decision.copy(deep=True)
    decision.loc[detector, "byd_weight"] = 1.0
    decision.loc[detector, "etf_weight"] = 0.0
    decision.loc[detector, "cash_weight"] = 0.0
    return decision


def _event_lifecycle_decision(
    champion_decision: pd.DataFrame,
    base: pd.Series,
    detector: pd.Series,
    eligible: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (
        champion_decision.index.equals(base.index)
        and base.index.equals(detector.index)
        and detector.index.equals(eligible.index)
    ):
        raise ValueError("event lifecycle inputs must share one index")

    event = detector & ~detector.shift(1, fill_value=False)
    active = False
    remaining = 0
    lifecycle_id = 0
    active_values: list[bool] = []
    id_values: list[int] = []
    start_values: list[bool] = []
    remaining_values: list[int] = []
    termination_values: list[str] = []

    for i, date in enumerate(detector.index):
        termination = ""
        if active and float(base.iloc[i]) >= 1.0 - EPS:
            active = False
            remaining = 0
            termination = "core_recovered"

        started = False
        if not active and bool(event.iloc[i]) and float(base.iloc[i]) == 0.75:
            active = True
            remaining = HOLD_ELIGIBLE_SESSIONS
            lifecycle_id += 1
            started = True

        overlay_now = active and float(base.iloc[i]) == 0.75
        active_values.append(overlay_now)
        id_values.append(lifecycle_id if overlay_now else 0)
        start_values.append(started)
        remaining_values.append(remaining if overlay_now else 0)
        termination_values.append(termination)

        next_open_eligible = i + 1 < len(eligible) and bool(eligible.iloc[i + 1])
        if overlay_now and next_open_eligible:
            remaining -= 1
            if remaining <= 0:
                active = False
                remaining = 0
                termination_values[-1] = "max_hold"

    overlay = pd.Series(active_values, index=detector.index, dtype=bool)
    decision = champion_decision.copy(deep=True)
    decision.loc[overlay, "byd_weight"] = 1.0
    decision.loc[overlay, "etf_weight"] = 0.0
    decision.loc[overlay, "cash_weight"] = 0.0

    changed = decision.ne(champion_decision).any(axis=1)
    if not changed.equals(overlay):
        raise AssertionError("event lifecycle changed outside its declared overlay")
    if (changed & base.ne(0.75)).any():
        raise AssertionError("event lifecycle changed a non-defensive core state")
    if not np.allclose(decision.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("event lifecycle weights do not sum to one")

    state = pd.DataFrame(
        {
            "detector": detector,
            "event": event,
            "overlay_decision_active": overlay,
            "lifecycle_id": id_values,
            "lifecycle_started": start_values,
            "remaining_eligible_sessions_before_decision": remaining_values,
            "termination_on_decision": termination_values,
        },
        index=detector.index,
    )
    return decision, state


def _evaluation(
    common: pd.DataFrame,
    champion_decision: pd.DataFrame,
    pointwise_decision: pd.DataFrame,
    event_decision: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scenario_results: dict[str, Any] = {}
    for scenario, cost_bps, financing_rate in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE),
    ):
        champion = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        pointwise = run_financed_allocation(
            POINTWISE,
            common,
            pointwise_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        event = run_financed_allocation(
            CHALLENGER,
            common,
            event_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        scenario_results[scenario] = {
            "champion": champion,
            "pointwise": pointwise,
            "event": event,
        }
        for window, (start, end) in WINDOWS.items():
            champion_metrics = _window_metrics(champion.daily, window)
            pointwise_metrics = _window_metrics(pointwise.daily, window)
            event_metrics = _window_metrics(event.daily, window)
            rows.append(
                {
                    "scenario": scenario,
                    "window": window,
                    "champion": champion_metrics,
                    "pointwise": pointwise_metrics,
                    "event": event_metrics,
                    "event_minus_champion": {
                        "cagr": event_metrics["cagr"] - champion_metrics["cagr"],
                        "sharpe": event_metrics["sharpe"] - champion_metrics["sharpe"],
                        "max_drawdown": event_metrics["max_drawdown"]
                        - champion_metrics["max_drawdown"],
                        "calmar": event_metrics["calmar"] - champion_metrics["calmar"],
                        "turnover_units": event_metrics["turnover_units"]
                        - champion_metrics["turnover_units"],
                        "relative_terminal_wealth": _relative_wealth(
                            event.daily, champion.daily, start, end
                        ),
                    },
                    "event_minus_pointwise": {
                        "cagr": event_metrics["cagr"] - pointwise_metrics["cagr"],
                        "sharpe": event_metrics["sharpe"] - pointwise_metrics["sharpe"],
                        "relative_terminal_wealth": _relative_wealth(
                            event.daily, pointwise.daily, start, end
                        ),
                    },
                }
            )
    return rows, scenario_results


def _episodes(mask: pd.Series) -> pd.DataFrame:
    active = mask.fillna(False).astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    ids = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in active.groupby(ids):
        if pd.isna(raw_id):
            continue
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
            }
        )
    return pd.DataFrame(rows)


def _episode_attribution(
    champion: pd.DataFrame,
    event: pd.DataFrame,
    base: pd.Series,
) -> list[dict[str, Any]]:
    active = event["position_byd_weight"].gt(champion["position_byd_weight"] + EPS)
    table = _episodes(active)
    rows: list[dict[str, Any]] = []
    for episode in table.itertuples(index=False):
        c = event.loc[episode.start : episode.end, "net_return"]
        b = champion.loc[episode.start : episode.end, "net_return"]
        relative = _wealth(c) / _wealth(b) - 1.0
        end_pos = base.index.get_loc(pd.Timestamp(episode.end))
        if not isinstance(end_pos, int):
            raise RuntimeError("event episode end lookup is ambiguous")
        next_base = base.iloc[min(end_pos + 1, len(base) - 1)]
        termination = (
            "core_recovered"
            if float(next_base) >= 1.0 - EPS and int(episode.sessions) < HOLD_ELIGIBLE_SESSIONS
            else "max_hold_or_sample_end"
        )
        rows.append(
            {
                "episode_id": int(episode.episode_id),
                "start": pd.Timestamp(episode.start).strftime("%Y-%m-%d"),
                "end": pd.Timestamp(episode.end).strftime("%Y-%m-%d"),
                "sessions": int(episode.sessions),
                "year": int(pd.Timestamp(episode.start).year),
                "relative_terminal_wealth": float(relative),
                "termination": termination,
            }
        )
    positive_total = sum(max(row["relative_terminal_wealth"], 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(row["relative_terminal_wealth"], 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return rows


def _period_attribution(champion: pd.DataFrame, event: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in ("development", "fixed_validation", "retrospective_2025_plus"):
        start, end = WINDOWS[window]
        rows.append(
            {
                "window": window,
                "relative_terminal_wealth": _relative_wealth(event, champion, start, end),
            }
        )
    positive_total = sum(max(row["relative_terminal_wealth"], 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(row["relative_terminal_wealth"], 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return rows


def _annual(champion: pd.DataFrame, pointwise: pd.DataFrame, event: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in sorted(set(champion.index.year)):
        idx = champion.index[champion.index.year == year]
        rows.append(
            {
                "year": int(year),
                "champion_return": _wealth(champion.loc[idx, "net_return"]) - 1.0,
                "pointwise_return": _wealth(pointwise.loc[idx, "net_return"]) - 1.0,
                "event_return": _wealth(event.loc[idx, "net_return"]) - 1.0,
                "event_vs_champion_relative_wealth": _wealth(event.loc[idx, "net_return"])
                / _wealth(champion.loc[idx, "net_return"])
                - 1.0,
                "event_vs_pointwise_relative_wealth": _wealth(event.loc[idx, "net_return"])
                / _wealth(pointwise.loc[idx, "net_return"])
                - 1.0,
                "event_recovery_sessions": int(
                    event.loc[idx, "position_byd_weight"].gt(
                        champion.loc[idx, "position_byd_weight"] + EPS
                    ).sum()
                ),
            }
        )
    return rows


def _gate_result(
    evaluation: list[dict[str, Any]],
    period: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    annual: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {(row["scenario"], row["window"]): row for row in evaluation}
    primary_full = by_key[("primary", "full_overlap")]
    primary_fixed = by_key[("primary", "fixed_validation")]
    primary_recent = by_key[("primary", "retrospective_2025_plus")]
    stress_full = by_key[("stress", "full_overlap")]
    stress_recent = by_key[("stress", "retrospective_2025_plus")]
    y2026 = next(row for row in annual if row["year"] == 2026)

    max_period_share = max((row["positive_contribution_share"] for row in period), default=0.0)
    max_episode_share = max((row["positive_contribution_share"] for row in episodes), default=0.0)
    champion_turnover = float(primary_full["champion"]["turnover_units"])
    event_turnover = float(primary_full["event"]["turnover_units"])

    gates = {
        "full_cagr_delta_ge_minus_50bp": float(primary_full["event_minus_champion"]["cagr"]) >= -0.005,
        "full_sharpe_delta_nonnegative": float(primary_full["event_minus_champion"]["sharpe"]) >= 0.0,
        "mdd_deterioration_le_100bp": float(primary_full["event_minus_champion"]["max_drawdown"]) >= -0.01,
        "fixed_validation_relative_wealth_nonnegative": float(
            primary_fixed["event_minus_champion"]["relative_terminal_wealth"]
        ) >= 0.0,
        "recent_relative_wealth_nonnegative": float(
            primary_recent["event_minus_champion"]["relative_terminal_wealth"]
        ) >= 0.0,
        "year_2026_relative_wealth_nonnegative": float(
            y2026["event_vs_champion_relative_wealth"]
        ) >= 0.0,
        "stress_full_relative_wealth_nonnegative": float(
            stress_full["event_minus_champion"]["relative_terminal_wealth"]
        ) >= 0.0,
        "stress_recent_relative_wealth_nonnegative": float(
            stress_recent["event_minus_champion"]["relative_terminal_wealth"]
        ) >= 0.0,
        "period_positive_concentration_le_60pct": float(max_period_share) <= 0.60 + EPS,
        "largest_positive_episode_share_le_50pct": float(max_episode_share) <= 0.50 + EPS,
        "turnover_le_1_5x_champion": event_turnover <= champion_turnover * 1.5 + EPS,
    }
    return {
        "gates": gates,
        "passed": int(sum(gates.values())),
        "total": len(gates),
        "all_pass": bool(all(gates.values())),
        "max_period_positive_contribution_share": float(max_period_share),
        "max_episode_positive_contribution_share": float(max_episode_share),
        "champion_turnover_units": champion_turnover,
        "event_turnover_units": event_turnover,
    }


def run() -> dict[str, Any]:
    spec = _load_spec(SPEC)
    with tempfile.TemporaryDirectory(prefix="byd-recovery-event-") as raw_root:
        root = Path(raw_root)
        byd_dir, etf_dir, data_identity = _extract_inputs(spec, root)
        common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
        cutoff = pd.Timestamp(str(spec["data"]["historical_cutoff"]))
        common = common.loc[:cutoff].copy()
        signals = signals.reindex(common.index)

        standard_results, _ = run_v12_candidates(
            common,
            signals,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        formal = _load_formal(spec)
        performance_path, performance_sha = _formal_section(
            formal,
            "performance",
            str(spec["baseline"]["performance_sha256"]),
        )
        formal_daily = _formal_daily(performance_path, str(cutoff.date()))
        formal_trace = _trace_reproduction(
            formal_daily, standard_results[V12_MODEL_ID].daily
        )
        if not formal_trace["exact"]:
            raise RuntimeError("event lifecycle refuses a non-exact V1.2 Champion")

        decisions, _ = build_v12_decisions(common, signals)
        champion_decision = decisions[V12_MODEL_ID]
        champion_rebuilt = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        rebuilt_trace = _trace_reproduction(formal_daily, champion_rebuilt.daily)
        if not rebuilt_trace["exact"]:
            raise RuntimeError("rebuilt V1.2 path does not match accepted formal trace")

        canonical = load_canonical_snapshot(byd_dir)
        full = build_research_dataset(canonical.adjusted, canonical.sessions)
        full.index = pd.to_datetime(full.index).normalize()
        factor = full["drawdown252_x_rebound60"].reindex(common.index).astype(float)
        base = signals["base_byd_weight"].astype(float)
        detector = _build_detector(base, factor)
        pointwise_decision = _pointwise_decision(champion_decision, detector)
        event_decision, lifecycle_state = _event_lifecycle_decision(
            champion_decision,
            base,
            detector,
            common["common_open_eligible"].astype(bool),
        )

        evaluation, scenario_results = _evaluation(
            common, champion_decision, pointwise_decision, event_decision
        )
        primary = scenario_results["primary"]
        champion_daily = primary["champion"].daily
        pointwise_daily = primary["pointwise"].daily
        event_daily = primary["event"].daily
        episodes = _episode_attribution(champion_daily, event_daily, base)
        period = _period_attribution(champion_daily, event_daily)
        annual = _annual(champion_daily, pointwise_daily, event_daily)
        gates = _gate_result(evaluation, period, episodes, annual)

    return {
        "schema_version": "1.0",
        "issue": 738,
        "challenger": CHALLENGER,
        "research_only": True,
        "historical_evidence_consumed": True,
        "automatic_promotion": False,
        "prospective_confirmation_required": True,
        "frozen_contract": {
            "detector_threshold": RECOVERY_THRESHOLD,
            "hold_common_open_eligible_sessions": HOLD_ELIGIBLE_SESSIONS,
            "entry": "false_to_true_detector_edge then next common eligible open",
            "overlay": "75% BYD + 25% 515180 -> 100% BYD while lifecycle active",
            "early_termination": "unchanged V1.2 core returns to 100%",
            "detector_flicker_exit": False,
            "retrigger_requires_new_edge": True,
        },
        "baseline": {
            "model_id": V12_MODEL_ID,
            "bundle_id": formal.bundle_id,
            "performance_sha256": performance_sha,
            "formal_trace_reproduction": formal_trace,
            "rebuilt_trace_reproduction": rebuilt_trace,
        },
        "data_identity": data_identity,
        "evaluation": evaluation,
        "annual_attribution": annual,
        "period_attribution": period,
        "episode_attribution": episodes,
        "lifecycle_decision_counts": {
            "detector_events": int(lifecycle_state["event"].sum()),
            "lifecycle_starts": int(lifecycle_state["lifecycle_started"].sum()),
            "core_recovery_terminations": int(
                lifecycle_state["termination_on_decision"].eq("core_recovered").sum()
            ),
            "max_hold_terminations": int(
                lifecycle_state["termination_on_decision"].eq("max_hold").sum()
            ),
        },
        "gates": gates,
        "decision": "historically_supported" if gates["all_pass"] else "not_supported",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts/research/byd_recovery_event_lifecycle_v1.json",
    )
    args = parser.parse_args()
    payload = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
