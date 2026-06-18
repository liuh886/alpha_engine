"""Check for alpha decay in Active factors.

For each Active factor:
1. Compute recent IC (last 6 months)
2. Compare with historical IC
3. If recent IC < 50% of historical, mark as 'decaying'
4. If recent IC < 30% of historical, mark as 'critical_decay'
5. Update factor metadata in registry
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.common.logging import get_logger
from src.research.factor_registry import FactorRegistry, STAGE_ACTIVE, STAGE_DEPRECATED

log = get_logger(__name__)

# Decay thresholds
DECAYING_THRESHOLD = 0.50    # recent IC < 50% of historical
CRITICAL_THRESHOLD = 0.30    # recent IC < 30% of historical
RECENT_MONTHS = 6            # window for "recent" IC computation
MIN_VALIDATIONS = 5          # minimum validations required for a reliable check


def _cutoff_date(months: int) -> str:
    """Return an ISO-8601 date string for N months ago."""
    dt = datetime.now() - timedelta(days=months * 30)
    return dt.isoformat()


def _compute_ic_stats(validations: list[dict]) -> dict:
    """Compute IC statistics from a list of validation records.

    Returns dict with:
        mean_ic: average IC across all validations
        mean_icir: average ICIR across all validations
        count: number of validations with non-null IC
    """
    ics = [v["ic"] for v in validations if v.get("ic") is not None]
    icirs = [v["icir"] for v in validations if v.get("icir") is not None]

    return {
        "mean_ic": sum(ics) / len(ics) if ics else 0.0,
        "mean_icir": sum(icirs) / len(icirs) if icirs else 0.0,
        "count": len(ics),
    }


def check_factor_decay(factor_id: int, registry: FactorRegistry) -> dict:
    """Check decay status for a single factor.

    Compares recent IC (last 6 months) against historical IC.

    Returns:
        Dict with keys: factor_id, name, stage, historical_ic, recent_ic,
        decay_ratio, status, message.
    """
    factor = registry.get_factor(factor_id)
    if not factor:
        return {
            "factor_id": factor_id,
            "status": "error",
            "message": f"Factor {factor_id} not found",
        }

    validations = registry.get_validations(factor_id)

    # Separate recent vs historical validations
    cutoff = _cutoff_date(RECENT_MONTHS)
    recent_validations = [v for v in validations if v.get("validated_at", "") >= cutoff]
    historical_validations = validations  # all validations

    if len(recent_validations) < MIN_VALIDATIONS:
        return {
            "factor_id": factor_id,
            "name": factor["name"],
            "stage": factor["stage"],
            "historical_ic": None,
            "recent_ic": None,
            "decay_ratio": None,
            "status": "insufficient_data",
            "message": (
                f"Only {len(recent_validations)} recent validations "
                f"(need {MIN_VALIDATIONS}). Skipping decay check."
            ),
        }

    hist_stats = _compute_ic_stats(historical_validations)
    recent_stats = _compute_ic_stats(recent_validations)

    historical_ic = abs(hist_stats["mean_ic"])
    recent_ic = abs(recent_stats["mean_ic"])

    # Avoid division by zero
    if historical_ic < 1e-10:
        decay_ratio = 1.0
    else:
        decay_ratio = recent_ic / historical_ic

    # Determine status
    if decay_ratio < CRITICAL_THRESHOLD:
        status = "critical_decay"
        message = (
            f"CRITICAL: Recent IC ({recent_ic:.4f}) is {decay_ratio:.1%} of "
            f"historical IC ({historical_ic:.4f}). Factor may need demotion."
        )
    elif decay_ratio < DECAYING_THRESHOLD:
        status = "decaying"
        message = (
            f"WARNING: Recent IC ({recent_ic:.4f}) is {decay_ratio:.1%} of "
            f"historical IC ({historical_ic:.4f}). Factor is losing alpha."
        )
    else:
        status = "healthy"
        message = (
            f"OK: Recent IC ({recent_ic:.4f}) is {decay_ratio:.1%} of "
            f"historical IC ({historical_ic:.4f})."
        )

    return {
        "factor_id": factor_id,
        "name": factor["name"],
        "stage": factor["stage"],
        "historical_ic": round(historical_ic, 6),
        "recent_ic": round(recent_ic, 6),
        "decay_ratio": round(decay_ratio, 4),
        "status": status,
        "message": message,
    }


def check_all_active_factors() -> list[dict]:
    """Check decay for all Active factors.

    Returns:
        List of decay check result dicts, one per Active factor.
    """
    registry = FactorRegistry()
    active_factors = registry.list_factors(stage=STAGE_ACTIVE)

    if not active_factors:
        log.info("no_active_factors_found")
        return []

    log.info("checking_decay", n_active=len(active_factors))
    results: list[dict] = []

    for factor in active_factors:
        result = check_factor_decay(factor["id"], registry)
        results.append(result)

        # Log based on status
        if result["status"] == "critical_decay":
            log.warning(
                "critical_decay_detected",
                factor_id=result["factor_id"],
                name=result["name"],
                decay_ratio=result["decay_ratio"],
            )
        elif result["status"] == "decaying":
            log.warning(
                "decay_detected",
                factor_id=result["factor_id"],
                name=result["name"],
                decay_ratio=result["decay_ratio"],
            )
        elif result["status"] == "healthy":
            log.info(
                "factor_healthy",
                factor_id=result["factor_id"],
                name=result["name"],
                decay_ratio=result["decay_ratio"],
            )

    return results


def update_decay_metadata(results: list[dict]) -> int:
    """Update factor metadata based on decay check results.

    Records a validation with decay info for factors showing decay.
    Does NOT auto-demote; that requires human review.

    Returns:
        Number of factors with recorded decay metadata.
    """
    registry = FactorRegistry()
    updated = 0

    for result in results:
        if result["status"] in ("decaying", "critical_decay"):
            factor_id = result["factor_id"]
            # Record a validation noting the decay status
            # This creates an audit trail in the validation history
            metrics = {
                "ic": result["recent_ic"],
                "icir": 0.0,  # decay check doesn't recompute ICIR
            }
            registry.record_validation(factor_id, "decay_check", metrics)
            updated += 1
            log.info(
                "decay_metadata_recorded",
                factor_id=factor_id,
                name=result["name"],
                status=result["status"],
            )

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Check for alpha decay in Active factors")
    parser.add_argument(
        "--update-metadata",
        action="store_true",
        help="Record decay status in factor validation history",
    )
    parser.add_argument(
        "--market",
        type=str,
        default=None,
        help="Market to check (currently unused, checks all Active factors)",
    )
    args = parser.parse_args()

    print("=== Factor Decay Check ===")
    results = check_all_active_factors()

    if not results:
        print("No Active factors to check.")
        return 0

    # Print summary
    n_healthy = sum(1 for r in results if r["status"] == "healthy")
    n_decaying = sum(1 for r in results if r["status"] == "decaying")
    n_critical = sum(1 for r in results if r["status"] == "critical_decay")
    n_insufficient = sum(1 for r in results if r["status"] == "insufficient_data")

    print(f"\nResults: {len(results)} factors checked")
    print(f"  Healthy:          {n_healthy}")
    print(f"  Decaying:         {n_decaying}")
    print(f"  Critical decay:   {n_critical}")
    print(f"  Insufficient data: {n_insufficient}")

    # Print details for non-healthy factors
    for r in results:
        if r["status"] not in ("healthy", "insufficient_data"):
            print(f"\n  [{r['status'].upper()}] {r['name']} (id={r['factor_id']})")
            print(f"    {r['message']}")

    # Optionally update metadata
    if args.update_metadata:
        n_updated = update_decay_metadata(results)
        print(f"\nRecorded decay metadata for {n_updated} factors.")

    # Exit code: 0 if no critical, 1 if any critical
    return 1 if n_critical > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
