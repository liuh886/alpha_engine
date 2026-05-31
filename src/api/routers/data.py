from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import (
    get_asset_inspection_service,
    get_data_service,
    get_job_coordinator,
    get_quality_index,
    get_snapshot_index,
)
from src.common.paths import DASHBOARD_DB_PATH

router = APIRouter(tags=["data"])


@router.post("/update")
def trigger_data_update(payload: dict):
    try:
        job = get_data_service().create_update_job_from_payload(payload)
        return get_job_coordinator().submit_response(job)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/instruments")
def get_instruments(market: str = Query("us")):
    instruments = get_data_service().get_instruments(market=market)
    return {"ok": True, "market": market, "instruments": instruments}


@router.get("/status")
def get_data_status():
    status = get_data_service().get_data_status(
        dashboard_db_path=Path(DASHBOARD_DB_PATH),
        snapshot_index=get_snapshot_index(),
        quality_index=get_quality_index(),
    )
    return {"ok": True, "data": status}


@router.get("/snapshots/latest")
def get_latest_snapshot(dataset_key: str = "watchlist", freq: str = "day"):
    snap = get_snapshot_index().get_latest(dataset_key=dataset_key, freq=freq)
    if not snap:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return {"ok": True, "snapshot": snap}


@router.get("/quality/latest")
def get_latest_quality(dataset_key: str = "watchlist", freq: str = "day", market: str = "all"):
    rep = get_quality_index().get_latest(dataset_key=dataset_key, freq=freq, market=market)
    if not rep:
        raise HTTPException(status_code=404, detail="quality report not found")
    return {"ok": True, "quality": rep}


@router.get("/stock/{symbol}")
def get_stock_data(symbol: str):
    try:
        return get_asset_inspection_service().inspect(symbol)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/completeness")
def get_data_completeness(
    market: str = Query("us"),
    feature: str = Query("close"),
):
    """Return a completeness/value matrix for the given market and feature.

    For feature=close, returns 1.0 (data present) or null (missing).
    For other features (volume, amount, etc), returns actual values or null.
    """
    from src.assistant.services.data_service import AVAILABLE_FEATURES

    if feature not in AVAILABLE_FEATURES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown feature '{feature}'. Available: {AVAILABLE_FEATURES}",
        )
    result = get_data_service().get_completeness_matrix(market=market, feature=feature)
    return {"ok": True, "data": result}


@router.get("/features")
def list_available_features():
    """Return the list of features available for the completeness heatmap."""
    from src.assistant.services.data_service import AVAILABLE_FEATURES
    return {"ok": True, "features": AVAILABLE_FEATURES}
