from __future__ import annotations

from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Query
from fastapi import Path as ApiPath
from fastapi.responses import JSONResponse

from src.api.dependencies import get_model_index, get_model_service
from src.api.schemas.release_contracts import (
    IDENTIFIER_PATTERN,
    ContractAPIRoute,
    Market,
    ModelDeleteRequestV1,
    ModelPromotionRequestV1,
    error_response,
)

logger = structlog.get_logger()

router = APIRouter(tags=["models"], route_class=ContractAPIRoute)


@router.get("")
def list_models(
    limit: int = Query(100, ge=1, le=200),
    market: Market | None = Query(None),
):
    try:
        versions = get_model_index().list_versions(
            limit=limit,
            market=market.value if market else None,
        )
        return {"ok": True, "schema_version": "v1", "versions": versions}
    except Exception:
        logger.exception("model_list_failed")
        return error_response(
            status_code=500,
            error_code="API_INTERNAL_ERROR",
            message="Unable to list model artifacts",
        )


@router.post("/promote")
def promote_model(payload: ModelPromotionRequestV1):
    artifact_id = payload.artifact_id
    try:
        if get_model_index().get_version(artifact_id) is None:
            return error_response(
                status_code=404,
                error_code="MODEL_ARTIFACT_NOT_FOUND",
                message="Model artifact not found",
                details={"artifact_id": artifact_id},
            )

        result = get_model_service().promote_model(artifact_id, payload.stage.value)
        if not result.get("ok"):
            return error_response(
                status_code=409,
                error_code="MODEL_PROMOTION_CONFLICT",
                message="Model artifact cannot transition to the requested stage",
                details={
                    "artifact_id": artifact_id,
                    "stage": payload.stage.value,
                    "gate_failures": result.get("gate_failures", []),
                },
            )
        return {
            "ok": True,
            "schema_version": "v1",
            "artifact_id": artifact_id,
            "stage": payload.stage.value,
        }
    except Exception:
        logger.exception("model_promotion_failed", artifact_id=artifact_id)
        return error_response(
            status_code=500,
            error_code="API_INTERNAL_ERROR",
            message="Unable to promote model artifact",
        )


@router.post("/delete")
def delete_model(payload: ModelDeleteRequestV1):
    artifact_id = payload.artifact_id
    try:
        if get_model_index().get_version(artifact_id) is None:
            return error_response(
                status_code=404,
                error_code="MODEL_ARTIFACT_NOT_FOUND",
                message="Model artifact not found",
                details={"artifact_id": artifact_id},
            )

        if not get_model_service().delete_model(artifact_id):
            return error_response(
                status_code=409,
                error_code="MODEL_DELETE_CONFLICT",
                message="Model artifact could not be deleted",
                details={"artifact_id": artifact_id},
            )
        return {
            "ok": True,
            "schema_version": "v1",
            "artifact_id": artifact_id,
            "deleted": True,
        }
    except Exception:
        logger.exception("model_delete_failed", artifact_id=artifact_id)
        return error_response(
            status_code=500,
            error_code="API_INTERNAL_ERROR",
            message="Unable to delete model artifact",
        )


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
    from src.common.paths import ARTIFACTS_DIR, MLRUNS_DIR

    report: dict = {
        "ok": True,
        "checks": {},
        "warnings": [],
        "status": "ready",
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
            report["warnings"].append(f"Latest predictions are {pred_info['age_days']} days old.")
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

    required_checks = (
        bool(report["checks"].get("recommended_model", {}).get("exists")),
        bool(report["checks"].get("predictions", {}).get("exists")),
        bool(report["checks"].get("data", {}).get("available")),
    )
    if all(required_checks) and not report["warnings"]:
        return report

    report["ok"] = False
    report["status"] = "degraded" if any(required_checks) else "blocked"
    report["error_code"] = (
        "MODEL_HEALTH_DEGRADED" if report["status"] == "degraded" else "MODEL_HEALTH_BLOCKED"
    )
    return JSONResponse(status_code=503, content=report)


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
        from datetime import datetime

        end_date = datetime.now().strftime("%Y-%m-%d")
        df = D.features(["AAPL"], ["$close"], start_time="2026-01-01", end_time=end_date)
        if df.empty:
            return {"available": False, "reason": "Empty data returned"}

        return {"available": True, "sample_records": len(df)}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


@router.get("/{artifact_id}")
def get_model_details(
    artifact_id: str = ApiPath(
        ...,
        min_length=1,
        max_length=128,
        pattern=IDENTIFIER_PATTERN,
    ),
):
    try:
        details = get_model_service().get_model_details(artifact_id)
        return {
            "ok": True,
            "schema_version": "v1",
            "artifact_id": artifact_id,
            **details,
        }
    except ValueError:
        return error_response(
            status_code=404,
            error_code="MODEL_ARTIFACT_NOT_FOUND",
            message="Model artifact not found",
            details={"artifact_id": artifact_id},
        )
    except Exception:
        logger.exception("model_details_failed", artifact_id=artifact_id)
        return error_response(
            status_code=500,
            error_code="API_INTERNAL_ERROR",
            message="Unable to load model artifact",
        )
