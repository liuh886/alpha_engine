"""Factor IC Analysis API endpoints.

Provides endpoints for computing and retrieving Information Coefficient
analysis for Alpha158 factors.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src.common.logging import get_logger
from src.common.paths import ARTIFACTS_DIR

log = get_logger(__name__)

router = APIRouter(prefix="/factors", tags=["factors"])


def _cache_dir() -> Path:
    d = ARTIFACTS_DIR / "factor_ic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(market: str, start: str, end: str) -> Path:
    return _cache_dir() / f"{market}_{start}_{end}.json"


def _load_cached_report(market: str, start: str, end: str) -> dict | None:
    path = _cache_path(market, start, end)
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.debug("Failed to read IC cache", path=str(path), exc_info=True)
    return None


@router.get("/ic")
async def get_factor_ic(
    market: str = Query("us", pattern="^(us|cn)$"),
    start: str = Query("2021-01-01"),
    end: str = Query("latest"),
    forward_days: int = Query(10, ge=1, le=60),
    freq: str = Query("M", pattern="^(M|W)$"),
) -> dict:
    """Full IC report for all factors.

    Results are cached to artifacts/factor_ic/ to avoid recomputation.
    """
    from src.research.factor_analysis import compute_factor_ic

    # Check cache first
    end_key = end if end and end != "latest" else "latest"
    cached = _load_cached_report(market, start, end_key)
    if cached:
        return {"ok": True, "report": cached, "cached": True}

    try:
        report = compute_factor_ic(
            market=market,
            start_date=start,
            end_date=end,
            forward_days=forward_days,
            freq=freq,
            use_cache=True,
        )
        return {"ok": True, "report": report.to_dict(), "cached": False}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Factor IC computation failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"IC computation failed: {e}")


@router.get("/ic/top")
async def get_top_factors(
    market: str = Query("us", pattern="^(us|cn)$"),
    n: int = Query(20, ge=1, le=100),
    start: str = Query("2021-01-01"),
    end: str = Query("latest"),
) -> dict:
    """Top N factors by |rank_ic|.

    Returns from cache if available; otherwise computes on-the-fly.
    """
    from src.research.factor_analysis import compute_factor_ic

    end_key = end if end and end != "latest" else "latest"

    # Try cache first
    cached = _load_cached_report(market, start, end_key)
    if cached:
        top = cached.get("top_factors", [])[:n]
        # If we need more than cached top 20, look at full factor list
        if len(top) < n:
            all_factors = cached.get("factors", [])
            top = all_factors[:n]
        return {
            "ok": True,
            "market": market,
            "n": len(top),
            "top_factors": top,
            "cached": True,
        }

    # Compute fresh
    try:
        report = compute_factor_ic(
            market=market,
            start_date=start,
            end_date=end,
            use_cache=True,
        )
        top = [f.to_dict() for f in report.top_factors[:n]]
        if len(top) < n:
            top = [f.to_dict() for f in report.factors[:n]]
        return {
            "ok": True,
            "market": market,
            "n": len(top),
            "top_factors": top,
            "cached": False,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Top factors computation failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Computation failed: {e}")


@router.get("/decay")
async def get_factor_decay(
    market: str = Query("us", pattern="^(us|cn)$"),
    factor: str = Query(..., min_length=1),
    max_lag: int = Query(20, ge=1, le=60),
    start: str = Query("2021-01-01"),
    end: str = Query("latest"),
) -> dict:
    """IC decay curve for a specific factor.

    Returns IC at each forward-return horizon from 1 to max_lag days.
    """
    from src.research.factor_analysis import compute_factor_decay

    try:
        decay_points = compute_factor_decay(
            market=market,
            factor_name=factor,
            max_lag=max_lag,
            start_date=start,
            end_date=end,
        )
        return {
            "ok": True,
            "factor": factor,
            "market": market,
            "decay": [dp.to_dict() for dp in decay_points],
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Factor decay computation failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Decay computation failed: {e}")
