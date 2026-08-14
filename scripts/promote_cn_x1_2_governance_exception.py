#!/usr/bin/env python3
"""Materialize the user-directed CN x1.2 research-baseline promotion receipt.

The source experiment is intentionally a rejected preregistered result.  This
script fails closed unless that rejection, its sole failed gate, and the
research-only boundary remain intact.  Promotion is therefore recorded as a
governance exception, never as a retroactive gate pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


MODEL_ID = "cn_x1_2"
CANDIDATE_ID = "cn_x1_2_alpha158_breadth_scaled"
EXPERIMENT_ID = "cn_x1_2_alpha158_breadth_scaled_v1"
FAILED_GATE = "2026h1_drawdown_worsening_within_3pp"
AUTHORITY_ISSUE = 954
AUTHORITY_COMMENT = "https://github.com/liuh886/alpha_engine/issues/954#issuecomment-5293367579"
PORTFOLIO_EVIDENCE = Path(
    "data/research/cn_x1_2_alpha158_breadth_scaled_v1/"
    "challenger_portfolio_evidence.json"
)


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_object(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_promotion_receipt(
    source: Path, portfolio_evidence: Path = PORTFOLIO_EVIDENCE
) -> dict[str, Any]:
    raw = _load_object(source)
    rows = _load_object(portfolio_evidence)
    if raw.get("experiment_id") != EXPERIMENT_ID or raw.get("status") != "completed_rejected":
        raise ValueError("CN x1.2 source experiment identity/status drifted")
    if raw.get("decision") != "cn_x1_2_alpha158_breadth_scaled_development_rejected":
        raise ValueError("CN x1.2 source decision must remain rejected")
    if raw.get("research_only") is not True or raw.get("trade_ready") is not False:
        raise ValueError("CN x1.2 research boundary drifted")
    if raw.get("automatic_promotion") is not False:
        raise ValueError("CN x1.2 source must prohibit automatic promotion")
    if raw.get("no_2026h2_evidence_consumed") is not True:
        raise ValueError("CN x1.2 promotion cannot consume 2026H2 evidence")
    if raw.get("reserved_holdout_start") != "2026-07-01":
        raise ValueError("CN x1.2 reserved holdout boundary drifted")

    boundary = raw.get("development_boundary")
    if not isinstance(boundary, dict) or boundary.get("supported") is not False:
        raise ValueError("CN x1.2 failed development boundary must remain unsupported")
    checks = boundary.get("checks")
    if not isinstance(checks, dict) or len(checks) != 22:
        raise ValueError("CN x1.2 must retain all 22 preregistered checks")
    failed = sorted(key for key, value in checks.items() if value is not True)
    if failed != [FAILED_GATE]:
        raise ValueError(f"CN x1.2 failed-gate identity drifted: {failed}")
    metrics = boundary.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("CN x1.2 development metrics are missing")
    observed_delta = float(metrics.get("worst_2026h1_drawdown_delta_vs_incumbent", 0.0))
    if abs(observed_delta - (-0.04798990466643405)) > 1e-12:
        raise ValueError("CN x1.2 2026H1 drawdown exception magnitude drifted")

    selected = raw.get("selected_candidate")
    incumbent = raw.get("incumbent")
    if not isinstance(selected, dict) or not isinstance(incumbent, dict):
        raise ValueError("CN x1.2 selected/incumbent evidence is missing")
    if selected.get("factor_count") != 17 or selected.get("exposure_policy") != "breadth_scaled":
        raise ValueError("CN x1.2 selected candidate identity drifted")
    if (
        rows.get("record_type") != "cn_x1_2_challenger_portfolio_evidence"
        or rows.get("experiment_id") != EXPERIMENT_ID
        or rows.get("candidate_id") != CANDIDATE_ID
        or rows.get("no_2026h2_evidence_consumed") is not True
        or rows.get("research_only") is not True
        or rows.get("trade_ready") is not False
    ):
        raise ValueError("CN x1.2 row-level portfolio evidence boundary drifted")

    promotion_receipt = {
        "schema_version": "cn_x1_2_user_directed_promotion_v1",
        "model_id": MODEL_ID,
        "selected_candidate": CANDIDATE_ID,
        "decision": "promoted_by_explicit_user_governance_exception",
        "promotion_date": "2026-08-14",
        "promotion_authority": {
            "kind": "explicit_user_direction",
            "issue": AUTHORITY_ISSUE,
            "audit_comment": AUTHORITY_COMMENT,
        },
        "source_experiment": {
            "experiment_id": EXPERIMENT_ID,
            "receipt": "data/research/experiment_receipts/cn_x1_2_alpha158_breadth_scaled_v1.json",
            "receipt_sha256": _sha256(source),
            "source_run_identity_sha256": raw.get("source_run_identity_sha256"),
            "original_decision": raw["decision"],
        },
        "portfolio_evidence": {
            "path": portfolio_evidence.as_posix(),
            "sha256": _sha256(portfolio_evidence),
            "cost_paths_bps": [20, 60],
            "performance_trace": "retained_exact_non_overlapping_10_session_trace",
            "holdings": "retained_exact_all_rebalance_targets_including_CSI300_sleeve",
        },
        "preregistered_gate_result": {
            "passed": 21,
            "total": 22,
            "supported": False,
            "failed_gates": [FAILED_GATE],
            "incumbent_2026h1_max_drawdown": -0.07926435673670995,
            "candidate_2026h1_max_drawdown": -0.127254261403144,
            "drawdown_delta_percentage_points": -4.798990466643405,
            "maximum_allowed_worsening_percentage_points": 3.0,
        },
        "positive_evidence": {
            "relative_excess_20bps": float(selected["base_20bps"]["relative_excess"]),
            "incumbent_relative_excess_20bps": float(incumbent["base_20bps"]["relative_excess"]),
            "relative_excess_60bps": float(selected["stress_60bps"]["relative_excess"]),
            "incumbent_relative_excess_60bps": float(incumbent["stress_60bps"]["relative_excess"]),
            "aggregate_max_drawdown_20bps": float(selected["base_20bps"]["max_drawdown"]),
            "incumbent_aggregate_max_drawdown_20bps": float(
                incumbent["base_20bps"]["max_drawdown"]
            ),
            "positive_windows": int(selected["base_20bps"]["positive_excess_windows"]),
            "mean_rank_ic": float(selected["mean_rank_ic"]),
            "exact_score_reproduction": True,
            "exact_portfolio_reproduction": True,
        },
        "governance_interpretation": {
            "automatic_promotion": False,
            "formal_acceptance_supported_by_preregistered_gates": False,
            "research_baseline_promotion_authorized": True,
            "failed_evidence_retained": True,
            "formal_bundle_transition": "materialized_complete_bundle_v2",
            "current_target_activation": "blocked_pending_maintained_cn_x1_2_inference_adapter",
        },
        "no_2026h2_evidence_consumed": True,
        "research_only": True,
        "trade_ready": False,
    }
    return promotion_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portfolio-evidence",
        type=Path,
        default=PORTFOLIO_EVIDENCE,
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/research/experiment_receipts/cn_x1_2_alpha158_breadth_scaled_v1.json"),
    )
    parser.add_argument(
        "--promotion-output",
        type=Path,
        default=Path("data/research/experiment_receipts/cn_x1_2_user_directed_promotion_v1.json"),
    )
    args = parser.parse_args()
    promotion = build_promotion_receipt(args.source, args.portfolio_evidence)
    _write_object(args.promotion_output, promotion)
    print(json.dumps({"promotion": str(args.promotion_output)}))


if __name__ == "__main__":
    main()
