import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex
from src.assistant.services.backtest_service import BacktestService


def repair_all_backtests():
    db_path = resolve_metadata_db_path(project_root)
    model_index = ModelRegistryIndex(db_path=db_path)

    svc = BacktestService(
        project_root=project_root,
        python_exe=sys.executable,
        dashboard_db_path=project_root / "artifacts" / "dashboard" / "dashboard_db.json",
    )

    versions = model_index.list_versions(limit=200)
    print(f"Found {len(versions)} models in index.")

    # Load model_list.yaml to resolve paths
    model_list_path = project_root / "artifacts" / "models" / "model_list.yaml"
    with open(model_list_path) as f:
        mlist_data = yaml.safe_load(f) or {"models": []}

    path_map = {m["id"]: m.get("path") for m in mlist_data["models"]}

    mlruns_dirs = [project_root / "mlruns", project_root / "artifacts" / "mlruns"]

    for v in versions:
        model_id = v["id"]
        market = v["market"]
        run_id = v.get("run_id")

        # Check if we already have the backtest report
        has_report = False
        if run_id:
            for m_dir in mlruns_dirs:
                if not m_dir.exists():
                    continue
                # Search for report_normal_1day.pkl in artifacts
                matches = list(m_dir.rglob(f"{run_id}/artifacts/report_normal_1day.pkl"))
                if matches:
                    has_report = True
                    break

        if has_report:
            print(f"Skipping {model_id}: report already exists for run_id {run_id}")
            continue

        model_path = path_map.get(model_id)
        if not model_path:
            model_path = v.get("path")

        if not model_path:
            print(f"Skipping {model_id}: no path found.")
            continue

        if not Path(model_path).is_absolute():
            # Try a few common locations
            cand1 = project_root / "artifacts" / model_path
            cand2 = project_root / model_path
            if cand1.exists():
                model_path = str(cand1)
            elif cand2.exists():
                model_path = str(cand2)
            else:
                print(f"Skipping {model_id}: model file not found at {model_path}")
                continue

        print("\n=============================================")
        print(f"Processing {model_id} ({market})")
        print(f"Model path: {model_path}")

        try:
            job = svc.create_job_from_payload(
                {
                    "market": market,
                    "mode": "rebacktest",
                    "model_path": model_path,
                    "start": "2025-01-01",
                    "end": "latest",
                    "tag": v.get("tag") or v.get("name"),
                }
            )

            cmd = job["commands"][0]
            print("Running backtest...")

            result = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True)

            # Parse new run_id
            match = re.search(r"Backtest run_id: ([a-f0-9]{32})", result.stdout)
            if match:
                new_run_id = match.group(1)
                print(f"[OK] New run_id: {new_run_id}")

                # Update ModelRegistryIndex
                v["run_id"] = new_run_id
                if v.get("payload_json"):
                    payload = json.loads(v["payload_json"])
                    payload["run_id"] = new_run_id
                    v["payload_json"] = json.dumps(payload)

                model_index.upsert_entry(v)

                # Update model_list.yaml
                for m in mlist_data["models"]:
                    if m["id"] == model_id:
                        m["run_id"] = new_run_id
                        break
                # Save after each success to be safe
                with open(model_list_path, "w") as f:
                    yaml.dump(mlist_data, f, sort_keys=False)
            else:
                print(
                    f"[WARN] Could not find run_id for {model_id}. Output length: {len(result.stdout)}"
                )
                if "Error" in result.stdout or "Exception" in result.stdout:
                    print("Potential error in output detected.")

        except Exception as e:
            print(f"[ERROR] Failed to process {model_id}: {e}")

    print("\nRebuilding dashboard DB one last time...")
    subprocess.run(
        [sys.executable, "scripts/build_dashboard_db.py"], cwd=str(project_root), check=True
    )
    print("Done!")


if __name__ == "__main__":
    repair_all_backtests()
