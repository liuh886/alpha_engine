"""Factor IC Analysis API endpoints.

Provides endpoints for computing and retrieving Information Coefficient
analysis for Alpha158 factors.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.common.dates import default_end_date
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


# ---------------------------------------------------------------------------
# Batch factor scanning
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    """Request body for POST /factors/scan."""

    market: str = Field("us", pattern="^(us|cn)$")
    start_date: str = Field("2021-01-01")
    end_date: str = Field(default_factory=default_end_date)
    train_end: str | None = Field(
        None,
        description=(
            "If provided, IC/quintile metrics are computed only on data after "
            "this date (out-of-sample). Omit for in-sample evaluation."
        ),
    )
    factor_pool: list[dict] | None = Field(
        None,
        description=(
            "Optional custom factor pool. Each entry needs 'name', 'expression', "
            "and optionally 'category'. Omit to use the default 16-factor pool."
        ),
    )
    gates: dict | None = Field(
        None,
        description="Override default gate thresholds (min_icir, min_t_stat, etc.).",
    )
    max_workers: int = Field(4, ge=1, le=16)
    auto_register: bool = Field(
        False,
        description="If true, factors that pass gates are registered in the FactorRegistry.",
    )


@router.post("/scan")
async def scan_factors(body: ScanRequest) -> dict:
    """Batch-scan a pool of factor expressions against validation gates.

    Accepts a custom factor pool or uses the built-in default pool of 16
    classic alpha factors (momentum, volatility, volume, mean-reversion).
    Returns a ScanReport ranked by |ICIR| descending.
    """
    from src.research.factor_scanner import DEFAULT_FACTOR_POOL, scan_factor_pool

    factor_pool = body.factor_pool if body.factor_pool else DEFAULT_FACTOR_POOL

    try:
        report = scan_factor_pool(
            factor_pool=factor_pool,
            market=body.market,
            start_date=body.start_date,
            end_date=body.end_date,
            train_end=body.train_end,
            gates=body.gates,
            max_workers=body.max_workers,
            auto_register=body.auto_register,
        )
        return {"ok": True, "report": report.to_dict()}
    except Exception as e:
        log.error("Factor scan failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Factor scan failed: {e}")


# ---------------------------------------------------------------------------
# Factor return attribution
# ---------------------------------------------------------------------------


class AttributionRequest(BaseModel):
    """Request body for POST /factors/attribute."""

    market: str = Field("us", pattern="^(us|cn)$")
    start_date: str = Field("2021-01-01")
    end_date: str = Field(default_factory=default_end_date)
    model_version_id: str | None = Field(
        None,
        description="Exact ModelVersion ID to bind attribution to. Resolves the model's "
        "DataSnapshot, predictions, and feature set for reproducible attribution.",
    )
    data_snapshot_id: str | None = Field(
        None,
        description="DataSnapshot ID for attribution. If model_version_id is also "
        "provided, it takes precedence and the snapshot is resolved from the model.",
    )
    strategy_config: str | None = Field(
        None,
        description="Deprecated: use model_version_id instead. "
        "Path to strategy YAML config or model ID string.",
    )
    factor_ids: list[int] | None = Field(
        None,
        description="Specific factor IDs to attribute. Omit to use all Active factors.",
    )
    min_observations: int = Field(
        12,
        ge=3,
        le=120,
        description="Minimum number of monthly observations required for valid "
        "attribution. Attribution fails closed (returns empty report) when the "
        "common period count is below this threshold.",
    )
    regularization: str | None = Field(
        None,
        pattern="^(ridge|none)$",
        description="Regularization method for the factor model. 'ridge' applies L2 "
        "penalty (helpful when factors are collinear). Defaults to unregularized OLS.",
    )


@router.post("/attribute")
async def attribute_factor_returns(body: AttributionRequest) -> dict:
    """Run factor return attribution analysis.

    Uses a cross-sectional factor model (OLS or ridge-regularized) to decompose
    portfolio returns into per-factor return and risk contributions. When
    ``model_version_id`` is provided, attribution is bound to the model's exact
    DataSnapshot, predictions, and feature set — changing the selected model
    changes the bound evidence or fails closed with a visible reason.

    Returns an AttributionReport with per-factor exposures, IC values,
    return/risk breakdowns, overall model fit (R-squared), and observation
    metadata (count, window, methodology).
    """
    from src.research.factor_attribution import attribute_returns

    # Resolve model identity: model_version_id takes precedence
    model_version_id = body.model_version_id
    data_snapshot_id = body.data_snapshot_id

    if model_version_id:
        try:
            from src.assistant.metadata_db import resolve_metadata_db_path
            from src.assistant.model_registry_index import ModelRegistryIndex
            from src.common import paths

            db_path = resolve_metadata_db_path(paths.get_artifacts_dir())
            index = ModelRegistryIndex(db_path=db_path)
            entry = index.get_version(model_version_id)
            if entry is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Model version not found: {model_version_id}",
                )
            # Resolve snapshot from the model version
            if entry.get("data_snapshot_id"):
                data_snapshot_id = data_snapshot_id or entry["data_snapshot_id"]
        except HTTPException:
            raise
        except Exception as exc:
            log.warning(
                "Failed to resolve model version for attribution",
                model_version_id=model_version_id,
                error=str(exc),
            )

    try:
        report = attribute_returns(
            market=body.market,
            start_date=body.start_date,
            end_date=body.end_date,
            strategy_config=body.strategy_config,
            factor_ids=body.factor_ids,
            model_version_id=model_version_id,
            data_snapshot_id=data_snapshot_id,
            min_observations=body.min_observations,
            regularization=body.regularization,
        )
        report_dict = report.to_dict()
        # Reshape to match frontend expected format
        summary = {
            "total_return": report_dict.get("total_return", 0),
            "excess_return": report_dict.get("excess_return", 0),
            # The frontend contract defines factor_coverage as model R-squared
            # in the 0..1 range.  factor_coverage in the research report is a
            # different return-explained percentage in the 0..100 range.
            "factor_coverage": report_dict.get("attribution_confidence", 0),
            "unexplained_return": report_dict.get("unexplained_return", 0),
            "benchmark_return": report_dict.get("benchmark_return", 0),
            "period": report_dict.get("period", ""),
            "market": report_dict.get("market", body.market),
            "strategy_name": report_dict.get("strategy_name", ""),
            "model_version_id": model_version_id or None,
            "data_snapshot_id": data_snapshot_id or None,
            "observation_count": report_dict.get("observation_count", 0),
            "observation_window": report_dict.get("observation_window", ""),
            "methodology": report_dict.get("methodology", "OLS"),
            "n_factors": report_dict.get("n_factors", 0),
            "residual": report_dict.get("unexplained_return", 0),
            "confidence_note": report_dict.get("confidence_note", ""),
        }
        factors = []
        for factor_index, fc in enumerate(report_dict.get("factor_contributions", []), start=1):
            factors.append(
                {
                    "factor_id": fc.get("factor_id", factor_index),
                    "factor_name": fc.get("factor_name", ""),
                    "factor_expression": fc.get("factor_expression", ""),
                    "ic": fc.get("factor_ic", 0),
                    "return_contribution": fc.get("return_contribution_pct", 0),
                    "risk_contribution": fc.get("risk_contribution_pct", 0),
                    "exposure": fc.get("exposure", 0),
                    "status": "Active",
                }
            )
        return {"ok": True, "summary": summary, "factors": factors}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Factor attribution failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Factor attribution failed: {e}")


class RollingAttributionRequest(BaseModel):
    """Request body for POST /factors/attribute/rolling."""

    market: str = Field("us", pattern="^(us|cn)$")
    start_date: str = Field("2021-01-01")
    end_date: str = Field(default_factory=default_end_date)
    factor_ids: list[int] | None = Field(
        None,
        description="Specific factor IDs to attribute. Omit to use all Active factors.",
    )
    window_months: int = Field(12, ge=3, le=60, description="Length of each window in months.")
    step_months: int = Field(3, ge=1, le=24, description="Step between windows in months.")


@router.post("/attribute/rolling")
async def attribute_factor_returns_rolling(body: RollingAttributionRequest) -> dict:
    """Compute factor attribution over rolling time windows.

    Runs the cross-sectional factor model on overlapping windows to show how
    factor contributions evolve over time. Returns per-window
    AttributionReports, per-factor trend data, and human-readable window
    labels.
    """
    from src.research.factor_attribution import attribute_returns_rolling

    try:
        result = attribute_returns_rolling(
            market=body.market,
            start_date=body.start_date,
            end_date=body.end_date,
            factor_ids=body.factor_ids,
            window_months=body.window_months,
            step_months=body.step_months,
        )
        return {"ok": True, "result": result.to_dict()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Rolling attribution failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rolling attribution failed: {e}")


# ---------------------------------------------------------------------------
# Factor Existence Check (T-03: deduplication)
# ---------------------------------------------------------------------------


@router.get("/exists")
async def check_factor_exists(
    expression: str = Query(..., description="Factor expression to check"),
) -> dict:
    """Check if a factor expression already exists in the registry.

    Returns the existing factor info if found, or exists=false if not.
    """
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    existing = registry.get_factor_by_expression(expression)
    if existing:
        return {
            "ok": True,
            "exists": True,
            "factor_id": existing["id"],
            "name": existing["name"],
            "stage": existing["stage"],
            "category": existing["category"],
            "message": f"Factor already exists: ID={existing['id']}, name='{existing['name']}', stage={existing['stage']}",
        }
    return {"ok": True, "exists": False}


# ---------------------------------------------------------------------------
# Factor Registry
# ---------------------------------------------------------------------------


@router.get("/registry")
async def list_registry_factors(
    stage: str | None = Query(None, description="Filter by stage"),
    category: str | None = Query(None, description="Filter by category"),
) -> dict:
    """List all factors in the registry with their latest validation.

    Returns the full factor list enriched with the most recent validation
    record per factor, plus registry-level summary stats.
    """
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    factors = registry.list_factors(stage=stage, category=category)

    # Attach latest validation to each factor
    enriched: list[dict] = []
    for f in factors:
        validations = registry.get_validations(f["id"])
        latest = validations[0] if validations else None
        enriched.append({**f, "latest_validation": latest})

    stats = registry.get_stats()

    # Add scan_stats — latest factor scan summary
    scan_stats = None
    try:
        from src.research.factor_scanner import FactorScanner

        scanner = FactorScanner()
        latest_scan = scanner.get_latest_scan()
        if latest_scan:
            results = latest_scan.get("results", [])
            passed = sum(1 for r in results if r.get("fdr_significant"))
            scan_stats = {
                "passed": passed,
                "total_scanned": len(results),
                "scanned_at": latest_scan.get("scanned_at", ""),
            }
    except Exception:
        pass

    return {
        "ok": True,
        "factors": enriched,
        "stats": stats,
        "scan_stats": scan_stats,
    }


@router.get("/registry/{factor_id}")
async def get_registry_factor_detail(factor_id: int) -> dict:
    """Get full factor detail including validation history and usage.

    Returns the factor record, all validation records (newest first),
    and all usage records.
    """
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    factor = registry.get_factor(factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail=f"Factor {factor_id} not found")

    validations = registry.get_validations(factor_id)
    usage = registry.get_usage(factor_id)

    return {
        "ok": True,
        "factor": factor,
        "validations": validations,
        "usage": usage,
    }


@router.post("/registry/{factor_id}/promote")
async def promote_registry_factor(factor_id: int) -> dict:
    """Promote a factor to the next lifecycle stage.

    Uses the three-tier gate system: Proposed -> Candidate -> Validated -> Active.
    Returns the new stage on success, or an error message on failure.
    """
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    factor = registry.get_factor(factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail=f"Factor {factor_id} not found")

    result = registry.promote(factor_id)
    if not result:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot promote factor in stage '{factor['stage']}'",
        )

    updated = registry.get_factor(factor_id)
    return {"ok": True, "new_stage": updated["stage"] if updated else None}


@router.post("/registry/{factor_id}/demote")
async def demote_registry_factor(factor_id: int) -> dict:
    """Demote an Active factor to Deprecated.

    Only Active factors can be demoted. Returns success or error.
    """
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    factor = registry.get_factor(factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail=f"Factor {factor_id} not found")

    result = registry.demote(factor_id)
    if not result:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot demote factor in stage '{factor['stage']}' (must be Active)",
        )

    updated = registry.get_factor(factor_id)
    return {"ok": True, "new_stage": updated["stage"] if updated else None}


# ---------------------------------------------------------------------------
# Experiment journal endpoints
# ---------------------------------------------------------------------------


@router.get("/experiments")
async def query_experiments_endpoint(
    query: str = Query(
        "summary", description="Query type: summary, tried, failed, or free-text search"
    ),
    market: str = Query("us", pattern="^(us|cn)$"),
    scope: str = Query("all", pattern="^(all|factors|models|walk_forward)$"),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Query the unified experiment journal.

    Supports several query modes:
    - ``summary``: overall stats across all registries
    - ``tried``: what experiments have been attempted
    - ``failed``: all failed experiments with reasons
    - any other value: free-text search across the specified scope
    """
    from src.research.experiment_journal import ExperimentJournal

    journal = ExperimentJournal()
    query_lower = query.strip().lower()

    try:
        if query_lower == "summary":
            result = journal.get_summary(market=market)
        elif query_lower == "tried":
            result = journal.what_have_i_tried(market=market)
        elif query_lower == "failed":
            result = journal.what_failed(market=market)
        else:
            result = journal.search_experiments(query=query, scope=scope)

        return {"ok": True, "result": result}
    except Exception as e:
        log.error("Experiment journal query failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@router.get("/experiments/summary")
async def experiments_summary(
    market: str = Query("us", pattern="^(us|cn)$"),
) -> dict:
    """Get summary statistics across all experiment registries.

    Returns counts by stage for factors and models, walk-forward file counts,
    validation pass rates, and recent activity.
    """
    from src.research.experiment_journal import ExperimentJournal

    try:
        journal = ExperimentJournal()
        return {"ok": True, "summary": journal.get_summary(market=market)}
    except Exception as e:
        log.error("Experiment summary failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Summary failed: {e}")


@router.get("/experiments/failed")
async def experiments_failed(
    market: str = Query("us", pattern="^(us|cn)$"),
) -> dict:
    """List all failed experiments with reasons.

    Includes factors at Proposed or Deprecated stage, Archived models,
    and walk-forward results with poor IC_IR.
    """
    from src.research.experiment_journal import ExperimentJournal

    try:
        journal = ExperimentJournal()
        failures = journal.what_failed(market=market)
        formatted = [
            _format_failed_experiment(failure, index) for index, failure in enumerate(failures)
        ]
        return {"ok": True, "total_failures": len(formatted), "failures": formatted}
    except Exception as e:
        log.error("Experiment failures query failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


def _format_failed_experiment(failure: dict, index: int) -> dict:
    """Map journal-native failures to the ExperimentLog frontend contract."""
    source = str(failure.get("_source") or "")
    experiment_type = "wf" if source == "walk_forward" else source
    name = str(
        failure.get("name") or failure.get("file") or failure.get("id") or f"failure-{index + 1}"
    )
    excluded = {
        "_source",
        "_timestamp",
        "timestamp",
        "id",
        "name",
        "file",
        "reason",
    }
    details = {
        key: value
        for key, value in failure.items()
        if key not in excluded and isinstance(value, (str, int, float, bool))
    }
    return {
        "id": f"{experiment_type or 'unknown'}:{failure.get('id') or failure.get('file') or index}",
        "timestamp": str(failure.get("timestamp") or failure.get("_timestamp") or ""),
        "type": experiment_type if experiment_type in {"factor", "model", "wf"} else "wf",
        "name": name,
        "failure_reason": str(failure.get("reason") or "Unknown failure"),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Structured experiment endpoints for ExperimentLogPage
# ---------------------------------------------------------------------------


@router.get("/experiments/log")
async def experiment_log(
    market: str = Query("us", pattern="^(us|cn)$"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """Return structured experiment log entries matching frontend ExperimentEntry type."""
    try:
        from src.research.factor_registry import FactorRegistry

        registry = FactorRegistry()
        entries = []
        entry_id = 0

        # Factors from registry
        for f in registry.list_factors():
            validations = registry.get_validations(f["id"])
            latest = validations[0] if validations else None
            ic = latest.get("ic") if latest else None
            stage = f.get("stage", "Proposed")
            result = (
                "pass"
                if stage in ("Active", "Validated")
                else ("fail" if stage in ("Deprecated", "Retired") else "in_progress")
            )
            entries.append(
                {
                    "id": entry_id,
                    "timestamp": f.get("updated_at", f.get("created_at", "")),
                    "type": "factor",
                    "name": f.get("name", ""),
                    "result": result,
                    "metrics": {"ic": ic, "stage": stage},
                }
            )
            entry_id += 1

        # Walk-forward results from artifacts
        import json as _json
        from pathlib import Path

        wf_dir = Path("artifacts/walk_forward")
        if wf_dir.exists():
            for wf_file in sorted(
                wf_dir.glob(f"{market}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )[:20]:
                try:
                    with open(wf_file) as fh:
                        data = _json.load(fh)
                    mean_ic = data.get("mean_ic", 0)
                    result = "pass" if data.get("ic_ir", 0) >= 0.3 else "fail"
                    entries.append(
                        {
                            "id": entry_id,
                            "timestamp": wf_file.stem.split("_", 1)[1]
                            if "_" in wf_file.stem
                            else "",
                            "type": "wf",
                            "name": wf_file.name,
                            "result": result,
                            "metrics": {
                                "mean_ic": mean_ic,
                                "ic_ir": data.get("ic_ir", 0),
                                "consistency": data.get("consistency_score", 0),
                            },
                        }
                    )
                    entry_id += 1
                except Exception:
                    continue

        # Model entries from SQLite registry
        try:
            from src.assistant.metadata_db import resolve_metadata_db_path
            from src.assistant.model_registry_index import ModelRegistryIndex
            from src.common import paths

            db_path = resolve_metadata_db_path(paths.get_artifacts_dir())
            model_reg = ModelRegistryIndex(db_path=db_path)
            for v in model_reg.list_versions(limit=100, market=market):
                wf = (
                    v.get("payload", {}).get("walk_forward", {})
                    if isinstance(v.get("payload"), dict)
                    else {}
                )
                wf_passed = wf.get("gate_passed", False) if isinstance(wf, dict) else False
                entries.append(
                    {
                        "id": entry_id,
                        "timestamp": v.get("created_at", ""),
                        "type": "model",
                        "name": v.get("tag", v.get("id", "")),
                        "result": "pass" if wf_passed else "in_progress",
                        "metrics": {
                            "stage": v.get("stage", "CANDIDATE"),
                            "market": v.get("market", ""),
                            "model_type": v.get("model_type", ""),
                        },
                    }
                )
                entry_id += 1
        except Exception:
            pass

        return {"ok": True, "experiments": entries[:limit]}
    except Exception as e:
        log.error("Experiment log failed", error=str(e), exc_info=True)
        return {"ok": True, "experiments": []}


@router.get("/experiments/log/summary")
async def experiment_log_summary(
    market: str = Query("us", pattern="^(us|cn)$"),
) -> dict:
    """Return summary matching frontend ExperimentSummary type."""
    try:
        from pathlib import Path

        from src.research.experiment_journal import ExperimentJournal
        from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

        registry = FactorRegistry()
        active_factors = len(registry.list_factors(stage=STAGE_ACTIVE))

        wf_dir = Path("artifacts/walk_forward")
        wf_count = len(list(wf_dir.glob(f"{market}_*.json"))) if wf_dir.exists() else 0

        # Use the same cross-registry failure definition as the detail panel.
        all_factors = registry.list_factors()
        failed = len(ExperimentJournal().what_failed(market=market))

        return {
            "ok": True,
            "summary": {
                "total_experiments": len(all_factors) + wf_count,
                "active_factors": active_factors,
                "wf_results": wf_count,
                "failed_experiments": failed,
            },
        }
    except Exception as e:
        log.error("Experiment summary failed", error=str(e), exc_info=True)
        return {
            "ok": True,
            "summary": {
                "total_experiments": 0,
                "active_factors": 0,
                "wf_results": 0,
                "failed_experiments": 0,
            },
        }
