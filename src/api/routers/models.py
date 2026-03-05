from fastapi import APIRouter, HTTPException, Query
from src.api.dependencies import get_model_service, get_model_index
import threading

router = APIRouter(prefix="/api/models", tags=["models"])

@router.get("")
def list_models(limit: int = Query(100), market: str | None = None):
    try:
        limit = int(limit)
    except Exception:
        limit = 100
    if limit <= 0:
        limit = 100
    versions = get_model_index().list_versions(limit=limit, market=market)
    return {"ok": True, "versions": versions}

@router.post("/promote")
def promote_model(payload: dict):
    version_id = str(payload.get("version_id") or "").strip()
    stage = str(payload.get("stage") or "RECOMMENDED").strip()
    if not version_id:
        raise HTTPException(status_code=400, detail="missing version_id")
    ok = get_model_service().promote_model(version_id, stage)
    return {"ok": ok}

@router.post("/delete")
def delete_model(payload: dict):
    version_id = str(payload.get("version_id") or "").strip()
    if not version_id:
        raise HTTPException(status_code=400, detail="missing version_id")
    ok = get_model_service().delete_model(version_id)
    return {"ok": ok}
