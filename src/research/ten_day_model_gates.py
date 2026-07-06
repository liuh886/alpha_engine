"""Ten-day model promotion gate helpers."""

from __future__ import annotations

from typing import Any

GATE_THRESHOLDS: dict[str, float] = {
    "min_icir": 0.30,
    "min_rank_ic": 0.02,
    "min_positive_ic_ratio": 0.55,
    "min_spread": 0.0,
    "min_sharpe": 0.0,
    "max_drawdown_floor": -0.15,
}


def evaluate_model_gates(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return pass/fail gate details for one fixed-ten-day candidate payload."""

    direction = candidate.get("score_direction", {}) or {}
    checks = {
        "icir": float(candidate.get("icir", 0.0)) >= GATE_THRESHOLDS["min_icir"],
        "rank_ic": float(candidate.get("rank_ic", 0.0)) >= GATE_THRESHOLDS["min_rank_ic"],
        "positive_ic_ratio": float(candidate.get("positive_ic_ratio", 0.0))
        >= GATE_THRESHOLDS["min_positive_ic_ratio"],
        "spread": float(direction.get("top_minus_bottom_spread", 0.0))
        > GATE_THRESHOLDS["min_spread"],
        "sharpe": float(candidate.get("sharpe", 0.0)) > GATE_THRESHOLDS["min_sharpe"],
        "drawdown": float(candidate.get("max_drawdown", 0.0))
        >= GATE_THRESHOLDS["max_drawdown_floor"],
        "direction": direction.get("recommendation") == "keep_score",
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "ready_for_trade_guidance": not failed,
        "failed_gates": failed,
        "checks": checks,
        "thresholds": dict(GATE_THRESHOLDS),
    }


def summarize_report_gates(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize gate readiness for every candidate in a comparison report."""

    rows = []
    for candidate in report.get("candidates", []):
        gate = evaluate_model_gates(candidate)
        rows.append(
            {
                "candidate": f"{candidate.get('candidate_kind')}/{candidate.get('orientation')}",
                "ready_for_trade_guidance": gate["ready_for_trade_guidance"],
                "failed_gates": gate["failed_gates"],
            }
        )
    return {
        "n_candidates": len(rows),
        "n_ready": sum(1 for row in rows if row["ready_for_trade_guidance"]),
        "candidates": rows,
    }
