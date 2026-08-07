"""Locked evaluator for spec-driven research experiments.

The experiment spec owns window roles and numeric thresholds. Candidate runners
may produce observations, but they do not get to decide which windows select a
winner or how support gates are evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import prod
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ExperimentContract:
    experiment_id: str
    baseline_candidate_id: str
    selection_windows: tuple[str, ...]
    reporting_windows: tuple[str, ...]
    base_cost_bps: int
    stress_cost_bps: int
    decision: str
    thresholds: dict[str, float | bool]
    ranking: tuple[str, ...]
    provider_identity_sha256: str
    cutoff: str


def load_experiment_contract(path: str | Path) -> ExperimentContract:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("experiment spec must be a mapping")

    windows = raw.get("windows") or {}
    selection = tuple(str(value) for value in windows.get("candidate_selection", []))
    reporting = tuple(str(value) for value in windows.get("consumed_reporting_only", []))
    if not selection:
        raise ValueError("candidate_selection must contain at least one window")
    overlap = sorted(set(selection) & set(reporting))
    if overlap:
        raise ValueError(f"selection/reporting windows overlap: {overlap}")
    if windows.get("consumed_reporting_may_enter_selection") is not False:
        raise ValueError("consumed_reporting_may_enter_selection must be explicitly false")

    evaluation = raw.get("evaluation") or {}
    thresholds = evaluation.get("thresholds") or {}
    required_thresholds = {
        "min_window_relative_excess",
        "min_worst_drawdown",
        "min_stress_compounded_relative_excess",
        "max_strongest_positive_window_share",
        "min_mean_rank_ic_improvement",
        "require_factor_baseline_dominance",
    }
    missing = sorted(required_thresholds - set(thresholds))
    if missing:
        raise ValueError(f"evaluation.thresholds missing: {missing}")

    base_cost_bps = int((raw.get("execution") or {}).get("base_cost_bps", 0))
    stress_cost_bps = int(evaluation.get("stress_cost_bps", 0))
    declared_stresses = {
        int(value) for value in (raw.get("execution") or {}).get("cost_stress_bps", [])
    }
    if base_cost_bps <= 0 or stress_cost_bps <= 0:
        raise ValueError("base and stress costs must be positive")
    if stress_cost_bps not in declared_stresses:
        raise ValueError("evaluation stress cost is not declared by execution")

    ranking = tuple(str(value) for value in evaluation.get("ranking", []))
    if not ranking:
        raise ValueError("evaluation.ranking must not be empty")

    snapshot = raw.get("snapshot") or {}
    return ExperimentContract(
        experiment_id=str(raw["experiment_id"]),
        baseline_candidate_id=str(evaluation["baseline_candidate_id"]),
        selection_windows=selection,
        reporting_windows=reporting,
        base_cost_bps=base_cost_bps,
        stress_cost_bps=stress_cost_bps,
        decision=str(evaluation["decision"]),
        thresholds=dict(thresholds),
        ranking=ranking,
        provider_identity_sha256=str(snapshot.get("provider_identity_sha256", "")),
        cutoff=str(snapshot.get("cutoff", "")),
    )


def _compound(values: list[float]) -> float:
    return prod(1.0 + value for value in values) - 1.0


def _selection_rows(
    contract: ExperimentContract,
    observations: list[dict[str, Any]],
    candidate_id: str,
    cost_bps: int,
) -> list[dict[str, Any]]:
    by_window: dict[str, dict[str, Any]] = {}
    for row in observations:
        if str(row.get("candidate_id")) != candidate_id:
            continue
        if int(row.get("cost_bps", -1)) != cost_bps:
            continue
        window = str(row.get("window"))
        if window not in contract.selection_windows:
            continue
        if window in by_window:
            raise ValueError(f"duplicate observation for {candidate_id}/{window}/{cost_bps}bps")
        by_window[window] = row

    missing = [window for window in contract.selection_windows if window not in by_window]
    if missing:
        raise ValueError(
            f"candidate {candidate_id} missing selection windows at {cost_bps}bps: {missing}"
        )
    return [by_window[window] for window in contract.selection_windows]


def _candidate_metrics(
    contract: ExperimentContract,
    observations: list[dict[str, Any]],
    candidate_id: str,
    candidate_metadata: dict[str, dict[str, Any]],
    baseline_rank_ic: float,
) -> dict[str, Any]:
    base_rows = _selection_rows(contract, observations, candidate_id, contract.base_cost_bps)
    stress_rows = _selection_rows(contract, observations, candidate_id, contract.stress_cost_bps)

    relative_excess = [float(row["relative_excess"]) for row in base_rows]
    stress_relative_excess = [float(row["relative_excess"]) for row in stress_rows]
    drawdowns = [float(row["max_drawdown"]) for row in base_rows]
    rank_ics = [float(row["rank_ic"]) for row in base_rows]
    positives = [max(value, 0.0) for value in relative_excess]
    positive_total = sum(positives)
    strongest_share = max(positives) / positive_total if positive_total > 0 else 1.0
    mean_rank_ic = sum(rank_ics) / len(rank_ics)
    metadata = candidate_metadata.get(candidate_id, {})

    return {
        "candidate_id": candidate_id,
        "evaluated_windows": list(contract.selection_windows),
        "compounded_relative_excess": _compound(relative_excess),
        "all_development_windows_positive_excess": all(
            value > float(contract.thresholds["min_window_relative_excess"])
            for value in relative_excess
        ),
        "worst_drawdown": min(drawdowns),
        "stress_compounded_relative_excess": _compound(stress_relative_excess),
        "strongest_positive_window_share": strongest_share,
        "mean_rank_ic": mean_rank_ic,
        "mean_rank_ic_improvement": mean_rank_ic - baseline_rank_ic,
        "dominates_factor_baselines": bool(metadata.get("dominates_factor_baselines", False)),
        "concentration": float(metadata.get("concentration", 1.0)),
    }


def _gate_checks(contract: ExperimentContract, metrics: dict[str, Any]) -> dict[str, bool]:
    thresholds = contract.thresholds
    return {
        "all_development_windows_positive_excess": bool(
            metrics["all_development_windows_positive_excess"]
        ),
        "worst_drawdown": float(metrics["worst_drawdown"])
        >= float(thresholds["min_worst_drawdown"]),
        "stress_compounded_relative_excess": float(metrics["stress_compounded_relative_excess"])
        > float(thresholds["min_stress_compounded_relative_excess"]),
        "strongest_positive_window_share": float(metrics["strongest_positive_window_share"])
        < float(thresholds["max_strongest_positive_window_share"]),
        "mean_rank_ic_improvement": float(metrics["mean_rank_ic_improvement"])
        >= float(thresholds["min_mean_rank_ic_improvement"]),
        "factor_baseline_dominance": (
            bool(metrics["dominates_factor_baselines"])
            if bool(thresholds["require_factor_baseline_dominance"])
            else True
        ),
    }


def _ranking_value(metric: str, row: dict[str, Any]) -> float:
    if metric == "gate_pass_count":
        return float(row["gate_pass_count"])
    if metric in {"worst_drawdown", "compounded_relative_excess"}:
        return float(row[metric])
    if metric == "lower_concentration":
        return -float(row["concentration"])
    raise ValueError(f"unsupported ranking metric: {metric}")


def evaluate_experiment(
    contract: ExperimentContract,
    observations: list[dict[str, Any]],
    *,
    candidate_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate candidates using selection windows only and emit a deterministic receipt."""

    candidate_metadata = candidate_metadata or {}
    candidate_ids = sorted(
        {
            str(row["candidate_id"])
            for row in observations
            if str(row.get("window")) in contract.selection_windows
        }
    )
    if contract.baseline_candidate_id not in candidate_ids:
        raise ValueError("baseline candidate is missing from selection observations")

    baseline_rows = _selection_rows(
        contract,
        observations,
        contract.baseline_candidate_id,
        contract.base_cost_bps,
    )
    baseline_rank_ic = sum(float(row["rank_ic"]) for row in baseline_rows) / len(baseline_rows)

    evaluated: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        metrics = _candidate_metrics(
            contract,
            observations,
            candidate_id,
            candidate_metadata,
            baseline_rank_ic,
        )
        checks = _gate_checks(contract, metrics)
        evaluated.append(
            {
                **metrics,
                "gate_checks": checks,
                "gate_pass_count": sum(checks.values()),
                "supported": all(checks.values()),
            }
        )

    evaluated.sort(
        key=lambda row: tuple(_ranking_value(metric, row) for metric in contract.ranking),
        reverse=True,
    )
    winner = evaluated[0]
    reporting_seen = sorted(
        {
            str(row.get("window"))
            for row in observations
            if str(row.get("window")) in contract.reporting_windows
        }
    )
    return {
        "schema_version": "1.0",
        "experiment_id": contract.experiment_id,
        "provider_identity_sha256": contract.provider_identity_sha256,
        "cutoff": contract.cutoff,
        "selection_windows": list(contract.selection_windows),
        "reporting_windows": list(contract.reporting_windows),
        "reporting_windows_seen_but_not_used": reporting_seen,
        "ranking": list(contract.ranking),
        "candidates": evaluated,
        "winner": winner["candidate_id"],
        "decision": contract.decision if winner["supported"] else "not_supported",
        "supported": bool(winner["supported"]),
    }
