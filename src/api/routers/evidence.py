"""Evidence Ledger API adapter."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import PROJECT_ROOT, get_evidence_ledger

router = APIRouter(tags=["evidence"])
SIGNAL_DISCOVERY_DIR = PROJECT_ROOT / "artifacts" / "evidence" / "10d_signal_discovery"


@router.get("/signal-discovery/latest")
def get_latest_signal_discovery(
    market: str = Query("us", pattern="^(us|cn)$"),
):
    """Return the latest fixed-10D signal-discovery comparison evidence."""
    report_path = SIGNAL_DISCOVERY_DIR / f"{market}_signal_discovery_report.json"
    if not report_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "signal_discovery_report_missing",
                "market": market,
                "path": str(report_path.relative_to(PROJECT_ROOT)),
            },
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "signal_discovery_report_invalid", "message": str(exc)},
        ) from exc

    required = {"schema_version", "market", "candidates", "summary"}
    missing = sorted(required - set(report))
    if missing:
        raise HTTPException(
            status_code=500,
            detail={"code": "signal_discovery_schema_invalid", "missing": missing},
        )
    return {
        "ok": True,
        "report": report,
        "artifact_path": str(report_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


@router.get("/{subject_type}/{subject_id}")
def get_evidence_bundle(
    subject_type: str,
    subject_id: str,
    market: str | None = Query(None, description="Optional market filter"),
):
    """Return a canonical evidence bundle for a research subject."""
    bundle = get_evidence_ledger().build_bundle(
        subject_type=subject_type,
        subject_id=subject_id,
        market=market,
    )
    return {"ok": True, "bundle": bundle.to_dict()}
