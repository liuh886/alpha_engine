import threading

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import (
    get_backtest_service,
    get_curve_index,
    get_job_service,
    get_run_index,
    get_training_service,
)

router = APIRouter(tags=["backtest"])


@router.get("/")
def list_backtests(market: str = Query(None), limit: int = Query(50)):
    """
    Returns a list of backtest runs with core metrics.
    Used by the Arena view and Dashboard lists.
    """
    runs = get_run_index().list_runs(market=market, limit=limit)
    # Map to frontend expected format
    formatted = []
    for r in runs:
        formatted.append(
            {
                "id": r["id"],
                "tag": r["name"],
                "market": r["market"],
                "date": r["date"],
                "annual_return": r.get("annual_return") or 0.0,
                "sharpe": r.get("sharpe") or 0.0,
                "max_drawdown": r.get("max_drawdown") or 0.0,
                "strategy_name": r.get("params", {}).get("model_tag") or "AlphaStrategy",
            }
        )
    return {"ok": True, "runs": formatted}


@router.get("/curve")
def get_backtest_curve(run_id: str, limit: int = Query(2000)):
    """
    Returns the equity curve (NAV, Drawdown) for a specific backtest run.
    """
    if not run_id:
        raise HTTPException(status_code=400, detail="missing run_id")

    curve = get_curve_index().list_curve(run_id, limit=limit)
    if not curve:
        # Fallback: check if the run exists but curve hasn't been cached
        run = get_run_index().get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return {"ok": True, "curve": [], "message": "Curve data not yet indexed."}

    return {"ok": True, "curve": curve, "run_id": run_id}


@router.get("/compare")
def compare_backtests(run_ids: str = Query(...)):
    """
    Returns multiple equity curves for side-by-side comparison.
    run_ids should be comma-separated.
    """
    ids = [rid.strip() for rid in run_ids.split(",") if rid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="at least one run_id is required")

    results = {}
    for rid in ids:
        curve = get_curve_index().list_curve(rid)
        run = get_run_index().get_run(rid)
        results[rid] = {
            "tag": run.get("tag") if run else "Unknown",
            "market": run.get("market") if run else "N/A",
            "curve": curve,
        }

    return {"ok": True, "comparisons": results}


@router.get("/{run_id}/attribution")
def get_profit_attribution(run_id: str):
    """
    Returns real profit attribution data from Qlib artifacts via BacktestService.
    """
    try:
        attr = get_backtest_service().get_profit_attribution(run_id)
        return {"ok": True, "run_id": run_id, "attribution": attr}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{run_id}/ledger")
def get_trading_ledger(run_id: str):
    """
    Returns the real execution ledger (Holdings & Trades) from Qlib artifacts.
    """
    try:
        ledger = get_backtest_service().get_trading_ledger(run_id)
        return {"ok": True, "run_id": run_id, **ledger}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/run")
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


@router.post("/train/run")
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


@router.delete("/runs/{run_id}")
def delete_run(run_id: str):
    if not run_id:
        raise HTTPException(status_code=400, detail="missing run_id")
    
    ok = get_backtest_service().delete_run(run_id)
    if ok:
        return {"ok": True, "run_id": run_id}
    else:
        raise HTTPException(status_code=404, detail="run not found or could not be deleted")
