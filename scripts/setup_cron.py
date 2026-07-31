"""Set up Alpha Engine research and daily decision automation."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

DAILY_LOCAL_CRON = "30 7 * * 2-6"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _daily_args(project_root: Path) -> str:
    return str(project_root / "scripts" / "run_latest_us_low_turnover_decision.py")


def setup_pm2_cron() -> str:
    """Write a PM2 ecosystem with daily and weekly research jobs."""

    project_root = _project_root()
    python_exe = Path(sys.executable).resolve()
    pm2_config = {
        "apps": [
            {
                "name": "alpha-daily-us-decision",
                "script": str(python_exe),
                "args": _daily_args(project_root),
                "cwd": str(project_root),
                "cron_restart": DAILY_LOCAL_CRON,
                "autorestart": False,
                "max_memory_restart": "2G",
                "time": True,
            },
            {
                "name": "alpha-weekly-research",
                "script": str(python_exe),
                "args": f"{project_root / 'scripts' / 'weekly_research.py'} --market us",
                "cwd": str(project_root),
                "cron_restart": "0 9 * * 1",
                "autorestart": False,
                "max_memory_restart": "1G",
            },
            {
                "name": "alpha-decay-check",
                "script": str(python_exe),
                "args": f"{project_root / 'scripts' / 'check_factor_decay.py'} --update-metadata",
                "cwd": str(project_root),
                "cron_restart": "0 8 * * 1",
                "autorestart": False,
            },
            {
                "name": "alpha-weekly-report",
                "script": str(python_exe),
                "args": str(project_root / "scripts" / "generate_weekly_report.py"),
                "cwd": str(project_root),
                "cron_restart": "0 10 * * 1",
                "autorestart": False,
            },
        ]
    }
    config_path = project_root / "ecosystem.config.json"
    config_path.write_text(json.dumps(pm2_config, indent=2), encoding="utf-8")
    print(f"PM2 config written to {config_path}")
    print("Set SEC_USER_AGENT in the PM2 environment before starting the daily job.")
    print("To start: pm2 start ecosystem.config.json --update-env")
    print("To verify: pm2 list")
    return str(config_path)


def _windows_daily_batch(project_root: Path, python_exe: Path) -> str:
    return f"""@echo off
cd /d "{project_root}"
if not defined SEC_USER_AGENT (
  echo SEC_USER_AGENT is required for SEC Company Facts access.
  exit /b 2
)
if not exist artifacts/logs mkdir artifacts/logs
"{python_exe}" scripts/run_latest_us_low_turnover_decision.py >> artifacts/logs/daily_us_decision.log 2>&1
exit /b %ERRORLEVEL%
"""


def setup_windows_task() -> str:
    """Write Windows batch launchers and print Task Scheduler commands."""

    project_root = _project_root()
    python_exe = Path(sys.executable).resolve()
    weekly_batch = f"""@echo off
cd /d "{project_root}"
"{python_exe}" scripts/weekly_research.py --market us
"{python_exe}" scripts/check_factor_decay.py --update-metadata
"{python_exe}" scripts/generate_weekly_report.py
"""
    weekly_path = project_root / "scripts" / "run_weekly.bat"
    weekly_path.write_text(weekly_batch, encoding="utf-8")
    daily_path = project_root / "scripts" / "run_daily_us_decision.bat"
    daily_path.write_text(
        _windows_daily_batch(project_root, python_exe),
        encoding="utf-8",
    )
    print(f"Weekly batch written to {weekly_path}")
    print(f"Daily decision batch written to {daily_path}")
    print("Set SEC_USER_AGENT as a persistent user environment variable first.")
    print(
        "Daily schedule: schtasks /create /f /tn \"AlphaEngine Daily US Decision\" "
        f"/tr \"{daily_path}\" /sc weekly /d TUE,WED,THU,FRI,SAT /st 07:30"
    )
    print(
        "Weekly schedule: schtasks /create /f /tn \"AlphaEngine Weekly Research\" "
        f"/tr \"{weekly_path}\" /sc weekly /d MON /st 09:00"
    )
    return str(daily_path)


def main() -> int:
    if platform.system() == "Windows":
        path = setup_windows_task()
        print(f"\nWindows automation setup complete: {path}")
    else:
        path = setup_pm2_cron()
        print(f"\nPM2 automation setup complete: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
