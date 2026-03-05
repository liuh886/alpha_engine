import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex
from src.assistant.services.backtest_service import BacktestService


def run_all_rebacktests():
    db_path = resolve_metadata_db_path(project_root)
    model_index = ModelRegistryIndex(db_path=db_path)
    
    svc = BacktestService(
        project_root=project_root,
        python_exe=sys.executable,
        dashboard_db_path=project_root / "artifacts" / "dashboard" / "dashboard_db.json"
    )
    
    versions = model_index.list_versions(limit=100)
    print(f"Found {len(versions)} models to re-backtest.")
    for v in versions:
        run_id = v.get("run_id")
        market = v.get("market")
        if not run_id or not market:
            continue
            
        print("\n=============================================")
        print(f"Re-backtesting {run_id} ({market})")
        print("=============================================")
        
        try:
            job = svc.create_job_from_payload({
                "market": market,
                "mode": "rebacktest",
                "run_id": run_id,
                "start": "2025-01-01",
                "end": "latest",
                "tag": v.get("tag") or v.get("name")
            })
            
            # Run it synchronously for this script
            cmd = job["commands"][0]
            subprocess.run(cmd, cwd=str(project_root), check=True)
            print(f"[OK] Successfully re-backtested {run_id}")
            
            # Fetch new metrics to update the registry index
            # This happens automatically during rebacktest in orchestrator actually!
            
        except Exception as e:
            print(f"[ERROR] Failed to re-backtest {run_id}: {e}")

if __name__ == "__main__":
    run_all_rebacktests()
    
    print("\nRebuilding dashboard_db.json...")
    subprocess.run([sys.executable, "scripts/build_dashboard_db.py"], cwd=str(project_root), check=True)
    print("Done!")
