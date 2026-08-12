"""Final untouched-holdout certification for the supported CN x1.2 challenger.

The exact trainer and economic evaluator remain owned by
``cn_ranker_exact_portfolio_replay``.  This module owns only the lifecycle
boundary that 2026H1 is a one-shot certification window and the promotion
checks preregistered in Issue #896.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.research import cn_ranker_exact_portfolio_replay as exact_replay
from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec

CERTIFICATION_ID = "cn_x1_2_2026h1_certification_v1"
CERTIFICATION_WINDOWS = ("2026H1",)
TARGET_CHALLENGER = "cn_x1_2_alpha158_three_mechanism"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _candidate(receipt: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    rows = receipt.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("exact replay receipt has no candidate rows")
    matches = [
        dict(row)
        for row in rows
        if isinstance(row, dict) and str(row.get("candidate_id")) == candidate_id
    ]
    if len(matches) != 1:
        raise ValueError(f"exact replay candidate identity is ambiguous: {candidate_id}")
    return matches[0]


def run_cn_x1_2_certification(
    spec_path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Consume 2026H1 exactly once and return the preregistered promotion verdict."""

    spec = load_cross_sectional_experiment_spec(spec_path)
    certification = spec.raw.get("certification")
    if not isinstance(certification, dict):
        raise ValueError("CN x1.2 certification block is required")
    if str(certification.get("evidence_role")) != "untouched_holdout":
        raise ValueError("CN x1.2 certification must be untouched_holdout evidence")
    if str(certification.get("window")) != "2026H1":
        raise ValueError("CN x1.2 certification window must be 2026H1")
    if certification.get("new_holdout_consumed") is not True:
        raise ValueError("CN x1.2 certification must explicitly consume the holdout")
    if tuple(spec.contract.selection_windows) != CERTIFICATION_WINDOWS:
        raise ValueError("CN x1.2 certification must select only 2026H1")
    if spec.contract.reporting_windows:
        raise ValueError("CN x1.2 certification may not consume reporting windows")
    if str(spec.parent.walk_forward.get("test_end")) != "2026-06-30":
        raise ValueError("CN x1.2 certification parent must stop at 2026-06-30")

    baseline_id = spec.contract.baseline_candidate_id
    challenger_ids = [
        candidate.candidate_id
        for candidate in spec.candidates
        if candidate.candidate_id != baseline_id
    ]
    if challenger_ids != [TARGET_CHALLENGER]:
        raise ValueError(
            "CN x1.2 certification requires exactly the frozen three-mechanism challenger"
        )

    output = Path(output_dir).resolve()
    original_windows = exact_replay.SELECTION_WINDOWS
    try:
        exact_replay.SELECTION_WINDOWS = CERTIFICATION_WINDOWS
        exact = exact_replay.run_exact_cn_ranker_portfolio_replay(
            spec_path,
            output_dir=output / "exact_replay",
        )
    finally:
        exact_replay.SELECTION_WINDOWS = original_windows

    if exact.get("status") != "completed":
        blocked = {
            "schema_version": "1.0",
            "certification_id": CERTIFICATION_ID,
            "experiment_id": spec.experiment_id,
            "status": str(exact.get("status") or "blocked"),
            "decision": "cn_x1_2_certification_blocked",
            "exact_replay": exact,
            "new_holdout_consumed": True,
            "research_only": True,
            "trade_ready": False,
        }
        _write_json(output / "certification_receipt.json", blocked)
        return blocked

    baseline = _candidate(exact, baseline_id)
    challenger = _candidate(exact, TARGET_CHALLENGER)
    base20 = dict(baseline["base_20bps"])
    base60 = dict(baseline["stress_60bps"])
    chal20 = dict(challenger["base_20bps"])
    chal60 = dict(challenger["stress_60bps"])
    boundary = dict(spec.raw.get("support_boundary") or {})

    improvement20 = float(chal20["relative_excess"]) - float(base20["relative_excess"])
    improvement60 = float(chal60["relative_excess"]) - float(base60["relative_excess"])
    drawdown_delta = float(chal20["max_drawdown"]) - float(base20["max_drawdown"])
    positive_windows = int(chal20["positive_excess_windows"])
    mean_rank_ic = float(challenger["mean_rank_ic"])
    exact_checks = dict((exact.get("support_boundary") or {}).get("checks") or {})

    risk_off_cost_gate = bool(
        float(chal20["risk_off_relative_excess"])
        >= -float(chal20["risk_off_total_cost"]) - 0.001
    )
    checks = {
        "beats_incumbent_20bps": improvement20 > 0.0,
        "beats_incumbent_60bps": improvement60 > 0.0,
        "relative_excess_positive_20bps": float(chal20["relative_excess"]) > 0.0,
        "relative_excess_positive_60bps": float(chal60["relative_excess"]) > 0.0,
        "certification_window_positive": positive_windows
        >= int(boundary["minimum_positive_selection_windows"]),
        "max_drawdown_above_floor": float(chal20["max_drawdown"])
        >= float(boundary["minimum_max_drawdown"]),
        "drawdown_worsening_within_limit": drawdown_delta
        >= -float(boundary["maximum_drawdown_worsening_vs_incumbent"]),
        "risk_on_relative_excess_positive": float(chal20["risk_on_relative_excess"]) > 0.0,
        "risk_off_relative_no_worse_than_cost_drag": risk_off_cost_gate,
        "mean_rank_ic_non_negative": mean_rank_ic >= float(boundary["minimum_mean_rank_ic"]),
        "exact_score_reproduction": bool(exact_checks.get("exact_score_reproduction")),
        "exact_portfolio_reproduction": bool(exact_checks.get("exact_portfolio_reproduction")),
    }
    supported = all(checks.values())

    receipt = {
        "schema_version": "1.0",
        "certification_id": CERTIFICATION_ID,
        "experiment_id": spec.experiment_id,
        "status": "completed",
        "decision": (
            "cn_x1_2_certification_supported"
            if supported
            else "cn_x1_2_certification_rejected"
        ),
        "selection_windows": list(CERTIFICATION_WINDOWS),
        "provider_identity_sha256": exact.get("observed_provider_identity_sha256"),
        "baseline": {
            "candidate_id": baseline_id,
            "relative_excess_20bps": float(base20["relative_excess"]),
            "relative_excess_60bps": float(base60["relative_excess"]),
            "max_drawdown_20bps": float(base20["max_drawdown"]),
            "mean_rank_ic": float(baseline["mean_rank_ic"]),
        },
        "challenger": {
            "candidate_id": TARGET_CHALLENGER,
            "factor_ids": list(challenger["factor_ids"]),
            "factor_implementation_hashes": dict(challenger["factor_implementation_hashes"]),
            "relative_excess_20bps": float(chal20["relative_excess"]),
            "relative_excess_60bps": float(chal60["relative_excess"]),
            "max_drawdown_20bps": float(chal20["max_drawdown"]),
            "mean_rank_ic": mean_rank_ic,
            "risk_on_relative_excess_20bps": float(chal20["risk_on_relative_excess"]),
            "risk_off_relative_excess_20bps": float(chal20["risk_off_relative_excess"]),
            "turnover_20bps": float(chal20["turnover"]),
        },
        "improvement_vs_incumbent_20bps": improvement20,
        "improvement_vs_incumbent_60bps": improvement60,
        "worst_drawdown_delta_vs_incumbent": drawdown_delta,
        "mean_rank_ic_improvement_vs_incumbent": mean_rank_ic - float(baseline["mean_rank_ic"]),
        "checks": checks,
        "certification_supported": supported,
        "score_reproduction": exact.get("score_reproduction"),
        "portfolio_reproduction": exact.get("portfolio_reproduction"),
        "new_holdout_consumed": True,
        "automatic_trade_readiness": False,
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output / "certification_receipt.json", receipt)
    return receipt
