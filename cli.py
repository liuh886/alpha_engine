import argparse
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

def run_cmd(cmd: list[str], err_msg: str):
    print(f"🚀 Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"❌ {err_msg}")
        sys.exit(result.returncode)

def main():
    parser = argparse.ArgumentParser(description="Alpha Engine Zero-Barrier CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: backtest
    parser_bt = subparsers.add_parser("backtest", help="Run a quick backtest pipeline")
    parser_bt.add_argument("--market", type=str, default="us", choices=["cn", "us"], help="Market to test")
    
    # Command: breakfast
    parser_br = subparsers.add_parser("breakfast", help="Generate daily morning trading report")
    parser_br.add_argument("--market", type=str, default="us", choices=["cn", "us"])

    # Command: workflow
    parser_wf = subparsers.add_parser("workflow", help="Run a formal workflow (train or backtest)")
    parser_wf.add_argument("type", choices=["train", "backtest"], help="Workflow type")
    parser_wf.add_argument("--market", type=str, default="us", help="Market (cn/us/all)")
    parser_wf.add_argument("--model-type", type=str, default="lgbm", help="Model type (lgbm/linear)")
    parser_wf.add_argument("--tag", type=str, default="", help="Model tag")
    parser_wf.add_argument("--profile", type=str, default="", help="Path to strategy profile JSON")

    args = parser.parse_args()

    if args.command == "workflow":
        from src.workflows.manager import WorkflowManager
        manager = WorkflowManager(PROJECT_ROOT)
        if args.type == "train":
            manager.run_training_workflow(
                market=args.market,
                model_type=args.model_type,
                profile=args.profile,
                tag=args.tag,
            )
        elif args.type == "backtest":
            manager.run_backtest_workflow(
                market=args.market,
                model_type=args.model_type,
                profile=args.profile,
                tag=args.tag,
            )
        print(f"✅ Workflow {args.type} completed successfully.")

    elif args.command == "backtest":
        print(f"==> Starting Zero-Barrier Backtest for {args.market.upper()} <==")
        run_cmd([sys.executable, "scripts/update_data.py", "--market", args.market, "--lookback-days", "5"], "Data update failed")
        run_cmd([sys.executable, "-m", "src.orchestrator", "rebacktest", "--market", args.market], "Backtest execution failed")
        run_cmd([sys.executable, "scripts/build_dashboard_db.py"], "Dashboard DB build failed")
        print("✅ Backtest Complete! Run `make dev` to view results.")

    elif args.command == "breakfast":
        print(f"==> Generating Trading Breakfast for {args.market.upper()} <==")
        run_cmd([sys.executable, "scripts/generate_breakfast.py", "--market", args.market], "Breakfast generation failed")
        print("✅ Breakfast markdown generated in artifacts/reports/")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
