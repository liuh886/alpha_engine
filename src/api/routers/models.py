from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
import structlog

from src.api.dependencies import get_model_index, get_model_service

logger = structlog.get_logger()

router = APIRouter(tags=["models"])


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


@router.get("/{version_id}")
def get_model_details(version_id: str):
    try:
        details = get_model_service().get_model_details(version_id)
        return {"ok": True, **details}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/promote")
def promote_model(payload: dict):
    version_id = str(payload.get("version_id") or "").strip()
    stage = str(payload.get("stage") or "RECOMMENDED").strip()
    if not version_id:
        raise HTTPException(status_code=400, detail="missing version_id")
    result = get_model_service().promote_model(version_id, stage)
    if not result["ok"] and result.get("gate_failures"):
        return {"ok": False, "gate_failures": result["gate_failures"]}
    return {"ok": result["ok"]}


@router.post("/delete")
def delete_model(payload: dict):
    version_id = str(payload.get("version_id") or "").strip()
    if not version_id:
        raise HTTPException(status_code=400, detail="missing version_id")
    ok = get_model_service().delete_model(version_id)
    return {"ok": ok}


# ------------------------------------------------------------------
# P3-2: Model health check
# ------------------------------------------------------------------


@router.get("/health")
def model_health_check():
    """Check model health: file existence, prediction freshness, registry status.

    Returns a diagnostic report for the recommended model including:
    - Whether the model artifact file exists
    - How old the latest prediction is
    - Whether the model registry has a RECOMMENDED entry
    - Prediction coverage (how many stocks have scores)
    """
    from src.common.paths import MLRUNS_DIR, ARTIFACTS_DIR

    report: dict = {
        "ok": True,
        "checks": {},
        "warnings": [],
        "status": "healthy",
    }

    # 1. Check model registry for RECOMMENDED entry
    try:
        model_index = get_model_index()
        with model_index._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_versions WHERE description LIKE '%RECOMMENDED%' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

        if row:
            rec = {k: row[k] for k in row.keys()}
            report["checks"]["recommended_model"] = {
                "exists": True,
                "run_id": rec.get("run_id"),
                "market": rec.get("market"),
                "created_at": rec.get("created_at"),
            }

            # Check age
            created = rec.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created)
                    age_days = (datetime.now() - created_dt).days
                    report["checks"]["recommended_model"]["age_days"] = age_days
                    if age_days > 14:
                        report["warnings"].append(
                            f"Recommended model is {age_days} days old. Consider retraining."
                        )
                except Exception:
                    pass
        else:
            report["checks"]["recommended_model"] = {"exists": False}
            report["warnings"].append("No RECOMMENDED model found in registry.")

    except Exception as exc:
        report["checks"]["recommended_model"] = {"exists": False, "error": str(exc)}

    # 2. Check prediction file freshness
    try:
        pred_info = _check_prediction_freshness(MLRUNS_DIR, ARTIFACTS_DIR)
        report["checks"]["predictions"] = pred_info
        if pred_info.get("age_days") is not None and pred_info["age_days"] > 7:
            report["warnings"].append(
                f"Latest predictions are {pred_info['age_days']} days old."
            )
        if not pred_info.get("exists"):
            report["warnings"].append("No prediction files found.")
    except Exception as exc:
        report["checks"]["predictions"] = {"exists": False, "error": str(exc)}

    # 3. Check Qlib data availability
    try:
        data_info = _check_qlib_data()
        report["checks"]["data"] = data_info
        if not data_info.get("available"):
            report["warnings"].append("Qlib data not available.")
    except Exception as exc:
        report["checks"]["data"] = {"available": False, "error": str(exc)}

    # Determine overall status
    if report["warnings"]:
        report["status"] = "degraded" if len(report["warnings"]) <= 2 else "unhealthy"

    return report


def _check_prediction_freshness(mlruns_dir: Path, artifacts_dir: Path) -> dict:
    """Find the latest pred.pkl and report its age."""
    import pickle

    best_path = None
    best_mtime = 0.0

    for search_dir in [mlruns_dir, artifacts_dir]:
        if not search_dir.exists():
            continue
        for pred_file in search_dir.rglob("pred.pkl"):
            mt = pred_file.stat().st_mtime
            if mt > best_mtime:
                best_mtime = mt
                best_path = pred_file

    if best_path is None:
        return {"exists": False}

    try:
        with best_path.open("rb") as f:
            pred_df = pickle.load(f)

        age_days = (datetime.now().timestamp() - best_mtime) / 86400
        coverage = 0
        if hasattr(pred_df, "index"):
            if hasattr(pred_df.index, "get_level_values"):
                try:
                    instruments = pred_df.index.get_level_values("instrument").unique()
                    coverage = len(instruments)
                except Exception:
                    pass
            else:
                coverage = len(pred_df.index)

        return {
            "exists": True,
            "path": str(best_path),
            "age_days": round(age_days, 1),
            "coverage": coverage,
        }
    except Exception as exc:
        return {"exists": True, "path": str(best_path), "error": str(exc)}


def _check_qlib_data() -> dict:
    """Check if Qlib data is accessible."""
    try:
        from qlib.data import D
        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

        safe_qlib_init(build_qlib_init_cfg({}, market="us"))

        # Try a simple data fetch
        df = D.features(["AAPL"], ["$close"], start_time="2026-01-01", end_time="2026-06-17")
        if df.empty:
            return {"available": False, "reason": "Empty data returned"}

        return {"available": True, "sample_records": len(df)}
    except Exception as exc:
        return {"available": False, "error": str(exc)}
