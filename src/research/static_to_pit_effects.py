"""Metric extraction and additive four-cell attribution."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np


CELL_ORDER: tuple[str, ...] = ("S/S", "S/P", "P/S", "P/P")
DECOMPOSITION_METRICS: tuple[str, ...] = (
    "ic",
    "rank_ic",
    "icir",
    "positive_ic_ratio",
    "top_minus_bottom_spread",
    "total_return",
    "benchmark_return",
    "excess_return",
    "sharpe",
    "max_drawdown",
    "turnover",
    "costs",
)


def extract_original_candidate_metrics(
    report: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    """Extract original-orientation metrics from one window report."""

    comparison = report.get("comparison_report", {})
    result: dict[str, dict[str, float]] = {}
    for raw in comparison.get("candidates", []):
        if raw.get("orientation") != "original":
            continue
        name = str(raw.get("candidate_name", ""))
        if not name:
            continue
        direction = raw.get("score_direction", {})
        values: dict[str, float] = {}
        for metric in DECOMPOSITION_METRICS:
            value = (
                direction.get(metric) if metric == "top_minus_bottom_spread" else raw.get(metric)
            )
            if value is not None:
                values[metric] = float(value)
        result[name] = values
    return result


def four_cell_effects(
    cell_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    """Decompose P/P minus S/S into OOS, training and interaction effects."""

    missing = sorted(set(CELL_ORDER) - set(cell_metrics))
    if missing:
        raise ValueError(f"four-cell metrics missing cells: {missing}")

    candidates = set(cell_metrics["S/S"])
    for cell in CELL_ORDER[1:]:
        candidates &= set(cell_metrics[cell])

    result: dict[str, Any] = {}
    for candidate in sorted(candidates):
        metrics = set(cell_metrics["S/S"][candidate])
        for cell in CELL_ORDER[1:]:
            metrics &= set(cell_metrics[cell][candidate])
        candidate_result: dict[str, Any] = {}
        for metric in sorted(metrics):
            ss = float(cell_metrics["S/S"][candidate][metric])
            sp = float(cell_metrics["S/P"][candidate][metric])
            ps = float(cell_metrics["P/S"][candidate][metric])
            pp = float(cell_metrics["P/P"][candidate][metric])
            oos_effect = sp - ss
            training_effect = ps - ss
            interaction = pp - sp - ps + ss
            total = pp - ss
            candidate_result[metric] = {
                "S/S": ss,
                "S/P": sp,
                "P/S": ps,
                "P/P": pp,
                "oos_opportunity_set_effect": oos_effect,
                "training_and_label_effect": training_effect,
                "interaction_residual": interaction,
                "total_static_to_pit_gap": total,
                "reconciled": bool(
                    np.isclose(
                        oos_effect + training_effect + interaction,
                        total,
                        rtol=1e-10,
                        atol=1e-12,
                    )
                ),
            }
        result[candidate] = candidate_result
    return result
