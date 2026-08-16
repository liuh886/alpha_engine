"""Issue #966 Phase-6 minimal US feature-set decision over exact Stage-B evidence.

The selector does not train a model. It consumes the frozen exact portfolio
receipt plus no-label redundancy diagnostics, applies the preregistered subset
gate, and chooses the smallest passing feature set. A separate certification
step must then reproduce that selected candidate and evaluate any allowed risk
control; reporting windows never enter this selection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec

SCHEMA_VERSION = "1.0"
RUNNER = "issue966_phase6_minimal_set_selector_v1"


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _candidate_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = receipt.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Stage-B receipt has no candidates")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("Stage-B candidate row must be a mapping")
        candidate_id = str(raw.get("candidate_id", ""))
        if not candidate_id or candidate_id in result:
            raise ValueError(f"invalid Stage-B candidate id: {candidate_id!r}")
        result[candidate_id] = raw
    return result


def _metadata_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = receipt.get("candidate_metadata")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Stage-B receipt has no candidate_metadata")
    result = {str(row["candidate_id"]): dict(row) for row in rows if isinstance(row, dict)}
    if len(result) != len(rows):
        raise ValueError("Stage-B candidate metadata contains invalid/duplicate identities")
    return result


def select_minimal_feature_set(
    spec_path: str | Path,
    stage_b_receipt_path: str | Path,
    redundancy_receipt_path: str | Path,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    stage_b = _load_json(stage_b_receipt_path)
    redundancy = _load_json(redundancy_receipt_path)
    if spec.experiment_id != "us_issue966_phase6_minimal_set_v1":
        raise ValueError("unexpected Phase-6 minimal-set experiment id")
    if stage_b.get("experiment_id") != spec.experiment_id:
        raise ValueError("Stage-B experiment id differs from Phase-6 spec")
    if redundancy.get("experiment_id") != spec.experiment_id:
        raise ValueError("redundancy experiment id differs from Phase-6 spec")
    if stage_b.get("status") != "completed" or stage_b.get("runner") != "exact_us_ranker_portfolio_v1":
        raise ValueError("Phase-6 selection requires completed exact US Stage-B evidence")
    if stage_b.get("provider_identity_sha256") != spec.contract.provider_identity_sha256:
        raise ValueError("Stage-B provider identity differs from Phase-6 contract")
    if redundancy.get("provider_identity_sha256") != spec.contract.provider_identity_sha256:
        raise ValueError("redundancy provider identity differs from Phase-6 contract")
    if tuple(stage_b.get("selection_windows") or ()) != tuple(spec.contract.selection_windows):
        raise ValueError("Stage-B selection windows drifted")
    if tuple(redundancy.get("selection_windows") or ()) != tuple(spec.contract.selection_windows):
        raise ValueError("redundancy selection windows drifted")

    policy = dict(spec.raw.get("phase6_selection_policy") or {})
    baseline_id = str(policy.get("baseline_candidate_id", ""))
    candidates = _candidate_map(stage_b)
    metadata = _metadata_map(stage_b)
    if baseline_id not in candidates or baseline_id not in metadata:
        raise ValueError("Phase-6 baseline candidate is missing from exact evidence")
    baseline = candidates[baseline_id]
    base20 = float(baseline["compounded_relative_excess"])
    base60 = float(baseline["stress_compounded_relative_excess"])
    base_dd = float(baseline["worst_drawdown"])
    max_dd_worsening = float(policy["maximum_drawdown_worsening_vs_baseline"])
    max_component_redundancy = float(policy["maximum_abs_component_rank_correlation_to_baseline"])

    candidate_added = redundancy.get("candidate_added_factor_ids")
    factor_redundancy = redundancy.get("factors")
    if not isinstance(candidate_added, dict) or not isinstance(factor_redundancy, dict):
        raise ValueError("redundancy receipt is missing factor mappings")

    decisions: dict[str, Any] = {}
    passing: list[dict[str, Any]] = []
    for candidate_id, row in candidates.items():
        if candidate_id == baseline_id:
            continue
        if candidate_id not in metadata:
            raise ValueError(f"candidate metadata missing: {candidate_id}")
        additions = [str(value) for value in candidate_added.get(candidate_id, [])]
        if not additions:
            raise ValueError(f"Phase-6 challenger has no incremental factors: {candidate_id}")
        component_corr: dict[str, float] = {}
        for factor_id in additions:
            raw = factor_redundancy.get(factor_id)
            if not isinstance(raw, dict):
                raise ValueError(f"redundancy evidence missing added factor: {factor_id}")
            component_corr[factor_id] = float(raw["max_abs_mean_daily_rank_correlation"])
        max_corr = max(component_corr.values())
        improvement20 = float(row["compounded_relative_excess"]) - base20
        improvement60 = float(row["stress_compounded_relative_excess"]) - base60
        dd_delta = float(row["worst_drawdown"]) - base_dd
        checks = {
            "beats_baseline_20bps": improvement20 > 0.0,
            "beats_baseline_60bps": improvement60 > 0.0,
            "all_development_windows_positive_excess": bool(
                row.get("all_development_windows_positive_excess")
            ),
            "drawdown_worsening_within_limit": dd_delta >= -max_dd_worsening,
            "component_redundancy_within_limit": max_corr <= max_component_redundancy,
        }
        factor_count = int(metadata[candidate_id]["factor_count"])
        decision = {
            "candidate_id": candidate_id,
            "factor_count": factor_count,
            "added_factor_ids": additions,
            "component_max_abs_rank_correlation_to_baseline": component_corr,
            "max_component_redundancy": max_corr,
            "checks": checks,
            "pass": all(checks.values()),
            "metrics": {
                "compounded_relative_excess_20bps": float(row["compounded_relative_excess"]),
                "improvement_vs_baseline_20bps": improvement20,
                "compounded_relative_excess_60bps": float(row["stress_compounded_relative_excess"]),
                "improvement_vs_baseline_60bps": improvement60,
                "worst_drawdown": float(row["worst_drawdown"]),
                "drawdown_delta_vs_baseline": dd_delta,
                "mean_rank_ic": float(row["mean_rank_ic"]),
            },
        }
        decisions[candidate_id] = decision
        if decision["pass"]:
            passing.append(decision)

    passing.sort(
        key=lambda row: (
            int(row["factor_count"]),
            -float(row["metrics"]["improvement_vs_baseline_20bps"]),
            -float(row["metrics"]["improvement_vs_baseline_60bps"]),
            str(row["candidate_id"]),
        )
    )
    selected = passing[0] if passing else None
    reporting = dict(spec.raw.get("reporting_boundary") or {})
    if reporting.get("reporting_windows_may_enter_selection") is not False:
        raise ValueError("Phase-6 reporting windows must be excluded from selection")

    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER,
        "experiment_id": spec.experiment_id,
        "status": "completed",
        "provider_identity_sha256": spec.contract.provider_identity_sha256,
        "selection_windows": list(spec.contract.selection_windows),
        "baseline": {
            "candidate_id": baseline_id,
            "factor_count": int(metadata[baseline_id]["factor_count"]),
            "compounded_relative_excess_20bps": base20,
            "compounded_relative_excess_60bps": base60,
            "worst_drawdown": base_dd,
            "mean_rank_ic": float(baseline["mean_rank_ic"]),
        },
        "candidate_decisions": decisions,
        "passing_candidate_ids": [str(row["candidate_id"]) for row in passing],
        "selected_candidate_id": None if selected is None else str(selected["candidate_id"]),
        "selected_factor_count": None if selected is None else int(selected["factor_count"]),
        "selected_added_factor_ids": None if selected is None else list(selected["added_factor_ids"]),
        "selection_rule": list(policy.get("selection_order") or []),
        "reporting_boundary": reporting,
        "fresh_untouched_us_holdout_available": bool(
            reporting.get("fresh_untouched_us_holdout_available")
        ),
        "next": (
            "run_selected_candidate_reproduction_and_single_skew_control_certification"
            if selected is not None
            else "preserve_us_x1_2_no_phase6_feature_candidate"
        ),
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }


def write_minimal_feature_set_decision(
    decision: dict[str, Any],
    path: str | Path,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
