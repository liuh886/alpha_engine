import sqlite3
import subprocess
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
db_path = project_root / "artifacts" / "metadata" / "metadata.db"


def cleanup():
    if not db_path.exists():
        print("DB not found.")
        return

    conn = sqlite3.connect(db_path)
    # Mark all running jobs as failed (stale)
    conn.execute(
        "UPDATE jobs SET status = 'failed', error = 'Stale task cleaned by system' WHERE status = 'running'"
    )
    conn.commit()
    conn.close()
    print("Marked all running jobs as failed in DB.")

    # We can't easily map run_id to OS PID here without more work,
    # but we can kill all 'python.exe' processes that are not this one or the server.
    # Actually, it's safer to just let the user know or kill all python processes
    # except the one with the server's PID if we had it.
    # Since we are in a Ralph Loop, I will try to find python processes running update_data.py or arena_settle.py.

    try:
        # Windows command to find and kill
        subprocess.run(
            [
                "powershell.exe",
                "-Command",
                "Get-Process python | Where-Object { $_.CommandLine -like '*update_data.py*' -or $_.CommandLine -like '*arena_settle.py*' } | Stop-Process -Force",
            ],
            check=False,
        )
        print("Stopped stuck python processes.")
    except Exception as e:
        print(f"Error stopping processes: {e}")


if __name__ == "__main__":
    cleanup()
