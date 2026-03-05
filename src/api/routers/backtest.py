import sys
import threading
from fastapi import APIRouter, HTTPException
from src.api.dependencies import get_backtest_service, get_training_service, get_job_service, PROJECT_ROOT
from src.common.paths import DASHBOARD_DB_PATH, MLRUNS_DIR

router = APIRouter(tags=["jobs"])

@router.post("/api/backtest/run")
def run_backtest(payload: dict):
    try:
        job = get_backtest_service().create_job_from_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = job["id"]
    get_job_service().create_job(job)
    t = threading.Thread(target=get_job_service().run_job, args=(job_id,), daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id}

@router.post("/api/train/run")
def run_training(payload: dict):
    try:
        job = get_training_service().create_job_from_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = job["id"]
    get_job_service().create_job(job)
    t = threading.Thread(target=get_job_service().run_job, args=(job_id,), daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id}

@router.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    if not run_id:
        raise HTTPException(status_code=400, detail="missing run_id")
    try:
        from src.dashboard.run_deletion import delete_backtest_run
        ok = delete_backtest_run(
            run_id,
            mlruns_root=MLRUNS_DIR,
            dashboard_json_path=DASHBOARD_DB_PATH,
            model_list_path=PROJECT_ROOT / "models" / "model_list.yaml",
            project_root=PROJECT_ROOT,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if ok:
        try:
            import subprocess
            subprocess.run(
                [sys.executable, "scripts/build_dashboard_db.py"],
                cwd=str(PROJECT_ROOT),
                check=False,
            )
        except Exception:
            pass
        return {"ok": True, "run_id": run_id}
    else:
        raise HTTPException(status_code=404, detail="run not found or could not be deleted")
