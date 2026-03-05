from fastapi import APIRouter, HTTPException
from src.common.paths import CONFIG_DIR

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

@router.get("/list")
def list_strategies():
    files = list(CONFIG_DIR.glob("*.yaml")) + list(CONFIG_DIR.glob("*.json"))
    return {"ok": True, "files": [f.name for f in files]}

@router.get("/content/{filename}")
def get_strategy_content(filename: str):
    cfg_path = CONFIG_DIR / filename
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    content = cfg_path.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "filename": filename, "content": content}

@router.post("/save")
def save_strategy(payload: dict):
    filename = str(payload.get("filename") or "").strip()
    content = str(payload.get("content") or "")
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")
    
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=403, detail="invalid filename")

    cfg_path = CONFIG_DIR / filename
    try:
        cfg_path.write_text(content, encoding="utf-8")
        return {"ok": True, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
