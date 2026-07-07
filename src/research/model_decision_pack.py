"""Model decision-pack helpers for fixed-10D research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.research.ten_day_model_gates import GATE_THRESHOLDS


@dataclass(frozen=True)
class DecisionThresholds:
    """Decision thresholds for research and trade-guidance status."""

    trade_icir: float = GATE_THRESHOLDS["min_icir"]
    max_drawdown_floor: float = GATE_THRESHOLDS["max_drawdown_floor"]
    min_ready_ratio: float = 0.75
    stronger_research_icir: float = 0.20

    def to_dict(self) -> dict[str, float]:
        return {
            "trade_icir": self.trade_icir,
            "max_drawdown_floor": self.max_drawdown_floor,
            "min_ready_ratio": self.min_ready_ratio,
            "stronger_research_icir": self.stronger_research_icir,
        }


def _candidate_rows(stability_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = stability_summary.get("candidates", [])
    if not isinstance(rows, list):
        raise ValueError("stability_summary['candidates'] must be a list")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("stability_summary candidates must be objects")
    return [dict(row) for row in rows]


def _validate_stability_summary(stability_summary: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    if stability_summary.get("schema_version") != "1.0":
        raise ValueError("stability_summary schema_version must be '1.0'")
    min_windows = int(stability_summary.get("min_windows", 0))
    n_reports = int(stability_summary.get("n_reports", 0))
    if min_windows < 3:
        raise ValueError("stability_summary min_windows must be at least 3")
    if n_reports < min_windows:
        raise ValueError("stability_summary must contain at least min_windows reports")
    inconsistent = [
        row.get("candidate", "unknown")
        for row in rows
        if bool(row.get("stable_research_candidate")) and int(row.get("n_windows", 0)) < min_windows
    ]
    if inconsistent:
        raise ValueError(f"stable candidates have insufficient windows: {inconsistent}")
    return min_windows


def _select_best_research_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    stable = [row for row in rows if bool(row.get("stable_research_candidate"))]
    if not stable:
        return None
    return max(
        stable,
        key=lambda row: (
            float(row.get("mean_icir", 0.0)),
            float(row.get("ready_ratio", 0.0)),
            float(row.get("positive_icir_ratio", 0.0)),
            float(row.get("worst_drawdown", 0.0)),
        ),
    )


def evaluate_decision_status(
    candidate: dict[str, Any] | None,
    *,
    thresholds: DecisionThresholds | None = None,
) -> dict[str, Any]:
    """Classify the best candidate without overstating trade readiness."""

    limits = thresholds or DecisionThresholds()
    if candidate is None:
        return {
            "status": "no_stable_candidate",
            "trade_ready": False,
            "failed_trade_gates": ["stable_research_candidate"],
            "thresholds": limits.to_dict(),
        }

    mean_icir = float(candidate.get("mean_icir", 0.0))
    worst_drawdown = float(candidate.get("worst_drawdown", 0.0))
    ready_ratio = float(candidate.get("ready_ratio", 0.0))
    failed = []
    if mean_icir < limits.trade_icir:
        failed.append("mean_icir")
    if worst_drawdown < limits.max_drawdown_floor:
        failed.append("worst_drawdown")
    if ready_ratio < limits.min_ready_ratio:
        failed.append("ready_ratio")

    if not failed:
        status = "trade_guidance_candidate"
    elif mean_icir >= limits.stronger_research_icir and worst_drawdown >= limits.max_drawdown_floor:
        status = "stronger_research_candidate"
    else:
        status = "research_candidate"
    return {
        "status": status,
        "trade_ready": not failed,
        "failed_trade_gates": failed,
        "thresholds": limits.to_dict(),
    }


def build_model_decision_pack(
    stability_summary: dict[str, Any],
    *,
    thresholds: DecisionThresholds | None = None,
) -> dict[str, Any]:
    """Build a model decision pack from a walk-forward stability summary."""

    rows = _candidate_rows(stability_summary)
    _validate_stability_summary(stability_summary, rows)
    best = _select_best_research_candidate(rows)
    decision = evaluate_decision_status(best, thresholds=thresholds)
    stable = [row for row in rows if bool(row.get("stable_research_candidate"))]
    stable.sort(
        key=lambda row: (
            float(row.get("mean_icir", 0.0)),
            float(row.get("ready_ratio", 0.0)),
            float(row.get("worst_drawdown", 0.0)),
        ),
        reverse=True,
    )
    return {
        "schema_version": "1.0",
        "source_n_reports": stability_summary.get("n_reports"),
        "source_n_candidates": stability_summary.get("n_candidates"),
        "current_best_candidate": best,
        "decision": decision,
        "stable_candidate_count": len(stable),
        "stable_candidates_top5": stable[:5],
        "non_trade_ready_warning": (
            "Research evidence is not authorization for live trading or automated execution. "
            "Trade-guidance status requires all decision gates to pass."
        ),
        "recommended_next_step": _recommended_next_step(best, decision),
    }


def _recommended_next_step(candidate: dict[str, Any] | None, decision: dict[str, Any]) -> str:
    if candidate is None:
        return "Expand the universe and run robustness validation before model selection."
    if decision["trade_ready"]:
        return "Run independent universe-expansion and robustness validation before any operational use."
    failed = set(decision.get("failed_trade_gates", []))
    if "mean_icir" in failed and "ready_ratio" in failed:
        return (
            "Expand the universe and run robustness validation; do not continue small blend-weight tuning. "
            "The current candidate remains stronger research-only."
        )
    if "ready_ratio" in failed:
        return "Expand the universe and validate cross-window robustness before any trade-guidance claim."
    if "worst_drawdown" in failed:
        return "Stress drawdown under universe expansion and robustness validation before promotion."
    return "Run universe expansion and robustness validation before promotion."


def render_model_decision_markdown(pack: dict[str, Any]) -> str:
    """Render a concise model decision pack as Markdown."""

    best = pack.get("current_best_candidate") or {}
    decision = pack.get("decision") or {}
    lines = [
        "# AlphaEngine 10D Model Decision Pack",
        "",
        f"Decision status: **{decision.get('status', 'unknown')}**",
        f"Trade ready: **{bool(decision.get('trade_ready'))}**",
        "",
        "## Current best candidate",
        "",
        f"- Candidate: `{best.get('candidate', 'none')}`",
        f"- Mean ICIR: `{best.get('mean_icir', 'n/a')}`",
        f"- Mean Rank IC: `{best.get('mean_rank_ic', 'n/a')}`",
        f"- Mean spread: `{best.get('mean_spread', 'n/a')}`",
        f"- Worst drawdown: `{best.get('worst_drawdown', 'n/a')}`",
        f"- Ready ratio: `{best.get('ready_ratio', 'n/a')}`",
        "",
        "## Failed trade-guidance gates",
        "",
    ]
    failed = decision.get("failed_trade_gates", []) or []
    if failed:
        lines.extend(f"- `{item}`" for item in failed)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Warning",
            "",
            str(pack.get("non_trade_ready_warning", "Research evidence is not trade authorization.")),
            "",
            "## Recommended next step",
            "",
            str(pack.get("recommended_next_step", "Continue validation.")),
            "",
        ]
    )
    return "\n".join(lines)
