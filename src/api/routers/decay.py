"""Factor Decay Monitor API — Track factor effectiveness over time.

Endpoints:
    GET  /decay/check           — Check all Active factors for decay
    GET  /decay/factor/{name}   — Check a specific factor
    POST /decay/apply           — Apply status changes
"""

from __future__ import annotations

import pandas as pd
import structlog
from fastapi import APIRouter, HTTPException, Query

logger = structlog.get_logger()

router = APIRouter(prefix="/decay", tags=["decay"])


@router.get("/check")
def check_decay(
    market: str = Query("cn", description="Market to check"),
    lookback_days: int = Query(365, description="Days of history to analyze"),
):
    """Check all Active factors for decay.

    Returns decay status for each Active factor:
    - healthy: No decay detected
    - watch: Early warning signs
    - degraded: Significant decay
    - downgrade: Should be demoted
    """
    from src.research.decay_monitor import DecayMonitor

    monitor = DecayMonitor(market=market, lookback_days=lookback_days)
    reports = monitor.check_all_active_factors()
    summary = monitor.generate_report(reports)

    return {"ok": True, **summary}


@router.get("/factor/{factor_name}")
def check_factor_decay(
    factor_name: str,
    market: str = Query("cn", description="Market"),
):
    """Check a specific factor for decay."""
    from src.research.decay_monitor import DecayMonitor
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    factor = registry.get_factor(factor_name)
    if not factor:
        raise HTTPException(status_code=404, detail=f"Factor '{factor_name}' not found")

    monitor = DecayMonitor(market=market)

    # Load per-factor IC from validation records
    ic_history = pd.Series(dtype=float)
    validations = registry.get_validations(factor["id"])
    ic_records = [
        (v["validated_at"][:10], float(v["ic"]))
        for v in validations
        if v.get("ic") is not None and v.get("market", "").lower() == market.lower()
    ]
    if ic_records:
        ic_records.sort(key=lambda x: x[0])
        dates, ics = zip(*ic_records)
        ic_history = pd.Series(ics, index=pd.to_datetime(dates))

    report = monitor.check_factor(factor_name, ic_history)

    return {"ok": True, "report": report.to_dict()}


@router.post("/apply")
def apply_decay_changes(
    market: str = Query("cn", description="Market"),
    dry_run: bool = Query(True, description="If true, only report changes without applying"),
):
    """Apply status changes to factors based on decay analysis.

    Set dry_run=false to actually apply changes.
    """
    from src.research.decay_monitor import DecayMonitor

    monitor = DecayMonitor(market=market)
    reports = monitor.check_all_active_factors()

    if dry_run:
        summary = monitor.generate_report(reports)
        return {
            "ok": True,
            "dry_run": True,
            "changes_pending": len(summary["recommendations"]),
            **summary,
        }

    # Apply changes
    changes = monitor.apply_status_changes(reports)
    summary = monitor.generate_report(reports)

    return {
        "ok": True,
        "dry_run": False,
        "changes_applied": changes,
        **summary,
    }
