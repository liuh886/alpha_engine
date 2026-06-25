import json

from fastapi import APIRouter, HTTPException

from src.api.dependencies import get_artifact_gateway
from src.common.paths import DASHBOARD_DB_PATH

router = APIRouter(tags=["artifacts"])


@router.get("/top-bottom-analysis")
def get_top_bottom_analysis():
    """Return TOP/BOTTOM 5/10/15/20 backtest comparison for all models."""
    analysis_path = DASHBOARD_DB_PATH.parent / "top_bottom_analysis.json"
    try:
        if not analysis_path.exists():
            return {"ok": True, "models": [], "generated_at": ""}
        return json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": True, "models": [], "generated_at": ""}


@router.get("/dashboard-db")
def get_dashboard_db():
    """Return the full dashboard database for frontend comparison/display."""
    try:
        if not DASHBOARD_DB_PATH.exists():
            return {"ok": True, "models": [], "name_map": {}, "generated_at": ""}
        return json.loads(DASHBOARD_DB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/arena-leaderboard/{arena_id}")
def get_arena_leaderboard_artifact(arena_id: str):
    try:
        return get_artifact_gateway().get_arena_leaderboard(arena_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{artifact_key}")
def get_artifact_json(artifact_key: str):
    try:
        return get_artifact_gateway().get_json(artifact_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
