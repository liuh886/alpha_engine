"""Post-diagnostic one-session confirmation ablations for v4.2.

This module follows the state-2 tail diagnostic. It distinguishes a mechanical
execution delay from a persistence requirement and isolates confirmation on the
0->1 bridge entry and the 1->2 leverage entry. No active baseline rule changes.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS,
    bridge_weights_for_states,
)

STATE_LABELS = {0: "defensive", 1: "attack", 2: "partial_leverage"}


def confirmed_execution_states(
    decisions: pd.Series,
    *,
    mode: str,
) -> pd.Series:
    """Require selected close decisions to persist for one additional session."""

    valid_modes = {
        "baseline",
        "bridge_entry_confirmation_1",
        "leverage_entry_confirmation_1",
        "risk_increase_confirmation_1",
        "risk_reduction_confirmation_1",
        "all_transitions_confirmation_1",
    }
    if mode not in valid_modes:
        raise ValueError(f"unsupported confirmation mode: {mode}")
    targets = decisions.shift(1).fillna(0).astype(int)
    if mode == "baseline":
        return targets

    def needs_confirmation(current: int, target: int) -> bool:
        if mode == "all_transitions_confirmation_1":
            return target != current
        if mode == "bridge_entry_confirmation_1":
            return current == 0 and target == 1
        if mode == "leverage_entry_confirmation_1":
            return current < 2 and target == 2
        if mode == "risk_increase_confirmation_1":
            return target > current
        if mode == "risk_reduction_confirmation_1":
            return target < current
        return False

    current = 0
    pending_target: int | None = None
    executed: list[int] = []
    for target in targets:
        target = int(target)
        if target == current:
            pending_target = None
            executed.append(current)
            continue
        if not needs_confirmation(current, target):
            current = target
            pending_target = None
        elif pending_target == target:
            current = target
            pending_target = None
        else:
            pending_target = target
        executed.append(current)
    return pd.Series(executed, index=decisions.index, dtype=int)


def fixed_execution_delay_states(
    decisions: pd.Series,
    *,
    sessions: int,
) -> pd.Series:
    """Apply a mechanical fixed delay without a persistence requirement."""

    if sessions < 0:
        raise ValueError("sessions must be non-negative")
    return decisions.shift(1 + sessions).fillna(0).astype(int)


def run_confirmation_scenario(
    source: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    scenario: str,
) -> StrategyResult:
    """Reprice the frozen v4.2 decisions under one timing ablation."""

    daily = source.copy()
    if scenario == "fixed_execution_delay_1":
        states = fixed_execution_delay_states(
            daily["decision_state"].astype(int),
            sessions=1,
        )
    else:
        states = confirmed_execution_states(
            daily["decision_state"].astype(int),
            mode=scenario,
        )
    daily["position_state"] = states
    daily["position_label"] = states.map(STATE_LABELS)
    weights = bridge_weights_for_states(states, contract)
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]
    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if bool(contract["portfolio"]["charge_initial_entry"]) and not turnover.empty:
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    else:
        turnover.iloc[0] = 0.0
    cost_bps = float(
        contract["portfolio"]["transaction_cost_bps_per_turnover_unit"]
    )
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(
            contract["portfolio"]["annual_risk_free_rate"]
        ),
    )
    metrics.update(
        {
            "strategy": scenario,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(
                daily["transaction_cost"].sum()
            ),
            "state_0_sessions": int(states.eq(0).sum()),
            "state_1_sessions": int(states.eq(1).sum()),
            "state_2_sessions": int(states.eq(2).sum()),
        }
    )
    return StrategyResult(scenario, daily, pd.DataFrame(), metrics)


def scenario_difference_events(
    baseline: StrategyResult,
    challenger: StrategyResult,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attribute contiguous periods where a scenario differs from v4.2."""

    common = baseline.daily.index.intersection(challenger.daily.index)
    left = baseline.daily.loc[common]
    right = challenger.daily.loc[common]
    changed = left["position_state"].astype(int).ne(
        right["position_state"].astype(int)
    )
    rows: list[dict[str, Any]] = []
    groups = changed.ne(changed.shift()).cumsum()
    event_number = 0
    for _, mask in changed.groupby(groups):
        if not bool(mask.iloc[0]):
            continue
        event_number += 1
        dates = mask.index
        start_date = dates[0]
        end_date = dates[-1]
        base_interval = left.loc[start_date:end_date]
        challenger_interval = right.loc[start_date:end_date]
        base_net = float((1.0 + base_interval["net_return"]).prod() - 1.0)
        challenger_net = float(
            (1.0 + challenger_interval["net_return"]).prod() - 1.0
        )
        rows.append(
            {
                "event_id": event_number,
                "start_date": start_date,
                "end_date": end_date,
                "sessions": int(len(dates)),
                "baseline_states": ",".join(
                    map(
                        str,
                        base_interval["position_state"].astype(int).tolist(),
                    )
                ),
                "challenger_states": ",".join(
                    map(
                        str,
                        challenger_interval["position_state"].astype(int).tolist(),
                    )
                ),
                "baseline_net_return": base_net,
                "challenger_net_return": challenger_net,
                "net_return_delta": challenger_net - base_net,
                "baseline_turnover_units": float(
                    base_interval["turnover_units"].sum()
                ),
                "challenger_turnover_units": float(
                    challenger_interval["turnover_units"].sum()
                ),
                "turnover_saved": float(
                    base_interval["turnover_units"].sum()
                    - challenger_interval["turnover_units"].sum()
                ),
            }
        )
    events = pd.DataFrame(rows)
    if events.empty:
        return events, pd.DataFrame()
    positive = events["net_return_delta"].clip(lower=0.0)
    total_positive = float(positive.sum())
    top_positive_share = (
        float(positive.max() / total_positive)
        if total_positive > 1e-12
        else 0.0
    )
    summary = pd.DataFrame(
        [
            {
                "events": int(len(events)),
                "positive_event_rate": float(
                    events["net_return_delta"].gt(0.0).mean()
                ),
                "mean_net_return_delta": float(
                    events["net_return_delta"].mean()
                ),
                "total_arithmetic_net_return_delta": float(
                    events["net_return_delta"].sum()
                ),
                "top_positive_event_share": top_positive_share,
                "total_turnover_saved": float(
                    events["turnover_saved"].sum()
                ),
            }
        ]
    )
    return events, summary


