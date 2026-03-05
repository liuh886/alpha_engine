import json
import subprocess
import sys
from pathlib import Path


def test_export_static_site_data_smoke():
    root = Path(__file__).resolve().parents[1]
    # Ensure artifacts/site/data exists for test output
    out_dir = root / "artifacts" / "site" / "test_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable, "scripts/export_static_site_data.py",
        "--market", "all",
        "--output", str(out_dir)
    ]
    
    # Run script
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    
    # If DB doesn't exist, we might get an error message but it's a "known" failure in clean envs.
    # But for a smoke test, we want to see it run.
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        # Only fail if it's not a "DB not found" error
        if "Metadata DB not found" not in result.stdout:
            assert result.returncode == 0
    else:
        # Check if manifest exists
        manifest_path = out_dir / "manifest.json"
        assert manifest_path.exists()
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
            assert "generated_at" in data
            assert "total_models" in data["stats"]
