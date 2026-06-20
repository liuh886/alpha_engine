"""Evidence Ledger API adapter."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.api.dependencies import get_evidence_ledger

router = APIRouter(tags=["evidence"])


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
