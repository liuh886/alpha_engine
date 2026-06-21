"""Set up weekly research automation via PM2 or Windows Task Scheduler."""

import os
import platform
import sys


def setup_pm2_cron():
    """Set up PM2 cron job for weekly research."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = sys.executable

    # PM2 ecosystem config for weekly research
    pm2_config = {
        "apps": [
            {
                "name": "alpha-weekly-research",
                "script": f"{python_exe}",
                "args": f"{os.path.join(project_root, 'scripts', 'weekly_research.py')} --market us",
                "cwd": project_root,
                "cron_restart": "0 9 * * 1",  # Every Monday at 9 AM
                "autorestart": False,
                "max_memory_restart": "1G",
            },
            {
                "name": "alpha-decay-check",
                "script": f"{python_exe}",
                "args": f"{os.path.join(project_root, 'scripts', 'check_factor_decay.py')} --update-metadata",
                "cwd": project_root,
                "cron_restart": "0 8 * * 1",  # Every Monday at 8 AM
                "autorestart": False,
            },
            {
                "name": "alpha-weekly-report",
                "script": f"{python_exe}",
                "args": f"{os.path.join(project_root, 'scripts', 'generate_weekly_report.py')}",
                "cwd": project_root,
                "cron_restart": "0 10 * * 1",  # Every Monday at 10 AM
                "autorestart": False,
            },
        ]
    }

    import json

    config_path = os.path.join(project_root, "ecosystem.config.json")
    with open(config_path, "w") as f:
        json.dump(pm2_config, f, indent=2)

    print(f"PM2 config written to {config_path}")
    print("To start: pm2 start ecosystem.config.json")
    print("To verify: pm2 list")

    return config_path


def setup_windows_task():
    """Set up Windows Task Scheduler for weekly research."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_exe = sys.executable

    # Create batch script for Windows Task Scheduler
    batch_content = f"""@echo off
cd /d {project_root}
"{python_exe}" scripts\weekly_research.py --market us
"{python_exe}" scripts\check_factor_decay.py --update-metadata
"{python_exe}" scripts\generate_weekly_report.py
"""

    batch_path = os.path.join(project_root, "scripts", "run_weekly.bat")
    with open(batch_path, "w") as f:
        f.write(batch_content)

    print(f"Batch script written to {batch_path}")
    print(
        "To schedule: schtasks /create /tn 'AlphaEngine Weekly Research' /tr '{batch_path}' /sc weekly /d MON /st 09:00"
    )

    return batch_path


if __name__ == "__main__":
    if platform.system() == "Windows":
        path = setup_windows_task()
        print(f"\nWindows Task Scheduler setup complete: {path}")
    else:
        path = setup_pm2_cron()
        print(f"\nPM2 cron setup complete: {path}")
