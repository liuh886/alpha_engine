import argparse
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.services.governance_service import GovernanceService


def run_step(args, cwd, capture=False):
    if capture:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.stdout + proc.stderr
    subprocess.run(args, cwd=str(cwd), check=True)
    return ""

def main():
    parser = argparse.ArgumentParser(description="Daily Routine for Trading Assistant")
    parser.add_argument("--market", type=str, default="all", choices=["cn", "us", "all"], help="Market to process")
    
    args = parser.parse_args()
    gov = GovernanceService(PROJECT_ROOT)
    
    print(f"=== Starting Daily Routine for {args.market.upper()} ===")
    
    try:
        # 1. Update Data
        print("\n[1/3] Updating Market Data...")
        run_step([sys.executable, "scripts/update_data.py", "--market", args.market, "--lookback-days", "5"], PROJECT_ROOT)
        
        # 2. Run Inference
        print("\n[2/3] Running Inference...")
        out = run_step([sys.executable, "-m", "src.inference", "--market", args.market], PROJECT_ROOT, capture=True)
        print(out)
        
        if "[!] Inference failed" in out or "No results generated" in out:
            print("\n[ERROR] Inference step failed detection in output.", file=sys.stderr)
            gov.log_run_event(args.market, "Daily Routine", "FAILURE", metric="Inference failure detected")
            return 2
        
        # 3. Build Dashboard JSON
        print("\n[3/3] Building Dashboard DB...")
        run_step([sys.executable, "scripts/build_dashboard_db.py"], PROJECT_ROOT)
        
        print("\n=== Daily Routine Completed Successfully. ===")
        gov.log_run_event(args.market, "Daily Routine", "SUCCESS")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Daily Routine failed: {e}", file=sys.stderr)
        gov.log_run_event(args.market, "Daily Routine", "FAILURE", metric=str(e)[:50])
        return 1

if __name__ == "__main__":
    sys.exit(main())
