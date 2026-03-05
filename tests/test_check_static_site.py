import subprocess
import sys
from pathlib import Path


def test_check_static_site_smoke():
    root = Path(__file__).resolve().parents[1]
    # We use the actual 'site' directory for this test if it exists
    site_dir = root / "site"
    if not site_dir.exists():
        # Fallback to creating a minimal valid site for testing the script
        site_dir = root / "artifacts" / "site" / "test_site"
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "index.html").write_text("...")
        (site_dir / "app.js").write_text("...")
        (site_dir / "styles.css").write_text("...")
        (site_dir / "data").mkdir(exist_ok=True)
        import json
        with open(site_dir / "data" / "manifest.json", "w") as f:
            json.dump({"generated_at": "...", "stats": {}}, f)
        with open(site_dir / "data" / "models.json", "w") as f:
            json.dump([], f)
        with open(site_dir / "data" / "arena.json", "w") as f:
            json.dump({}, f)
        with open(site_dir / "data" / "reports.json", "w") as f:
            json.dump([], f)

    cmd = [
        sys.executable, "scripts/check_static_site.py",
        "--site-dir", str(site_dir)
    ]
    
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    assert result.returncode == 0
    assert "[OK] Static Site Check Passed." in result.stdout
