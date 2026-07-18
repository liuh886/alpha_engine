"""Weekly automated research cycle.

Runs every week via cron/PM2:
1. Refresh market data (US + CN)
2. Run canonical spec-bound research cycle for each market
3. Check for factor decay in Active factors
4. Generate weekly report
5. Log results to ExperimentJournal
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.common.logging import get_logger
from src.reliability.classifier import classify_failure
from src.research.workflow_runtime import create_research_workflow
from src.research.workflow_types import ResearchWorkflowRequest, ResearchWorkflowResult, WorkflowStatus

log = get_logger(__name__)

REPORT_DIR = PROJECT_ROOT / "artifacts" / "reports" / "weekly"


def _task_slug() -> str:
    return "weekly_research"


def _refresh_market_data(market: str) -> bool:
    """Refresh market data for a single market. Returns True on success."""
    from src.agents.tools.data_tools import run_data_update

    log.info("data_refresh_start", market=market)
    result = run_data_update(market=market)
    if result.get("success"):
        log.info("data_refresh_success", market=market)
        return True

    log.error(
        "data_refresh_failed",
        market=market,
        error=result.get("error", "unknown"),
    )
    return False


def _run_research_for_market(market: str) -> ResearchWorkflowResult | None:
    """Run canonical spec-bound research for a market.

    Uses the single canonical ``create_research_workflow().run()`` path
    (ADR-0009).  Returns the workflow result or ``None`` on failure.
    """
    log.info("research_cycle_start", market=market)
    try:
        request = ResearchWorkflowRequest(
            market=market,
            goal=f"Weekly automated research for {market.upper()}",
            requested_by="weekly_research",
            metadata={"source": "weekly_research"},
        )
        wf_result = create_research_workflow().run(request)

        log.info(
            "research_cycle_complete",
            market=market,
            status=wf_result.status.value,
            run_id=wf_result.run_id,
        )
        return wf_result
    except Exception as exc:
        log.error("research_cycle_failed", market=market, error=str(exc))
        return None


def _check_factor_decay() -> list[dict]:
    """Run factor decay check on Active factors. Returns decay results."""
    from scripts.check_factor_decay import check_all_active_factors

    log.info("factor_decay_check_start")
    results = check_all_active_factors()
    n_decaying = sum(1 for r in results if r.get("status") in ("decaying", "critical_decay"))
    log.info(
        "factor_decay_check_complete",
        total_checked=len(results),
        decaying=n_decaying,
    )
    return results


def _generate_report(
    us_result: ResearchWorkflowResult | None,
    cn_result: ResearchWorkflowResult | None,
    decay_results: list[dict],
    market_success: dict[str, bool],
) -> str:
    """Generate the weekly report as a markdown string."""
    from scripts.generate_weekly_report import build_weekly_report

    return build_weekly_report(
        us_result=us_result,
        cn_result=cn_result,
        decay_results=decay_results,
        market_success=market_success,
    )


def _save_report(report_text: str) -> Path:
    """Save the weekly report to artifacts/reports/weekly/. Returns the path."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    path = REPORT_DIR / f"weekly_report_{date_str}.md"
    path.write_text(report_text, encoding="utf-8")
    log.info("report_saved", path=str(path))
    return path


def _log_to_journal(
    us_result: ResearchWorkflowResult | None,
    cn_result: ResearchWorkflowResult | None,
    decay_results: list[dict],
) -> None:
    """Log weekly research summary to the experiment journal."""
    from src.research.experiment_journal import ExperimentJournal

    journal = ExperimentJournal()
    summary = journal.get_summary()

    log.info(
        "journal_summary",
        factor_total=summary.get("factors", {}).get("total", 0),
        model_total=summary.get("models", {}).get("total", 0),
        walk_forward_files=summary.get("walk_forward", {}).get("total_files", 0),
    )

    # Log canonical workflow results as structured events
    for market, wf_result in [("us", us_result), ("cn", cn_result)]:
        if wf_result is None:
            log.info("weekly_cycle_result", market=market, status="skipped")
            continue
        pd = wf_result.promotion_decision or {}
        log.info(
            "weekly_cycle_result",
            market=market,
            run_id=wf_result.run_id,
            status=wf_result.status.value,
            promotion_status=pd.get("status", "not_evaluated"),
            trade_ready=bool(pd.get("trade_ready", False)),
        )

    # Log decay results
    for dr in decay_results:
        if dr.get("status") in ("decaying", "critical_decay"):
            log.warning(
                "factor_decay_detected",
                factor_name=dr.get("name"),
                factor_id=dr.get("factor_id"),
                status=dr.get("status"),
                recent_ic=dr.get("recent_ic"),
                historical_ic=dr.get("historical_ic"),
                decay_ratio=dr.get("decay_ratio"),
            )


