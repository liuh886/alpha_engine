import subprocess
import sys
from pathlib import Path


def test_e2e_smoke_dry_run():
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "scripts/e2e_smoke.py", "--dry-run"]
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)

    assert result.returncode == 0
    assert "=== E2E Smoke Test (Dry Run) ===" in result.stdout
    assert "scripts/update_data.py" in result.stdout
    assert "rebacktest" in result.stdout
    assert "arena_settle.py" in result.stdout
    assert "export_reports_zip.py" in result.stdout


def test_e2e_smoke_dry_run_passes_market_to_update_data():
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "scripts/e2e_smoke.py", "--dry-run", "--market", "us"]
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)

    assert result.returncode == 0
    assert "scripts/update_data.py --lookback-days 1 --market us" in result.stdout
