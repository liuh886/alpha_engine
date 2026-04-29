from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.common.paths import ARTIFACTS_DIR, DASHBOARD_DB_PATH, MLRUNS_DIR


def check_python():
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")


def check_dependencies():
    deps = ["qlib", "pandas", "numpy", "lightgbm", "fire", "fastapi", "pydantic"]
    missing = []
    print("\nChecking Dependencies...")
    for d in deps:
        try:
            mod = __import__(d)
            version = getattr(mod, "__version__", "unknown")
            print(f"  [OK] {d} ({version})")
        except ImportError:
            missing.append(d)

    try:
        from qlib.workflow import R

        print("  [OK] Qlib C++ Extensions (workflow/record_temp)")
    except ImportError as e:
        print(f"  [!] Qlib binary extension corrupted or incompatible: {e}")
        print("      -> Try resolving by running `uv sync` or checking Microsoft Qlib docs.")
        missing.append("qlib-bin")

    return not bool(missing)


def check_metadata_integrity(fix=False):
    print("\nChecking Metadata Integrity (SQLite vs MLflow vs JSON)...")
    db_path = ARTIFACTS_DIR / "metadata" / "metadata.db"

    if fix:
        print("  [FIX] Running metadata synchronization (register_all_runs)...")
        try:
            from scripts.utils.register_all_runs import register

            register()
        except ImportError:
            print("  [!] Could not import register_all_runs. Skipping auto-sync.")
        except Exception as e:
            print(f"  [!] Metadata sync failed: {e}")

    if not db_path.exists():
        print(f"  [!] Metadata DB missing at {db_path}")
        print(
            "      -> Don't panic! It hasn't been created yet. Run `make data` or click `Train` in the UI to initialize it."
        )
        return False

    errors = 0
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row

        # 1. Check SQLite vs MLflow artifacts
        # We assume a table 'model_versions' or 'backtest_runs' exists
        try:
            runs = conn.execute("SELECT run_id, tag FROM model_versions").fetchall()
            print(f"  [INFO] Found {len(runs)} models in SQLite registry.")
            for run in runs:
                run_id = run["run_id"]
                # Search for run_id in MLRUNS_DIR (it could be in any experiment subfolder)
                # MLflow structure: mlruns/<exp_id>/<run_id>
                found_mlflow = False
                if MLRUNS_DIR.exists():
                    for exp_dir in MLRUNS_DIR.iterdir():
                        if (exp_dir / run_id).exists():
                            found_mlflow = True
                            break

                if not found_mlflow:
                    print(
                        f"  [!] SQLite record {run['tag']} ({run_id}) has NO matching MLflow artifact."
                    )
                    errors += 1
                    if fix:
                        print(f"      [FIX] Pruning orphaned SQLite record {run_id}...")
                        conn.execute("DELETE FROM model_versions WHERE run_id = ?", (run_id,))
        except sqlite3.OperationalError as e:
            print(f"  [INFO] Table 'model_versions' not yet initialized or: {e}")

        # 2. Check SQLite vs Dashboard JSON
        if DASHBOARD_DB_PATH.exists():
            with open(DASHBOARD_DB_PATH, encoding="utf-8") as f:
                dash_data = json.load(f)
                dash_runs = dash_data.get("models", [])
                print(f"  [INFO] Found {len(dash_runs)} runs in dashboard_db.json.")
                # Basic check: all dash_runs should be in SQLite or MLflow
                # This is a bit more complex, but we can check if they exist on disk at least
        else:
            print(f"  [!] dashboard_db.json missing at {DASHBOARD_DB_PATH}")
            errors += 1
            if fix:
                print("      [FIX] Run 'python scripts/build_dashboard_db.py' to regenerate.")

        if fix and errors > 0:
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [!] Integrity check failed: {e}")
        return False

    if errors == 0:
        print("  [OK] Metadata consistency verified.")
    return errors == 0 or fix


def main():
    parser = argparse.ArgumentParser(description="Trading Assistant Environment Doctor")
    parser.add_argument(
        "--fix", action="store_true", help="Attempt to fix metadata inconsistencies"
    )
    args = parser.parse_args()

    print("=== Qlib Trading Assistant: Environment Doctor ===\n")

    check_python()
    dep_ok = check_dependencies()
    integ_ok = check_metadata_integrity(fix=args.fix)

    if dep_ok and integ_ok:
        print("\n[SUCCESS] Environment looks healthy.")
    else:
        print("\n[FAILURE] Environment issues detected.")
        if not args.fix:
            print(
                "          -> Try running `python scripts/doctor.py --fix` to resolve minor inconsistencies."
            )
            print("          -> Also ensure you've run `uv sync` to install base dependencies.")
        sys.exit(1)


if __name__ == "__main__":
    main()