def run_weekly_research(
    markets: list[str] | None = None,
    skip_data: bool = False,
    skip_decay: bool = False,
) -> int:
    """Main entry point for weekly research automation.

    Args:
        markets: List of markets to process (``"us"``, ``"cn"``).
            Defaults to ``["us", "cn"]`` (equivalent to ``--market all``).
        skip_data: If True, skip the data refresh step.
        skip_decay: If True, skip the factor decay check.

    Returns:
        0 on success, 1 on partial failure, 2 on total failure.
    """
    from src.governance.service import GovernanceService

    if markets is None:
        markets = ["us", "cn"]

    gov = GovernanceService(PROJECT_ROOT)
    task_slug = _task_slug()

    print("=== Starting Weekly Research Cycle ===")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"  Timestamp: {timestamp}")
    print(f"  Markets: {', '.join(m.upper() for m in markets)}")
    if skip_data:
        print("  [skip-data] Data refresh will be skipped.")
    if skip_decay:
        print("  [skip-decay] Factor decay check will be skipped.")

    gov.update_task_status(
        task_slug,
        status="RUNNING",
        source="weekly_research",
        details={"action": "Weekly Research Cycle", "markets": markets},
    )
    gov.log_run_event(
        "all",
        "Weekly Research",
        "STARTED",
        task_slug=task_slug,
        source="weekly_research",
    )

    market_success: dict[str, bool] = {}
    all_results: dict[str, ResearchWorkflowResult | None] = {}
    decay_results: list[dict] = []
    errors: list[str] = []

    try:
        # ------------------------------------------------------------------
        # Step 1: Refresh market data (skipped if --skip-data)
        # ------------------------------------------------------------------
        if skip_data:
            print("\n[1/5] Skipping data refresh (--skip-data).")
            for market in markets:
                market_success[market] = True  # absent = not failed
        else:
            print("\n[1/5] Refreshing market data...")
            for market in markets:
                ok = _refresh_market_data(market)
                market_success[market] = ok
                if not ok:
                    errors.append(f"Data refresh failed for {market}")

        # ------------------------------------------------------------------
        # Step 2-3: Run canonical spec-bound research for each market
        # ------------------------------------------------------------------
        for market in markets:
            step_label = "2" if market == "us" else "3"
            print(f"\n[{step_label}/5] Running spec-bound research for {market.upper()}...")
            if not market_success.get(market):
                print(f"  Skipping {market.upper()} (data refresh failed).")
                all_results[market] = None
                continue

            try:
                wf_result = _run_research_for_market(market)
                all_results[market] = wf_result
                if wf_result is not None:
                    pd = wf_result.promotion_decision or {}
                    print(
                        f"  {market.upper()}: canonical spec-bound cycle, "
                        f"status={wf_result.status.value}, "
                        f"promotion={pd.get('status', 'not_evaluated')}, "
                        f"trade_ready={pd.get('trade_ready', False)}."
                    )
                    if wf_result.status != WorkflowStatus.COMPLETED:
                        status_text = wf_result.status.value
                        errors.append(
                            f"Research for {market} completed with status {status_text}"
                        )
                else:
                    print(f"  {market.upper()}: research cycle failed (exception).")
                    errors.append(f"Research failed for {market}")
            except Exception as exc:
                all_results[market] = None
                errors.append(f"Research failed for {market}: {exc}")
                log.error("research_failed", market=market, error=str(exc))

        # ------------------------------------------------------------------
        # Step 4: Factor decay check (skipped if --skip-decay)
        # ------------------------------------------------------------------
        if skip_decay:
            print("\n[4/5] Skipping factor decay check (--skip-decay).")
        else:
            print("\n[4/5] Checking factor decay...")
            try:
                decay_results = _check_factor_decay()
                n_alerts = sum(
                    1 for r in decay_results if r.get("status") in ("decaying", "critical_decay")
                )
                print(f"  Checked {len(decay_results)} Active factors, {n_alerts} decay alerts.")
            except Exception as exc:
                errors.append(f"Decay check failed: {exc}")
                log.error("decay_check_failed", error=str(exc))

        # ------------------------------------------------------------------
        # Step 5: Generate and save report
        # ------------------------------------------------------------------
        print("\n[5/5] Generating weekly report...")
        us_result = all_results.get("us")
        cn_result = all_results.get("cn")

        report_text = _generate_report(us_result, cn_result, decay_results, market_success)
        report_path = _save_report(report_text)
        print(f"  Report saved: {report_path}")

        # Log to journal
        _log_to_journal(us_result, cn_result, decay_results)

        # ------------------------------------------------------------------
        # Finalize
        # ------------------------------------------------------------------
        has_failures = any(not ok for ok in market_success.values()) or errors

        if not has_failures:
            print("\n=== Weekly Research Completed Successfully. ===")
            gov.log_run_event(
                "all",
                "Weekly Research",
                "SUCCESS",
                task_slug=task_slug,
                source="weekly_research",
            )
            gov.update_task_status(
                task_slug,
                status="DONE",
                source="weekly_research",
                last_outcome="SUCCESS",
            )
            return 0

        print(f"\n!!! Weekly Research completed with {len(errors)} error(s). !!!")
        for err in errors:
            print(f"  - {err}")
        gov.log_run_event(
            "all",
            "Weekly Research",
            "PARTIAL",
            task_slug=task_slug,
            source="weekly_research",
        )
        gov.update_task_status(
            task_slug,
            status="DONE",
            source="weekly_research",
            last_outcome="PARTIAL",
        )
        return 1

    except Exception as exc:
        print(f"\n[ERROR] Weekly Research crashed: {exc}", file=sys.stderr)
        event = classify_failure(
            component="weekly_research",
            operation="run_weekly_research",
            exc=exc,
        )
        gov.log_reliability_event(event, task_slug=task_slug, source="weekly_research")
        gov.update_task_status(
            task_slug,
            status="ERROR",
            source="weekly_research",
            last_outcome="CRASH",
        )
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly automated research cycle")
    parser.add_argument(
        "--market",
        type=str,
        default="all",
        choices=["cn", "us", "all"],
        help="Market to process (default: all)",
    )
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Skip data refresh step",
    )
    parser.add_argument(
        "--skip-decay",
        action="store_true",
        help="Skip factor decay check",
    )
    args = parser.parse_args()

    # Convert --market flag to a list of markets
    if args.market == "all":
        selected_markets = ["us", "cn"]
    else:
        selected_markets = [args.market]

    return run_weekly_research(
        markets=selected_markets,
        skip_data=args.skip_data,
        skip_decay=args.skip_decay,
    )


if __name__ == "__main__":
    sys.exit(main())
