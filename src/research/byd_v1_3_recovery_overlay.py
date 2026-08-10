"""Governed BYD V1.3 state-conditioned recovery overlay.

V1.3 leaves canonical V1.0 unchanged and may only add the tactical 25%
sleeve during pre-registered recovery events. The module consumes the
repository-pinned BYD canonical v1 snapshot and treats all history through
2026-08-03 as already observed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.byd_v1_2_recovery_state import (
    CANONICAL_ADJUSTED_SHA256,
    CANONICAL_CUTOFF,
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_SCHEMA,
    EVALUATION_WINDOWS,
    OPEN_LABEL_POLICY,
    CanonicalResearchData,
    StrategyResult,
    _window_metrics,
    build_research_dataset,
    build_v1_0_decision_position,
    run_buy_and_hold,
    run_strategy,
)

SNAPSHOT_PATH = "data/research/byd_canonical_v1_snapshot.tar.xz"
SNAPSHOT_SHA256 = "2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179"
HOLD_ELIGIBLE_INTERVALS = 10
COOLDOWN_ELIGIBLE_OPENS = 10


@dataclass(frozen=True)
class OverlaySchedule:
    final_decision_position: pd.Series
    overlay_active: pd.Series
    overlay_branch: pd.Series
    event_ledger: pd.DataFrame


def branch_conditions(dataset: pd.DataFrame) -> pd.DataFrame:
    """Return the two frozen, mutually exclusive V1.3 branch conditions."""

    branch_a = (
        dataset["market_state"].isin(["bear", "sideways"])
        & dataset["vol_state"].eq("low")
        & dataset["drawdown_252"].le(-0.15)
        & dataset["distance_from_low_20"].ge(0.05)
        & dataset["open_return_autocorr_20"].gt(0.0)
    )
    branch_b = (
        dataset["market_state"].eq("bull")
        & dataset["vol_state"].eq("high")
        & dataset["drawdown_252"].le(-0.10)
        & dataset["distance_from_low_20"].ge(0.05)
        & dataset["momentum_accel_20_60"].gt(0.0)
    )
    conditions = pd.DataFrame(
        {
            "bear_sideways_low_vol": branch_a.fillna(False),
            "bull_high_vol": branch_b.fillna(False),
        },
        index=dataset.index,
    )
    if (conditions.sum(axis=1) > 1).any():
        raise AssertionError("V1.3 overlay branches must remain mutually exclusive")
    return conditions


def build_overlay_schedule(
    dataset: pd.DataFrame,
    base_decision_position: pd.Series,
) -> OverlaySchedule:
    """Build the frozen 10-eligible-open overlay and event clocks.

    An event is triggered at the close on a false-to-true branch transition
    while V1.0 targets 75%. Entry occurs at the next eligible open through the
    shared execution engine. The decision remains active until ten eligible
    open-to-open intervals have been established; quarantined opens do not
    advance holding or cooldown clocks.
    """

    if not dataset.index.equals(base_decision_position.index):
        raise ValueError("base decision position must align with the dataset")
    conditions = branch_conditions(dataset)
    rising = conditions & ~conditions.shift(1, fill_value=False)
    eligible = dataset["open_research_eligible"].astype(bool)

    cooldown = {branch: 0 for branch in conditions.columns}
    active: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    pending_exit_ids: list[int] = []
    active_values: list[bool] = []
    branch_values: list[str] = []

    for date in dataset.index:
        is_eligible = bool(eligible.loc[date])

        if is_eligible:
            for branch in cooldown:
                if cooldown[branch] > 0:
                    cooldown[branch] -= 1
            if pending_exit_ids:
                for event_id in pending_exit_ids:
                    events[event_id - 1]["exit_execution_date"] = date
                pending_exit_ids.clear()

        ended_this_open = False
        if active is not None and is_eligible:
            if active["entry_execution_date"] is None:
                active["entry_execution_date"] = date
            active["eligible_intervals"] += 1
            active["last_active_open_date"] = date
            if active["eligible_intervals"] >= HOLD_ELIGIBLE_INTERVALS:
                active["end_signal_date"] = date
                cooldown[str(active["branch"])] = COOLDOWN_ELIGIBLE_OPENS
                pending_exit_ids.append(int(active["event_id"]))
                active = None
                ended_this_open = True

        if active is None:
            for branch in conditions.columns:
                if (
                    cooldown[branch] == 0
                    and bool(rising.loc[date, branch])
                    and np.isclose(float(base_decision_position.loc[date]), 0.75)
                ):
                    event = {
                        "event_id": len(events) + 1,
                        "branch": branch,
                        "trigger_date": date,
                        "entry_execution_date": None,
                        "last_active_open_date": None,
                        "end_signal_date": None,
                        "exit_execution_date": None,
                        "eligible_intervals": 0,
                        "completed": False,
                    }
                    events.append(event)
                    active = event
                    break

        is_active = active is not None
        active_values.append(is_active)
        branch_values.append(str(active["branch"]) if is_active else "")

        if ended_this_open and active is not None:
            raise AssertionError("an ended event may not restart on the same branch")

    for event in events:
        event["completed"] = bool(
            event["eligible_intervals"] >= HOLD_ELIGIBLE_INTERVALS
            and event["exit_execution_date"] is not None
        )

    overlay_active = pd.Series(
        active_values,
        index=dataset.index,
        name="overlay_active",
        dtype=bool,
    )
    overlay_branch = pd.Series(
        branch_values,
        index=dataset.index,
        name="overlay_branch",
        dtype="string",
    )
    final = base_decision_position.where(~overlay_active, 1.0).astype(float)
    final.name = "decision_position"
    if not set(final.unique()).issubset({0.75, 1.0}):
        raise AssertionError("V1.3 produced an undeclared position")
    if (final + 1e-12 < base_decision_position).any():
        raise AssertionError("V1.3 overlay may not reduce the V1.0 position")

    ledger = pd.DataFrame(events)
    if ledger.empty:
        ledger = pd.DataFrame(
            columns=[
                "event_id",
                "branch",
                "trigger_date",
                "entry_execution_date",
                "last_active_open_date",
                "end_signal_date",
                "exit_execution_date",
                "eligible_intervals",
                "completed",
            ]
        )
    return OverlaySchedule(
        final_decision_position=final,
        overlay_active=overlay_active,
        overlay_branch=overlay_branch,
        event_ledger=ledger,
    )


def _period_name(date: pd.Timestamp) -> str:
    if date <= pd.Timestamp("2022-12-31"):
        return "development"
    if date <= pd.Timestamp("2024-12-31"):
        return "fixed_validation"
    return "retrospective_2025_plus"


def attribute_overlay_events(
    ledger: pd.DataFrame,
    candidate: StrategyResult,
    base: StrategyResult,
) -> pd.DataFrame:
    """Attach incremental return evidence to completed overlay events."""

    if ledger.empty:
        return ledger.assign(
            candidate_return=pd.Series(dtype=float),
            base_return=pd.Series(dtype=float),
            relative_benefit=pd.Series(dtype=float),
            period=pd.Series(dtype="string"),
        )
    rows: list[dict[str, Any]] = []
    for raw in ledger.to_dict(orient="records"):
        row = dict(raw)
        trigger = pd.Timestamp(row["trigger_date"])
        row["period"] = _period_name(trigger)
        if not bool(row["completed"]):
            row.update(
                {
                    "candidate_return": np.nan,
                    "base_return": np.nan,
                    "relative_benefit": np.nan,
                }
            )
            rows.append(row)
            continue
        entry = pd.Timestamp(row["entry_execution_date"])
        exit_ = pd.Timestamp(row["exit_execution_date"])
        candidate_block = candidate.daily.loc[
            (candidate.daily.index >= entry) & (candidate.daily.index < exit_)
        ]
        base_block = base.daily.reindex(candidate_block.index)
        candidate_return = float((1.0 + candidate_block["net_return"]).prod() - 1.0)
        base_return = float((1.0 + base_block["net_return"]).prod() - 1.0)
        relative = (1.0 + candidate_return) / (1.0 + base_return) - 1.0
        row.update(
            {
                "candidate_return": candidate_return,
                "base_return": base_return,
                "relative_benefit": float(relative),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _positive_concentration(events: pd.DataFrame) -> tuple[float, float]:
    completed = events.loc[events["completed"]].copy()
    positive = completed["relative_benefit"].clip(lower=0.0).dropna()
    total = float(positive.sum())
    if total <= 0.0:
        return 1.0, 1.0
    largest_episode_share = float(positive.max() / total)
    period_positive = (
        completed.assign(positive=completed["relative_benefit"].clip(lower=0.0))
        .groupby("period", observed=True)["positive"]
        .sum()
    )
    largest_period_share = float(period_positive.max() / total)
    return largest_episode_share, largest_period_share


def evaluate_v1_3(
    canonical: CanonicalResearchData,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    dataset = build_research_dataset(canonical.adjusted, canonical.sessions)
    base_decision = build_v1_0_decision_position(dataset)
    schedule = build_overlay_schedule(dataset, base_decision)

    primary_cost = float(contract["costs"]["primary_bps_per_turnover_unit"])
    stress_cost = float(contract["costs"]["stress_bps_per_turnover_unit"])
    v1_3 = run_strategy(
        dataset,
        schedule.final_decision_position,
        name="byd_v1_3_recovery_overlay",
        cost_bps_per_turnover_unit=primary_cost,
    )
    v1_3_stress = run_strategy(
        dataset,
        schedule.final_decision_position,
        name="byd_v1_3_recovery_overlay_stress",
        cost_bps_per_turnover_unit=stress_cost,
    )
    v1_0 = run_strategy(
        dataset,
        base_decision,
        name="byd_v1_0_core75_regime_mom_120_canonical",
        cost_bps_per_turnover_unit=primary_cost,
    )
    v1_0_stress = run_strategy(
        dataset,
        base_decision,
        name="byd_v1_0_core75_regime_mom_120_canonical_stress",
        cost_bps_per_turnover_unit=stress_cost,
    )
    buy_hold = run_buy_and_hold(
        dataset,
        cost_bps_per_turnover_unit=primary_cost,
    )

    event_ledger = attribute_overlay_events(
        schedule.event_ledger,
        v1_3,
        v1_0,
    )
    largest_episode_share, largest_period_share = _positive_concentration(event_ledger)

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for window_name, (start, end) in EVALUATION_WINDOWS.items():
        metrics[window_name] = {
            "v1_3": _window_metrics(v1_3, start, end),
            "v1_3_stress": _window_metrics(v1_3_stress, start, end),
            "v1_0": _window_metrics(v1_0, start, end),
            "v1_0_stress": _window_metrics(v1_0_stress, start, end),
            "buy_hold": _window_metrics(buy_hold, start, end),
        }

    full = metrics["full_history"]
    validation = metrics["fixed_validation"]
    recent = metrics["retrospective_2025_plus"]
    completed_event_count = int(event_ledger["completed"].sum())
    incremental_round_trips = (
        full["v1_3"]["round_trips_per_year"] - full["v1_0"]["round_trips_per_year"]
    )
    gates = {
        "full_cagr_shortfall_cap": (full["v1_3"]["cagr"] >= full["v1_0"]["cagr"] - 0.0025),
        "full_drawdown_worsening_cap": (
            full["v1_3"]["max_drawdown"] >= full["v1_0"]["max_drawdown"] - 0.005
        ),
        "full_calmar_strictly_above_v1_0": (full["v1_3"]["calmar"] > full["v1_0"]["calmar"]),
        "validation_total_return_at_least_v1_0": (
            validation["v1_3"]["total_return"] >= validation["v1_0"]["total_return"]
        ),
        "validation_drawdown_worsening_cap": (
            validation["v1_3"]["max_drawdown"] >= validation["v1_0"]["max_drawdown"] - 0.01
        ),
        "retrospective_2025_plus_return_shortfall_cap": (
            recent["v1_3"]["total_return"] >= recent["v1_0"]["total_return"] - 0.01
        ),
        "stress_40_calmar_not_below_v1_0_stress": (
            full["v1_3_stress"]["calmar"] >= full["v1_0_stress"]["calmar"]
        ),
        "incremental_turnover_cap": incremental_round_trips <= 0.50,
        "minimum_completed_overlay_events": completed_event_count >= 10,
        "largest_positive_episode_share_cap": largest_episode_share <= 0.50,
        "largest_positive_period_share_cap": largest_period_share <= 0.60,
    }
    historical_supported = all(gates.values())

    latest_conditions = branch_conditions(dataset).loc[CANONICAL_CUTOFF]
    prospective_ledger = pd.DataFrame(
        [
            {
                "model_id": "byd_v1_3_recovery_overlay",
                "canonical_adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
                "signal_date": CANONICAL_CUTOFF,
                "prospective_start_date": "2026-08-04",
                "execution_date": "",
                "base_target_position": float(base_decision.loc[CANONICAL_CUTOFF]),
                "overlay_active": bool(schedule.overlay_active.loc[CANONICAL_CUTOFF]),
                "overlay_branch": str(schedule.overlay_branch.loc[CANONICAL_CUTOFF]),
                "target_position": float(schedule.final_decision_position.loc[CANONICAL_CUTOFF]),
                "branch_a_condition": bool(latest_conditions["bear_sideways_low_vol"]),
                "branch_b_condition": bool(latest_conditions["bull_high_vol"]),
                "status": "awaiting_first_post_cutoff_eligible_open",
                "realized_incremental_return": np.nan,
            }
        ]
    )

    return {
        "decision": (
            "byd_v1_3_historically_supported_prospective_confirmation_required"
            if historical_supported
            else "byd_v1_3_not_supported"
        ),
        "historical_supported": historical_supported,
        "research_only": True,
        "trade_ready": False,
        "prospective_confirmation_required": historical_supported,
        "canonical_identity": {
            "snapshot_path": SNAPSHOT_PATH,
            "snapshot_sha256": SNAPSHOT_SHA256,
            "schema": CANONICAL_SCHEMA,
            "adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "cutoff": CANONICAL_CUTOFF,
            "open_label_policy": OPEN_LABEL_POLICY,
        },
        "metrics": metrics,
        "gates": gates,
        "completed_event_count": completed_event_count,
        "incremental_round_trips_per_year": float(incremental_round_trips),
        "largest_positive_episode_share": largest_episode_share,
        "largest_positive_period_share": largest_period_share,
        "dataset": dataset,
        "schedule": schedule,
        "event_ledger": event_ledger,
        "v1_3": v1_3,
        "v1_0": v1_0,
        "buy_hold": buy_hold,
        "prospective_ledger": prospective_ledger,
    }
