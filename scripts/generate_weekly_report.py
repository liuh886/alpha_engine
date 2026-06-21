"""Generate weekly alpha research report.

Report includes:
- Summary: new factors discovered, factors promoted, factors demoted
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

log = get_logger(__name__)


def _section_header(title: str) -> str:
    return f"\n## {title}\n"


def _format_cycle_summary(
    market: str,
    results: list,
) -> str:
    """Format research cycle results for one market into markdown."""
    if not results:
        return f"**{market.upper()}**: No research cycles run this week.\n"

    total_scanned = sum(r.factors_scanned for r in results)
    total_fdr_passed = sum(r.factors_passed_fdr for r in results)
    total_promoted = sum(r.factors_promoted for r in results)
    best_sharpe = max((r.sharpe for r in results), default=0.0)
    best_mdd = min((r.max_drawdown for r in results), default=0.0)

    lines = [
        f"**{market.upper()}** ({len(results)} cycles):",
        f"- Factors scanned: {total_scanned}",
        f"- FDR-significant: {total_fdr_passed}",
        f"- Promoted: {total_promoted}",
        f"- Best Sharpe: {best_sharpe:.3f}",
        f"- Best Max Drawdown: {best_mdd:.4f}",
    ]

    # List newly promoted factors
    new_factors = []
    for r in results:
        new_factors.extend(r.new_active_factors)
    if new_factors:
        unique_factors = sorted(set(new_factors))
        lines.append(f"- New active factors: {', '.join(unique_factors)}")

    # Cycle status summary
    statuses = [r.status for r in results]
    n_success = statuses.count("success")
    n_partial = statuses.count("partial")
    n_failed = statuses.count("failed")
    status_parts = []
    if n_success:
        status_parts.append(f"{n_success} succeeded")
    if n_partial:
        status_parts.append(f"{n_partial} partial")
    if n_failed:
        status_parts.append(f"{n_failed} failed")
    if status_parts:
        lines.append(f"- Cycle outcomes: {', '.join(status_parts)}")

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
    us_results: list,
    cn_results: list,
    decay_results: list[dict],
) -> str:
    """Generate actionable recommendations based on the week's results."""
    recommendations: list[str] = []

    # Check for failed cycles
    all_results = us_results + cn_results
    failed = [r for r in all_results if r.status == "failed"]
    if failed:
        recommendations.append(
            f"- **Investigate failures**: {len(failed)} research cycle(s) failed. "
            "Check logs for scan, backtest, or attribution errors."
        )

    # Check for low Sharpe
    all_sharpes = [r.sharpe for r in all_results if r.sharpe > 0]
    if all_sharpes and max(all_sharpes) < 0.5:
        recommendations.append(
            "- **Sharpe below target**: Best Sharpe this week was "
            f"{max(all_sharpes):.3f}. Consider scanning new factor categories "
            "or adjusting model hyperparameters."
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

    # Check for no new factors
    total_promoted = sum(r.factors_promoted for r in all_results)
    if total_promoted == 0 and all_results:
        recommendations.append(
            "- **No new factors promoted**: Consider expanding the factor "
            "pool or relaxing FDR thresholds for exploration."
        )

    # Check for concentration
    for r in all_results:
        if r.top_contributors:
            top = r.top_contributors[0]
            if top.get("contribution_pct", 0) > 50:
                recommendations.append(
                    f"- **Factor concentration**: {top.get('factor_name', '?')} "
                    f"contributes {top.get('contribution_pct', 0):.0f}% of returns. "
                    "Scan for diversifying factors."
                )

    if not recommendations:
        recommendations.append(
            "- No critical issues detected. Continue current research direction."
        )

    return "\n".join(recommendations) + "\n"


def build_weekly_report(
    us_results: list,
    cn_results: list,
    decay_results: list[dict],
    market_success: dict[str, bool],
) -> str:
    """Build the full weekly report as a markdown string.

    This is the main report assembly function, called by weekly_research.py
    and also usable standalone.

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
    all_results = us_results + cn_results
    total_scanned = sum(r.factors_scanned for r in all_results)
    total_promoted = sum(r.factors_promoted for r in all_results)
    n_decay_alerts = sum(
        1 for r in decay_results if r.get("status") in ("decaying", "critical_decay")
    )
    sections.append(
        f"Scanned **{total_scanned}** factors across "
        f"{'US + CN' if us_results and cn_results else 'US' if us_results else 'CN'}. "
        f"**{total_promoted}** promoted to Active. "
        f"**{n_decay_alerts}** decay alert(s).\n"
    )

    # Research Cycle Results
    sections.append(_section_header("Research Cycles"))
    if market_success.get("us") is not None:
        sections.append(_format_cycle_summary("us", us_results))
    if market_success.get("cn") is not None:
        sections.append(_format_cycle_summary("cn", cn_results))

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
    sections.append(_format_recommendations(us_results, cn_results, decay_results))

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
        us_results=[],
        cn_results=[],
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
