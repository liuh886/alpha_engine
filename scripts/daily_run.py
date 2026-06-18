import argparse
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from scripts.build_dashboard_db import build_db
from src.agents.research_assistant import ResearchAssistant
from src.agents.tools.data_tools import run_data_update
from src.agents.tools.orchestrator_tools import run_orchestrator
from src.governance.service import GovernanceService
from src.reliability.classifier import classify_failure


def _task_slug(market: str) -> str:
    return f"daily_run.{str(market).lower()}"


def main():
    parser = argparse.ArgumentParser(description="Daily Routine for Trading Assistant")
    parser.add_argument(
        "--market", type=str, default="all", choices=["cn", "us", "all"], help="Market to process"
    )

    args = parser.parse_args()
    gov = GovernanceService(PROJECT_ROOT)
    agent = ResearchAssistant()
    task_slug = _task_slug(args.market)

    print(f"=== Starting Daily Routine for {args.market.upper()} ===")
    gov.update_task_status(
        task_slug,
        status="RUNNING",
        source="daily_run",
        market=args.market,
        details={"action": "Daily Routine"},
    )
    gov.log_run_event(
        args.market,
        "Daily Routine",
        "STARTED",
        task_slug=task_slug,
        source="daily_run",
    )

    markets = ["cn", "us"] if args.market == "all" else [args.market]

    overall_success = True
    try:
        for market in markets:
            print(f"\n>>> Processing Market: {market.upper()}")

            # 1. Update Data
            print("[1/4] Updating Market Data...")
            data_res = run_data_update(market=market)
            if not data_res["success"]:
                event = data_res.get("event")
                if event and agent.self_heal(event):
                    print("  Self-healing: Retrying data update...")
                    data_res = run_data_update(market=market)

                if not data_res["success"]:
                    print(f"  [ERROR] Data update failed for {market}.", file=sys.stderr)
                    overall_success = False
                    continue

            # 2. Run Inference (using orchestrator run mode)
            print("[2/4] Running Inference (Strategy Prediction)...")
            inf_res = run_orchestrator(
                market=market, mode="run", tag=f"DAILY_{time.strftime('%Y%m%d')}"
            )
            if not inf_res["success"]:
                event = inf_res.get("event")
                if event and agent.self_heal(event):
                    print("  Self-healing: Retrying inference...")
                    inf_res = run_orchestrator(
                        market=market, mode="run", tag=f"DAILY_{time.strftime('%Y%m%d')}"
                    )

                if not inf_res["success"]:
                    print(f"  [ERROR] Inference failed for {market}.", file=sys.stderr)
                    overall_success = False
                    continue

            # 3. Generate Trading Report & Ticket
            print("[3/4] Generating Trading Report & Ticket...")
            try:
                from src.reporting.generate import generate_report

                generate_report(market)
            except Exception as e:
                print(f"  [WARNING] Report generation failed: {e}")

        # 4. Build Dashboard JSON
        if overall_success:
            print("\n[4/4] Finalizing Dashboard Data...")
            try:
                build_db()
            except Exception as e:
                print(f"  [ERROR] Dashboard DB build failed: {e}")
                return 3

        if not overall_success:
            print("\n!!! Daily Routine FAILED for one or more markets. !!!")
            return 2

        print("\n=== Daily Routine Completed Successfully. ===")
        gov.log_run_event(
            args.market,
            "Daily Routine",
            "SUCCESS",
            task_slug=task_slug,
            source="daily_run",
        )
        gov.update_task_status(
            task_slug,
            status="DONE",
            source="daily_run",
            market=args.market,
            last_outcome="SUCCESS",
        )
        return 0

    except Exception as e:
        print(f"\n[ERROR] Daily Routine crashed: {e}", file=sys.stderr)
        # Catch-all classification for top-level routine failures
        event = classify_failure(component="daily_run", exc=e, context={"market": args.market})
        gov.log_reliability_event(event, task_slug=task_slug, source="daily_run")
        return 1


if __name__ == "__main__":
    sys.exit(main())
