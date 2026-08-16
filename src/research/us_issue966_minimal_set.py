"""Issue #966 Phase-6 minimal US feature-set decision over exact Stage-B evidence.

The selector does not train a model. It consumes the frozen exact portfolio
receipt, its exact per-window observations, and no-label redundancy diagnostics,
then chooses the smallest passing subset. Reporting windows never enter this
selection. A separate certification step must reproduce the selected candidate
and evaluate the already-approved skew risk control exactly once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec

SCHEMA_VERSION = "1.0"
RUNNER = "issue966_phase6_minimal_set_selector_v1"
BASE_COST_BPS = 20
STRESS_COST_BPS = 60


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_observations(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Stage-B observations must be a non-empty JSON list")
    rows: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("Stage-B observation row must be a mapping")
        rows.append(dict(raw))
    return rows


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
    raw = receipt.get("candidate_metadata")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Stage-B receipt has no candidate_metadata mapping")
    result: dict[str, dict[str, Any]] = {}
    for candidate_id, metadata in raw.items():
        if not isinstance(metadata, dict):
            raise ValueError(f"candidate metadata must be a mapping: {candidate_id}")
        result[str(candidate_id)] = dict(metadata)
    return result


def _exact_window_relative_excess(
    observations: list[dict[str, Any]],
    *,
    candidate_id: str,
    selection_windows: tuple[str, ...],
    cost_bps: int,
) -> dict[str, float]:
    by_window: dict[str, float] = {}
    for row in observations:
        if str(row.get("candidate_id")) != candidate_id:
            continue
        if int(row.get("cost_bps", -1)) != cost_bps:
            continue
        window = str(row.get("window", ""))
        if window not in selection_windows:
            continue
        if window in by_window:
            raise ValueError(
                f"duplicate Stage-B observation for {candidate_id}/{window}/{cost_bps}bps"
            )
        by_window[window] = float(row["relative_excess"])
    missing = [window for window in selection_windows if window not in by_window]
    if missing:
        raise ValueError(
            f"candidate {candidate_id} missing exact {cost_bps}bps observations: {missing}"
        )
    return {window: by_window[window] for window in selection_windows}


def select_minimal_feature_set(
    spec_path: str | Path,
    stage_b_receipt_path: str | Path,
    observations_path: str | Path,
    redundancy_receipt_path: str | Path,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    stage_b = _load_json(stage_b_receipt_path)
    observations = _load_observations(observations_path)
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
    observed_provider = stage_b.get("observed_provider_identity_sha256")
    if observed_provider != spec.contract.provider_identity_sha256:
        raise ValueError("Stage-B observed provider identity differs from Phase-6 contract")
    if redundancy.get("provider_identity_sha256") != spec.contract.provider_identity_sha256:
        raise ValueError("redundancy provider identity differs from Phase-6 contract")
    selection_windows = tuple(spec.contract.selection_windows)
    if tuple(stage_b.get("selection_windows") or ()) != selection_windows:
        raise ValueError("Stage-B selection windows drifted")
    if tuple(redundancy.get("selection_windows") or ()) != selection_windows:
        raise ValueError("redundancy selection windows drifted")
    observed_windows = {
        str(row.get("window"))
        for row in observations
        if str(row.get("window")) in selection_windows
    }
    if observed_windows != set(selection_windows):
        raise ValueError("Stage-B observations do not exactly cover Phase-6 selection windows")

    policy = dict(spec.raw.get("phase6_selection_policy") or {})
    baseline_id = str(policy.get("baseline_candidate_id", ""))
    candidates = _candidate_map(stage_b)
    metadata = _metadata_map(stage_b)
    if baseline_id not in candidates or baseline_id not in metadata:
        raise ValueError("Phase-6 baseline candidate is missing from exact evidence")
    if set(candidates) != set(metadata):
        raise ValueError("Stage-B candidate and metadata identities differ")
    baseline = candidates[baseline_id]
    base20 = float(baseline["compounded_relative_excess"])
    base60 = float(baseline["stress_compounded_relative_excess"])
    base_dd = float(baseline["worst_drawdown"])
    max_dd_worsening = float(policy["maximum_drawdown_worsening_vs_baseline"])
    max_component_redundancy = float(
        policy["maximum_abs_component_rank_correlation_to_baseline"]
    )

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
        exact20 = _exact_window_relative_excess(
            observations,
            candidate_id=candidate_id,
            selection_windows=selection_windows,
            cost_bps=BASE_COST_BPS,
        )
        exact60 = _exact_window_relative_excess(
            observations,
            candidate_id=candidate_id,
            selection_windows=selection_windows,
            cost_bps=STRESS_COST_BPS,
        )
        checks = {
            "beats_baseline_20bps": improvement20 > 0.0,
            "beats_baseline_60bps": improvement60 > 0.0,
            "all_development_windows_positive_excess": all(
                value > 0.0 for value in exact20.values()
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
            "exact_window_relative_excess_20bps": exact20,
            "exact_window_relative_excess_60bps": exact60,
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
    if reporting.get("fresh_untouched_us_holdout_available") is not False:
        raise ValueError("Phase-6 contract must truthfully declare no fresh untouched US holdout")

    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER,
        "experiment_id": spec.experiment_id,
        "status": "completed",
        "provider_identity_sha256": spec.contract.provider_identity_sha256,
        "selection_windows": list(selection_windows),
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
        "fresh_untouched_us_holdout_available": False,
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
