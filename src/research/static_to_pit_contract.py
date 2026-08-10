"""Frozen contracts and endpoint gates for static-to-PIT diagnosis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from src.research.paradigm import ResearchParadigmSpec


CELL_ORDER: tuple[str, ...] = ("S/S", "S/P", "P/S", "P/P")
REFERENCE_ENDPOINTS: dict[str, dict[str, dict[str, float]]] = {
    "S/S": {
        "lgbm:": {
            "mean_icir": 0.3587,
            "compounded_relative_excess_return": 0.6504,
            "worst_drawdown": -0.2734,
        },
        "xgb:": {
            "mean_icir": 0.3497,
            "compounded_relative_excess_return": 0.7035,
            "worst_drawdown": -0.2563,
        },
    },
    "P/P": {
        "lgbm:": {
            "mean_icir": 0.0966,
            "compounded_relative_excess_return": -0.2049,
            "worst_drawdown": -0.2611,
        },
        "xgb:": {
            "mean_icir": 0.1149,
            "compounded_relative_excess_return": -0.3408,
            "worst_drawdown": -0.2559,
        },
    },
}


@dataclass(frozen=True)
class DecompositionCell:
    """One frozen training/OOS membership combination."""

    cell_id: str
    training_membership: str
    oos_membership: str

    def to_dict(self) -> dict[str, str]:
        return {
            "cell_id": self.cell_id,
            "training_membership": self.training_membership,
            "oos_membership": self.oos_membership,
        }


def build_four_cell_matrix() -> tuple[DecompositionCell, ...]:
    """Return the predeclared S/S, S/P, P/S, P/P matrix."""

    return (
        DecompositionCell("S/S", "static_curated", "static_curated"),
        DecompositionCell("S/P", "static_curated", "window_start_point_in_time"),
        DecompositionCell("P/S", "window_start_point_in_time", "static_curated"),
        DecompositionCell(
            "P/P",
            "window_start_point_in_time",
            "window_start_point_in_time",
        ),
    )


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible diagnostic contract deterministically."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_frozen_spec_pair(
    static_spec: ResearchParadigmSpec,
    pit_spec: ResearchParadigmSpec,
) -> dict[str, Any]:
    """Fail closed unless both specs differ only by universe membership."""

    if static_spec.market != "us" or pit_spec.market != "us":
        raise ValueError("static-to-PIT decomposition requires two US specs")

    shared_fields = {
        "benchmark": (static_spec.benchmark, pit_spec.benchmark),
        "factor_library": (static_spec.factor_library, pit_spec.factor_library),
        "candidate_grid": (static_spec.candidate_grid, pit_spec.candidate_grid),
        "strategy": (static_spec.strategy, pit_spec.strategy),
        "evaluation": (static_spec.evaluation, pit_spec.evaluation),
        "outputs": (static_spec.outputs, pit_spec.outputs),
    }
    mismatches = [name for name, (left, right) in shared_fields.items() if left != right]

    static_walk = dict(static_spec.walk_forward)
    pit_walk = dict(pit_spec.walk_forward)
    for payload in (static_walk, pit_walk):
        payload["last_test_year"] = 2025
    if static_walk != pit_walk:
        mismatches.append("walk_forward")

    if static_spec.universe.get("membership_mode") != "static_curated":
        mismatches.append("static_membership_mode")
    if pit_spec.universe.get("membership_mode") != "window_start_point_in_time":
        mismatches.append("pit_membership_mode")
    if mismatches:
        raise ValueError(
            "Frozen static/PIT specs differ outside the permitted universe "
            f"contract: {sorted(mismatches)}"
        )

    contract = {
        "schema_version": "1.0",
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "observed_windows": ["2024H1", "2024H2", "2025H1", "2025H2"],
        "static_experiment_id": static_spec.experiment_id,
        "pit_experiment_id": pit_spec.experiment_id,
        "benchmark": static_spec.benchmark,
        "factor_library": dict(static_spec.factor_library),
        "candidate_grid": dict(static_spec.candidate_grid),
        "strategy": dict(static_spec.strategy),
        "walk_forward": static_walk,
        "cells": [cell.to_dict() for cell in build_four_cell_matrix()],
        "stop_rules": {
            "parameter_search": False,
            "factor_window_search": False,
            "orientation_search": False,
            "topk_search": False,
            "blend_search": False,
            "cost_search": False,
            "universe_search": False,
        },
    }
    return {**contract, "contract_sha256": canonical_sha256(contract)}


def validate_endpoint_reproduction(
    stability_by_cell: Mapping[str, Mapping[str, Any]],
    *,
    tolerance: float = 0.0015,
) -> dict[str, Any]:
    """Verify the matrix reproduces committed S/S and P/P metrics."""

    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    checks: list[dict[str, Any]] = []
    for cell_id, references in REFERENCE_ENDPOINTS.items():
        rows = list(stability_by_cell.get(cell_id, {}).get("candidates", []))
        for prefix, expected_metrics in references.items():
            matches = [
                row
                for row in rows
                if str(row.get("candidate", "")).startswith(prefix)
                and str(row.get("candidate", "")).endswith("/original")
            ]
            if len(matches) != 1:
                checks.append(
                    {
                        "cell_id": cell_id,
                        "candidate_prefix": prefix,
                        "passed": False,
                        "reason": (
                            f"expected exactly one original candidate, found {len(matches)}"
                        ),
                    }
                )
                continue
            row = matches[0]
            metric_checks = []
            for metric, expected in expected_metrics.items():
                actual = float(row.get(metric, float("nan")))
                delta = actual - expected
                metric_checks.append(
                    {
                        "metric": metric,
                        "expected": expected,
                        "actual": actual,
                        "delta": delta,
                        "tolerance": tolerance,
                        "passed": bool(np.isfinite(actual) and abs(delta) <= tolerance),
                    }
                )
            checks.append(
                {
                    "cell_id": cell_id,
                    "candidate_prefix": prefix,
                    "candidate": row.get("candidate"),
                    "passed": all(item["passed"] for item in metric_checks),
                    "metrics": metric_checks,
                }
            )
    return {
        "passed": bool(checks) and all(item["passed"] for item in checks),
        "reference_source": (
            "docs/research/lgbm_xgb_ranker_comparison_2026-07-29.md and "
            "docs/research/lgbm_xgb_ranker_pit_robustness_2026-07-29.md"
        ),
        "checks": checks,
    }


def final_stop_decision() -> dict[str, Any]:
    """Return the post-diagnosis decision for the observed OHLCV family."""

    return {
        "decision": "stop_existing_ohlcv_ranker_family",
        "promotion_eligible": False,
        "stable_research_candidate": False,
        "trade_ready": False,
        "rationale": (
            "The authoritative P/P evidence rejects the existing OHLCV ranker "
            "family. Mixed cells are explanatory counterfactuals on already "
            "observed windows and cannot justify promotion or additional tuning. "
            "Any future challenge must introduce a genuinely new economic "
            "information set and untouched evidence."
        ),
    }
