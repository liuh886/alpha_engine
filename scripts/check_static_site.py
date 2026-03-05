import argparse
import json
import sys
from pathlib import Path


def check_site(site_dir: Path) -> bool:
    print(f"Checking static site in: {site_dir}")
    
    errors = []
    
    # 1. Check core files
    for f in ["index.html", "app.js", "styles.css", "data/manifest.json"]:
        if not (site_dir / f).exists():
            errors.append(f"Missing core file: {f}")

    # 2. Check JSON validity
    json_files = ["manifest.json", "models.json", "arena.json", "reports.json"]
    for f in json_files:
        p = site_dir / "data" / f
        if not p.exists():
            errors.append(f"Missing data file: {f}")
            continue
        try:
            with open(p, encoding="utf-8") as jf:
                json.load(jf)
        except Exception as e:
            errors.append(f"Invalid JSON in {f}: {e}")

    # 3. Check Manifest content
    manifest_path = site_dir / "data" / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
            if "generated_at" not in data:
                errors.append("Manifest missing 'generated_at'")
            if "stats" not in data:
                errors.append("Manifest missing 'stats'")

    # 4. Check Report links
    reports_path = site_dir / "data" / "reports.json"
    if reports_path.exists():
        with open(reports_path, encoding="utf-8") as f:
            reports = json.load(f)
            missing_files = 0
            for r in reports:
                if "static_html_path" in r:
                    report_file = site_dir / r["static_html_path"]
                    if not report_file.exists():
                        missing_files += 1
            if missing_files > 0:
                print(f"Warning: {missing_files} reports linked in JSON are missing from disk.")

    if errors:
        print("\n[!] Static Site Check FAILED:")
        for err in errors:
            print(f"  - {err}")
        return False
    
    print("\n[OK] Static Site Check Passed.")
    return True

def main():
    parser = argparse.ArgumentParser(description="Smoke test for static site artifacts.")
    parser.add_argument("--site-dir", type=str, default="site")
    args = parser.parse_args()
    
    ok = check_site(Path(args.site_dir))
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
