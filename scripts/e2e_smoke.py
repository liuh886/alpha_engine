import argparse
import subprocess
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


def run_step(name, cmd, dry_run=False):
    print(f"\n>>> [Step] {name}")
    print(f"Executing: {' '.join(cmd)}")
    if dry_run:
        print("[DRY RUN] Skipping execution.")
        return True

    start_time = time.time()
    try:
        subprocess.run(cmd, check=True)
        elapsed = time.time() - start_time
        print(f"<<< [Step] {name} Success ({elapsed:.2f}s)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"<<< [Step] {name} FAILED (Exit Code: {e.returncode})")
        return False


def main():
    parser = argparse.ArgumentParser(description="E2E Smoke Test for Trading Assistant")
    parser.add_argument(
        "--market", type=str, default="us", choices=["cn", "us", "all"], help="Market to test"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print steps without executing")

    args = parser.parse_args()

    if args.dry_run:
        print("=== E2E Smoke Test (Dry Run) ===")

    steps = [
        (
            "Data Update",
            [
                sys.executable,
                "scripts/update_data.py",
                "--lookback-days",
                "1",
                "--market",
                args.market,
            ],
        ),
        (
            "Re-backtest",
            [
                sys.executable,
                "-m",
                "src.orchestrator",
                "rebacktest",
                "--market",
                args.market,
                "--refresh_dashboard_db",
                "True",
            ],
        ),
        (
            "Arena Settle",
            [
                sys.executable,
                "scripts/arena_settle.py",
                "--market",
                args.market,
                "--arena-name",
                f"{args.market.upper()}_Smoke_Arena",
            ],
        ),
        ("Build Dashboard", [sys.executable, "scripts/build_dashboard_db.py"]),
        (
            "Export Reports",
            [sys.executable, "scripts/export_reports_zip.py", "--type", "all", "--limit", "5"],
        ),
    ]

    success = True
    for name, cmd in steps:
        if not run_step(name, cmd, args.dry_run):
            success = False
            break

    if success:
        print("\n[SUCCESS] E2E Smoke Test Completed Successfully.")
        sys.exit(0)
    else:
        print("\n[FAILURE] E2E Smoke Test Failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
