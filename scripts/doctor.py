#!/usr/bin/env python3
"""Check the local Alpha Engine research environment."""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.common.paths import ARTIFACTS_DIR, DASHBOARD_DB_PATH, MLRUNS_DIR

REQUIRED_DEPENDENCIES = ("qlib", "pandas", "numpy", "lightgbm", "fire", "pydantic")


def check_python() -> None:
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")


def check_dependencies() -> bool:
    missing: list[str] = []
    print("\nChecking dependencies...")
    for dependency in REQUIRED_DEPENDENCIES:
        try:
            module = importlib.import_module(dependency)
            version = getattr(module, "__version__", "unknown")
            print(f"  [OK] {dependency} ({version})")
        except ImportError:
            missing.append(dependency)

    try:
        from qlib.workflow import R  # noqa: F401

        print("  [OK] Qlib C++ extensions (workflow/record_temp)")
    except ImportError as exc:
        print(f"  [!] Qlib binary extension is unavailable or incompatible: {exc}")
        print("      -> Run `uv sync --frozen --extra dev` and retry.")
        missing.append("qlib-bin")

    if missing:
        print(f"  [!] Missing dependencies: {', '.join(missing)}")
    return not missing


def check_metadata_integrity() -> bool:
    print("\nChecking metadata integrity (SQLite, MLflow, exported JSON)...")
    db_path = ARTIFACTS_DIR / "metadata" / "metadata.db"

    if not db_path.exists():
        print(f"  [!] Metadata DB missing at {db_path}")
        print("      -> Run the governed data or research entrypoint that owns this artifact.")
        return False

    errors = 0
    try:
        with sqlite3.connect(db_path, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            try:
                runs = connection.execute("SELECT run_id, tag FROM model_versions").fetchall()
                print(f"  [INFO] Found {len(runs)} models in the SQLite registry.")
                for run in runs:
                    run_id = run["run_id"]
                    found_mlflow = MLRUNS_DIR.exists() and any(
                        (experiment_dir / run_id).exists()
                        for experiment_dir in MLRUNS_DIR.iterdir()
                    )
                    if found_mlflow:
                        continue
                    print(f"  [!] SQLite record {run['tag']} ({run_id}) has no MLflow artifact.")
                    errors += 1
            except sqlite3.OperationalError as exc:
                print(f"  [INFO] model_versions is not initialized: {exc}")

            if DASHBOARD_DB_PATH.exists():
                payload = json.loads(DASHBOARD_DB_PATH.read_text(encoding="utf-8"))
                print(f"  [INFO] Found {len(payload.get('models', []))} exported model records.")
            else:
                print(f"  [!] Exported dashboard evidence missing at {DASHBOARD_DB_PATH}")
                errors += 1
    except Exception as exc:
        print(f"  [!] Integrity check failed: {exc}")
        return False

    if errors == 0:
        print("  [OK] Metadata consistency verified.")
    return errors == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print("=== Alpha Engine Research Environment Doctor ===\n")
    dependencies_ok = check_dependencies()
    check_python()
    metadata_ok = check_metadata_integrity()

    if dependencies_ok and metadata_ok:
        print("\n[SUCCESS] Environment looks healthy.")
        return 0

    print("\n[FAILURE] Environment issues detected.")
    print("          -> Reconcile missing artifacts through their governed source workflow.")
    print("          -> Run `uv sync --frozen --extra dev` to restore locked dependencies.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
