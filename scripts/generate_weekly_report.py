"""Generate weekly alpha research report.

Report includes:
- Summary: canonical spec-bound workflow status per market
- Research cycles: run identity, workflow status, promotion status, trade_ready
- Factor library status: total by stage, by category
- Top performers: top 5 factors by ICIR
- Decay alerts: factors with declining IC
- Walk-forward status: latest validation results
- Recommendations: what to investigate next
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.common.logging import get_logger
from src.research.workflow_types import ResearchWorkflowResult, WorkflowStatus

log = get_logger(__name__)


def _section_header(title: str) -> str:
    return f"\n## {title}\n"


def _format_workflow_summary(
    market: str,
    wf_result: ResearchWorkflowResult | None,
) -> str:
    """Format canonical workflow result for one market into markdown."""
    if wf_result is None:
        return f"**{market.upper()}**: No research run this week.\n"

    pd = wf_result.promotion_decision or {}
    lines = [
        f"**{market.upper()}** (canonical spec-bound execution, ADR-0009):",
        f"- Run ID: `{wf_result.run_id}`",
        f"- Workflow status: **{wf_result.status.value}**",
        f"- Started: {wf_result.started_at or 'N/A'}",
    ]
    if wf_result.completed_at:
        lines.append(f"- Completed: {wf_result.completed_at}")

    lines.append(f"- Steps executed: {len(wf_result.steps)}")
    for step in wf_result.steps:
        status_mark = "✓" if step.status == WorkflowStatus.COMPLETED else (
            "✗" if step.status == WorkflowStatus.FAILED else "○"
        )
        lines.append(f"  - {status_mark} {step.step.value}: {step.status.value}")

    lines.append(f"- Promotion status: **{pd.get('status', 'not_evaluated')}**")
    lines.append(f"- Trade ready: **{pd.get('trade_ready', False)}**")

    if wf_result.warnings:
        lines.append(f"- Warnings: {len(wf_result.warnings)}")
        for w in wf_result.warnings[:3]:
            lines.append(f"  - ⚠ {w}")

    return "\n".join(lines) + "\n"


def _format_decay_alerts(decay_results: list[dict]) -> str:
    """Format decay check results into markdown alerts."""
    if not decay_results:
        return "No Active factors to check.\n"

    alerts = [r for r in decay_results if r.get("status") in ("decaying", "critical_decay")]

    if not alerts:
        return "All Active factors are healthy -- no decay detected.\n"

    lines = [f"**{len(alerts)} factor(s) showing alpha decay:**\n"]

    for r in alerts:
        status_label = "CRITICAL" if r["status"] == "critical_decay" else "WARNING"
        lines.append(
            f"- [{status_label}] **{r.get('name', '?')}** (id={r.get('factor_id')}): "
            f"recent IC={r.get('recent_ic', 0):.4f}, "
            f"historical IC={r.get('historical_ic', 0):.4f}, "
            f"ratio={r.get('decay_ratio', 0):.1%}"
        )

    return "\n".join(lines) + "\n"


def _format_factor_library_status() -> str:
    """Query the factor registry and format library status."""
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    stats = registry.get_stats()

    lines = [
        f"**Total factors:** {stats['total_factors']}",
        "",
        "| Stage | Count |",
        "|-------|-------|",
    ]
    for stage, count in sorted(stats.get("by_stage", {}).items()):
        lines.append(f"| {stage} | {count} |")

    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    for cat, count in sorted(
        stats.get("by_category", {}).items(), key=lambda x: x[1], reverse=True
    ):
        lines.append(f"| {cat} | {count} |")

    lines.append("")
    total_val = stats.get("total_validations", 0)
    total_passed = stats.get("total_passed_validations", 0)
    pass_rate = (total_passed / total_val * 100) if total_val > 0 else 0.0
    lines.append(f"**Validations:** {total_passed}/{total_val} passed ({pass_rate:.1f}%)")

    return "\n".join(lines) + "\n"


def _format_top_performers() -> str:
    """Query the factor registry for top 5 factors by ICIR."""
    from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

    registry = FactorRegistry()
    active_factors = registry.list_factors(stage=STAGE_ACTIVE)

    if not active_factors:
        return "No Active factors in the registry.\n"

    # Gather ICIR from latest validation for each active factor
    factor_metrics: list[dict] = []
    for f in active_factors:
        validations = registry.get_validations(f["id"])
        latest = validations[0] if validations else None
        if latest and latest.get("icir") is not None:
            factor_metrics.append(
                {
                    "name": f["name"],
                    "category": f.get("category", "unknown"),
                    "icir": latest["icir"],
                    "ic": latest.get("ic", 0.0),
                    "rank_ic": latest.get("rank_ic", 0.0),
                }
            )

    if not factor_metrics:
        return "No Active factors with ICIR data.\n"

    # Sort by ICIR descending, take top 5
    top5 = sorted(factor_metrics, key=lambda x: abs(x["icir"]), reverse=True)[:5]

    lines = [
        "| Rank | Factor | Category | ICIR | IC | Rank IC |",
        "|------|--------|----------|------|----|---------|",
    ]
    for i, fm in enumerate(top5, 1):
        lines.append(
            f"| {i} | {fm['name']} | {fm['category']} | "
            f"{fm['icir']:.3f} | {fm['ic']:.4f} | {fm['rank_ic']:.4f} |"
        )

    return "\n".join(lines) + "\n"


def _format_walk_forward_status() -> str:
    """Query the experiment journal for latest walk-forward results."""
    from src.research.experiment_journal import ExperimentJournal

    journal = ExperimentJournal()
    wf_results = journal.list_walk_forward_results(limit=5)

    if not wf_results:
        return "No walk-forward validation results found.\n"

    lines = [
        "| Market | Model | Mean IC | IC IR | Consistency | Date |",
        "|--------|-------|---------|-------|-------------|------|",
    ]
    for r in wf_results:
        ts = r.get("timestamp", "?")
        if len(ts) > 10:
            ts = ts[:10]
        lines.append(
            f"| {r.get('market', '?')} | {r.get('model_type', '?')} | "
            f"{r.get('mean_ic', 0):.4f} | {r.get('ic_ir', 0):.3f} | "
            f"{r.get('consistency_score', 0):.2f} | {ts} |"
        )

    return "\n".join(lines) + "\n"


def _format_recommendations(
    us_result: ResearchWorkflowResult | None,
    cn_result: ResearchWorkflowResult | None,
    decay_results: list[dict],
) -> str:
    """Generate actionable recommendations based on workflow results and decay data."""
    recommendations: list[str] = []

    # Check for failed workflows
    for label, wf_result in [("US", us_result), ("CN", cn_result)]:
        if wf_result is None:
            continue
        if wf_result.status == WorkflowStatus.FAILED:
            recommendations.append(
                f"- **Investigate {label} failure**: workflow {wf_result.run_id} "
                f"failed. Check steps for errors."
            )
        elif wf_result.status == WorkflowStatus.COMPLETED:
            pd = wf_result.promotion_decision or {}
            promo_status = pd.get("status", "not_evaluated")
            if promo_status in ("missing_evidence", "evidence_insufficient"):
                recommendations.append(
                    f"- **{label} promotion blocked**: status={promo_status}. "
                    "Gather additional evidence before re-evaluation."
                )

    # Check for decay
    critical = [r for r in decay_results if r.get("status") == "critical_decay"]
    if critical:
        names = ", ".join(r.get("name", "?") for r in critical)
        recommendations.append(
            f"- **Critical decay alert**: {names} -- consider demoting to "
            "Deprecated or running fresh validation."
        )

    decaying = [r for r in decay_results if r.get("status") == "decaying"]
    if decaying:
        names = ", ".join(r.get("name", "?") for r in decaying)
        recommendations.append(
            f"- **Monitor decaying factors**: {names} -- re-validate with "
            "recent data before next promotion cycle."
        )

    # Check for trade-ready factors
    for label, wf_result in [("US", us_result), ("CN", cn_result)]:
        if wf_result is not None and wf_result.promotion_decision:
            if wf_result.promotion_decision.get("trade_ready"):
                recommendations.append(
                    f"- **{label} trade-ready**: workflow {wf_result.run_id} "
                    "passed all evidence gates. Review promotion decision."
                )

    if not recommendations:
        recommendations.append(
            "- No critical issues detected. Continue current research direction."
        )

    return "\n".join(recommendations) + "\n"


def build_weekly_report(
    us_result: ResearchWorkflowResult | None,
    cn_result: ResearchWorkflowResult | None,
    decay_results: list[dict],
    market_success: dict[str, bool],
) -> str:
    """Build the full weekly report as a markdown string.

    This is the main report assembly function, called by weekly_research.py
    and also usable standalone.

    Accepts canonical ``ResearchWorkflowResult`` objects (ADR-0009).  The
    report truthfully reflects workflow status, promotion status,
    trade-readiness, and run identity -- it does not fabricate per-factor
    scan counts or backtest performance metrics that the spec-bound path
    does not produce.

    Args:
        us_result: Canonical workflow result for US market, or None.
        cn_result: Canonical workflow result for CN market, or None.
        decay_results: Factor decay check results.
        market_success: Whether data refresh succeeded per market.

    Returns:
        Complete markdown report string.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    sections: list[str] = []

    # Title
    sections.append(f"# Alpha Research Weekly Report -- {date_str}\n")

    # Executive Summary
    sections.append(_section_header("Executive Summary"))
    n_decay_alerts = sum(
        1 for r in decay_results if r.get("status") in ("decaying", "critical_decay")
    )

    markets_run: list[str] = []
    promo_parts: list[str] = []
    for label, wf_result in [("US", us_result), ("CN", cn_result)]:
        if wf_result is not None:
            markets_run.append(label)
            pd = wf_result.promotion_decision or {}
            promo_parts.append(f"{label}: {pd.get('status', 'not_evaluated')}")
    markets_str = " + ".join(markets_run) if markets_run else "none"

    summary_lines = [
        f"Markets executed: **{markets_str}** (canonical spec-bound, ADR-0009).",
        f"**{n_decay_alerts}** factor decay alert(s).",
    ]
    if promo_parts:
        summary_lines.append(f"Promotion: {', '.join(promo_parts)}.")
    sections.append(" ".join(summary_lines) + "\n")

    # Research Cycles
    sections.append(_section_header("Research Cycles"))
    if market_success.get("us") is not None:
        sections.append(_format_workflow_summary("us", us_result))
    if market_success.get("cn") is not None:
        sections.append(_format_workflow_summary("cn", cn_result))
    if not market_success:
        sections.append("No research run this week.\n")

    # Factor Library Status
    sections.append(_section_header("Factor Library Status"))
    try:
        sections.append(_format_factor_library_status())
    except Exception as exc:
        sections.append(f"Error loading library status: {exc}\n")

    # Top Performers
    sections.append(_section_header("Top Performers (by ICIR)"))
    try:
        sections.append(_format_top_performers())
    except Exception as exc:
        sections.append(f"Error loading top performers: {exc}\n")

    # Decay Alerts
    sections.append(_section_header("Decay Alerts"))
    sections.append(_format_decay_alerts(decay_results))

    # Walk-Forward Status
    sections.append(_section_header("Walk-Forward Validation"))
    try:
        sections.append(_format_walk_forward_status())
    except Exception as exc:
        sections.append(f"Error loading walk-forward results: {exc}\n")

    # Recommendations
    sections.append(_section_header("Recommendations"))
    sections.append(_format_recommendations(us_result, cn_result, decay_results))

    # Footer
    sections.append(f"\n---\n*Generated at {now.strftime('%Y-%m-%d %H:%M:%S')}*\n")

    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly alpha research report")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: artifacts/reports/weekly/weekly_report_YYYYMMDD.md)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_report",
        help="Print report to stdout instead of saving to file",
    )
    args = parser.parse_args()

    # Run a standalone report: query existing data without running new cycles
    decay_results: list[dict] = []
    try:
        from scripts.check_factor_decay import check_all_active_factors

        decay_results = check_all_active_factors()
    except Exception as exc:
        log.warning("decay_check_failed_standalone", error=str(exc))

    report = build_weekly_report(
        us_result=None,
        cn_result=None,
        decay_results=decay_results,
        market_success={},
    )

    if args.print_report:
        print(report)
        return 0

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        report_dir = PROJECT_ROOT / "artifacts" / "reports" / "weekly"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        out_path = report_dir / f"weekly_report_{date_str}.md"

    out_path.write_text(report, encoding="utf-8")
    print(f"Report saved to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