def _segment_metrics(
    result: StrategyResult,
    *,
    split_location: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment, returns in (
        ("early", result.daily["net_return"].iloc[:split_location]),
        ("late", result.daily["net_return"].iloc[split_location:]),
    ):
        metrics = _return_metrics(returns)
        metrics.update({"segment": segment, "strategy": result.name})
        rows.append(metrics)
    return rows


def run_confirmation_comparison(
    baseline_result: StrategyResult,
    contract: Mapping[str, Any],
    *,
    train_fraction: float = 0.60,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, StrategyResult],
]:
    """Run the fixed-delay benchmark and three predeclared confirmations."""

    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    source = baseline_result.daily.copy()
    scenario_names = (
        "baseline",
        "fixed_execution_delay_1",
        "bridge_entry_confirmation_1",
        "leverage_entry_confirmation_1",
        "risk_increase_confirmation_1",
        "risk_reduction_confirmation_1",
        "all_transitions_confirmation_1",
    )
    results = {
        name: run_confirmation_scenario(
            source,
            contract,
            scenario=name,
        )
        for name in scenario_names
    }
    baseline = results["baseline"]
    if not baseline.daily["position_state"].equals(
        baseline_result.daily["position_state"].astype(int)
    ):
        raise AssertionError("confirmation baseline changed the v4.2 trace")
    if not np.allclose(
        baseline.daily["net_return"].to_numpy(dtype=float),
        baseline_result.daily["net_return"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise AssertionError("confirmation baseline does not reproduce v4.2")

    table = pd.DataFrame(
        [dict(result.metrics) for result in results.values()]
    ).set_index("strategy")
    base_metrics = table.loc["baseline"]
    for metric in (
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
    ):
        table[f"{metric}_delta_vs_baseline"] = (
            table[metric] - float(base_metrics[metric])
        )

    split = max(1, min(len(source) - 1, int(len(source) * train_fraction)))
    segment_rows: list[dict[str, Any]] = []
    event_frames: list[pd.DataFrame] = []
    event_summary_rows: list[dict[str, Any]] = []
    for key, result in results.items():
        segment_rows.extend(_segment_metrics(result, split_location=split))
        if key in {
            "bridge_entry_confirmation_1",
            "leverage_entry_confirmation_1",
            "risk_increase_confirmation_1",
        }:
            events, event_summary = scenario_difference_events(
                baseline, result
            )
            if not events.empty:
                events.insert(0, "scenario", key)
                event_frames.append(events)
            row = {"scenario": key}
            if not event_summary.empty:
                row.update(event_summary.iloc[0].to_dict())
            event_summary_rows.append(row)
    events = (
        pd.concat(event_frames, ignore_index=True)
        if event_frames
        else pd.DataFrame()
    )
    event_summary = pd.DataFrame(event_summary_rows)
    segments = pd.DataFrame(segment_rows)
    return table.sort_index(), segments, events, results


def confirmation_research_gate(
    metrics: pd.DataFrame,
    segments: pd.DataFrame,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the combined risk-increase confirmation without promoting it."""

    candidate = "risk_increase_confirmation_1"
    baseline = metrics.loc["baseline"]
    challenger = metrics.loc[candidate]
    rules = contract["promotion_gate"]
    candidate_events = events.loc[events["scenario"].eq(candidate)]
    positive = candidate_events["net_return_delta"].clip(lower=0.0)
    positive_sum = float(positive.sum())
    top_share = (
        float(positive.max() / positive_sum)
        if positive_sum > 1e-12
        else 0.0
    )
    positive_rate = float(
        candidate_events["net_return_delta"].gt(0.0).mean()
    )
    segment_table = segments.set_index(["strategy", "segment"])
    early_delta = float(
        segment_table.loc[(candidate, "early"), "cagr"]
        - segment_table.loc[("baseline", "early"), "cagr"]
    )
    late_delta = float(
        segment_table.loc[(candidate, "late"), "cagr"]
        - segment_table.loc[("baseline", "late"), "cagr"]
    )
    gates = {
        "cagr_improves": float(challenger["cagr"]) > float(baseline["cagr"]),
        "sharpe_improves": float(challenger["sharpe"])
        > float(baseline["sharpe"]),
        "sortino_improves": float(challenger["sortino"])
        > float(baseline["sortino"]),
        "calmar_improves": float(challenger["calmar"])
        > float(baseline["calmar"]),
        "max_drawdown_within_tolerance": float(
            challenger["max_drawdown"] - baseline["max_drawdown"]
        )
        >= -float(rules["max_drawdown_worsening_tolerance"]),
        "turnover_not_higher": float(challenger["turnover_units"])
        <= float(baseline["turnover_units"]),
        "positive_event_rate": positive_rate
        >= float(rules["min_positive_event_rate"]),
        "top_event_not_dominant": top_share
        <= float(rules["max_top_positive_event_share"]),
        "early_segment_positive": early_delta > 0.0,
        "late_segment_positive": late_delta > 0.0,
    }
    passes = all(gates.values())
    return {
        "passes_retrospective_research_gate": passes,
        "promotion_authorized": False,
        "next_direction": (
            "open_separate_prospective_confirmation_challenger"
            if passes
            else "retain_v4_2_and_reject_confirmation_challenger"
        ),
        "gates": gates,
        "measured": {
            "positive_event_rate": positive_rate,
            "top_positive_event_share": top_share,
            "early_segment_cagr_delta": early_delta,
            "late_segment_cagr_delta": late_delta,
            "turnover_delta": float(
                challenger["turnover_units"] - baseline["turnover_units"]
            ),
        },
    }
