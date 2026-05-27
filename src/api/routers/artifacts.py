from fastapi import APIRouter, HTTPException

from src.api.dependencies import get_artifact_gateway

router = APIRouter(tags=["artifacts"])


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
