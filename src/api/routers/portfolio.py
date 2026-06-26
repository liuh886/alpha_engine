"""Portfolio constraint API with explicit artifact provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from src.api.dependencies import get_model_index
from src.api.schemas.release_contracts import (
    ContractAPIRoute,
    PortfolioCheckRequestV1,
    error_response,
)

logger = structlog.get_logger()

router = APIRouter(
    prefix="/portfolio",
    tags=["portfolio"],
    route_class=ContractAPIRoute,
)


def _portfolio_artifact_candidates(portfolio_artifact_id: str) -> tuple[Path, ...]:
    from src.common import paths

    return (
        paths.ARTIFACTS_DIR / "backtest" / f"{portfolio_artifact_id}_positions.json",
        paths.ARTIFACTS_DIR / "signals" / f"{portfolio_artifact_id}.json",
    )


def _resolve_portfolio_artifact(portfolio_artifact_id: str) -> dict[str, Any]:
    """Resolve and parse only the explicitly named portfolio artifact."""
    for artifact_path in _portfolio_artifact_candidates(portfolio_artifact_id):
        if not artifact_path.is_file():
            continue
        try:
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("portfolio artifact is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("portfolio artifact must contain a JSON object")
        return data
    raise FileNotFoundError(f"portfolio artifact not found: {portfolio_artifact_id}")


def _load_prev_positions_from_artifact(
    portfolio_artifact_id: str,
) -> dict[str, float] | None:
    """Load positions only from the explicitly named portfolio artifact."""
    try:
        data = _resolve_portfolio_artifact(portfolio_artifact_id)
        positions = data.get("positions")
        if positions is None and all(isinstance(value, (int, float)) for value in data.values()):
            positions = data
        if not isinstance(positions, dict):
            return None
        return {str(symbol): float(weight) for symbol, weight in positions.items()}
    except (FileNotFoundError, TypeError, ValueError):
        logger.warning(
            "portfolio_artifact_read_failed",
            artifact_id=portfolio_artifact_id,
            exc_info=True,
        )
    return None


def _artifact_identity_conflicts(
    request: PortfolioCheckRequestV1,
    model_artifact: dict[str, Any],
    portfolio_artifact: dict[str, Any],
) -> list[dict[str, str]]:
    comparisons = (
        ("model.market", model_artifact.get("market"), request.market.value),
        ("model.data_snapshot_id", model_artifact.get("snapshot_id"), request.data_snapshot_id),
        (
            "portfolio.portfolio_artifact_id",
            portfolio_artifact.get("portfolio_artifact_id")
            or portfolio_artifact.get("artifact_id")
            or portfolio_artifact.get("id"),
            request.portfolio_artifact_id,
        ),
        (
            "portfolio.model_artifact_id",
            portfolio_artifact.get("model_artifact_id"),
            request.model_artifact_id,
        ),
        (
            "portfolio.data_snapshot_id",
            portfolio_artifact.get("data_snapshot_id") or portfolio_artifact.get("snapshot_id"),
            request.data_snapshot_id,
        ),
        ("portfolio.market", portfolio_artifact.get("market"), request.market.value),
    )
    conflicts: list[dict[str, str]] = []
    for binding, actual, expected in comparisons:
        if actual in (None, ""):
            continue
        actual_value = str(actual).lower() if binding.endswith(".market") else str(actual)
        expected_value = expected.lower() if binding.endswith(".market") else expected
        if actual_value != expected_value:
            conflicts.append({"binding": binding, "expected": expected, "actual": str(actual)})
    return conflicts


def _infer_market_segments(symbols: list[str]) -> dict[str, str]:
    industry_map: dict[str, str] = {}
    for symbol in symbols:
        code = symbol.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if code.startswith("688"):
            industry_map[symbol] = "STAR_Market"
        elif code.startswith("300"):
            industry_map[symbol] = "ChiNext"
        elif code.startswith("002"):
            industry_map[symbol] = "SME"
        elif code.startswith("6"):
            industry_map[symbol] = "Shanghai_Main"
        elif code.startswith("0"):
            industry_map[symbol] = "Shenzhen_Main"
        elif code.startswith(("8", "4")):
            industry_map[symbol] = "BSE"
        else:
            industry_map[symbol] = "Other"
    return industry_map


def _snapshot_store() -> Path:
    from src.common.paths import SNAPSHOT_STORE
    return SNAPSHOT_STORE


def _coverage_status(
    *,
    source: str,
    expected_symbols: list[str],
    available_symbols: list[str],
    complete_status: str,
    warnings: list[str],
) -> str:
    missing = sorted(set(expected_symbols) - set(available_symbols))
    if not missing:
        return complete_status
    preview = ", ".join(missing[:10])
    suffix = "" if len(missing) <= 10 else f" (+{len(missing) - 10} more)"
    warnings.append(f"{source} coverage is partial; missing symbols: {preview}{suffix}")
    return "partial"


def _collect_portfolio_market_data(
    request: PortfolioCheckRequestV1,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Resolve exact artifacts and gather inputs needed by constraint checks."""
    market_data: dict[str, Any] = {"portfolio_value": request.portfolio_value}
    data_status: dict[str, str] = {}
    data_warnings: list[str] = []

    if request.industry_map:
        market_data["industry_map"] = request.industry_map
        data_status["industry_map"] = _coverage_status(
            source="Industry classification",
            expected_symbols=list(request.positions),
            available_symbols=list(request.industry_map),
            complete_status="provided",
            warnings=data_warnings,
        )
    else:
        market_data["industry_map"] = _infer_market_segments(list(request.positions))
        data_status["industry_map"] = "auto_segment"
        data_warnings.append(
            "Industry map inferred from market segment, not an industry classification artifact"
        )

    if request.factor_exposures:
        market_data["factor_exposures"] = request.factor_exposures
        data_status["factor_exposures"] = _coverage_status(
            source="Factor exposure",
            expected_symbols=list(request.positions),
            available_symbols=list(request.factor_exposures),
            complete_status="provided",
            warnings=data_warnings,
        )
    else:
        data_status["factor_exposures"] = "unavailable"
        data_warnings.append("Factor exposure check skipped: no model-bound exposures provided")

    if request.prev_positions:
        market_data["prev_positions"] = request.prev_positions
        data_status["prev_positions"] = "provided"
    else:
        previous = _load_prev_positions_from_artifact(request.portfolio_artifact_id)
        if previous:
            market_data["prev_positions"] = previous
            data_status["prev_positions"] = "artifact"
        else:
            data_status["prev_positions"] = "unavailable"
            data_warnings.append(
                "Turnover check skipped: named portfolio artifact has no previous positions"
            )

    from qlib.data import D

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    from src.data.snapshot import DataSnapshot

    snapshot = DataSnapshot.resolve_snapshot(
        request.data_snapshot_id,
        store=_snapshot_store(),
    )
    provider_uri = snapshot.manifest.storage_uri
    safe_qlib_init(
        build_qlib_init_cfg(
            {},
            market=request.market.value,
            provider_uri_default=provider_uri,
        )
    )
    data_status["data_snapshot"] = "resolved"

    symbols = list(request.positions)
    try:
        returns_df = D.features(
            symbols,
            ["$close/Ref($close, 1) - 1"],
            start_time="2025-01-01",
        )
        if returns_df.empty:
            data_status["returns"] = "empty"
            data_warnings.append(
                "Correlation and consecutive-loss checks skipped: snapshot returns are empty"
            )
        else:
            returns_wide = returns_df.unstack(level="instrument")
            returns_wide.columns = [column[1] for column in returns_wide.columns]
            market_data["returns_df"] = returns_wide
            market_data["daily_returns"] = returns_wide.mean(axis=1).dropna().tolist()[-30:]
            data_status["returns"] = _coverage_status(
                source="Returns",
                expected_symbols=symbols,
                available_symbols=list(returns_wide.columns),
                complete_status="loaded",
                warnings=data_warnings,
            )

        volume_df = D.features(symbols, ["$volume"], start_time="2025-01-01")
        if volume_df.empty:
            data_status["volume"] = "empty"
            data_status["price"] = "not_run"
            data_warnings.append("Liquidity check skipped: snapshot volume data is empty")
        else:
            volume_wide = volume_df.unstack(level="instrument")
            volume_wide.columns = [column[1] for column in volume_wide.columns]
            market_data["volume_df"] = volume_wide
            data_status["volume"] = _coverage_status(
                source="Volume",
                expected_symbols=symbols,
                available_symbols=list(volume_wide.columns),
                complete_status="loaded",
                warnings=data_warnings,
            )

            price_df = D.features(symbols, ["$close"], start_time="2025-01-01")
            if price_df.empty:
                data_status["price"] = "empty"
                data_warnings.append("Liquidity check skipped: snapshot price data is empty")
            else:
                price_wide = price_df.unstack(level="instrument")
                price_wide.columns = [column[1] for column in price_wide.columns]
                market_data["price_df"] = price_wide
                data_status["price"] = _coverage_status(
                    source="Price",
                    expected_symbols=symbols,
                    available_symbols=list(price_wide.columns),
                    complete_status="loaded",
                    warnings=data_warnings,
                )
    except Exception as exc:
        logger.warning(
            "portfolio_snapshot_data_fetch_failed",
            snapshot_id=request.data_snapshot_id,
            error=str(exc),
        )
        data_status.setdefault("returns", "failed")
        data_status.setdefault("volume", "failed")
        data_status.setdefault("price", "failed")
        data_warnings.append("Required snapshot market data could not be loaded")

    return market_data, data_status, data_warnings


def _check_execution_status(
    data_status: dict[str, str],
) -> tuple[str, list[str], list[dict[str, str]]]:
    requirements = {
        "industry_concentration": (("industry_map", {"provided"}),),
        "correlation_crowding": (("returns", {"loaded"}),),
        "factor_exposure": (("factor_exposures", {"provided"}),),
        "liquidity_capacity": (
            ("volume", {"loaded"}),
            ("price", {"loaded"}),
        ),
        "turnover_cost": (("prev_positions", {"provided", "artifact"}),),
        "consecutive_loss": (("returns", {"loaded"}),),
    }
    performed: list[str] = []
    skipped: list[dict[str, str]] = []
    for check, sources in requirements.items():
        unavailable = [
            (source, data_status.get(source, "unavailable"))
            for source, ready_values in sources
            if data_status.get(source, "unavailable") not in ready_values
        ]
        if not unavailable:
            performed.append(check)
        else:
            skipped.append(
                {
                    "check": check,
                    "source": ",".join(source for source, _status in unavailable),
                    "reason": ",".join(
                        f"{source}:{source_status}" for source, source_status in unavailable
                    ),
                }
            )

    core_checks = {"correlation_crowding", "factor_exposure", "liquidity_capacity"}
    if not core_checks.intersection(performed):
        status = "blocked"
    elif skipped:
        status = "partial"
    else:
        status = "ready"
    return status, performed, skipped


def _inputs_for_performed_checks(
    market_data: dict[str, Any], performed_checks: list[str]
) -> dict[str, Any]:
    inputs = dict(market_data)
    performed = set(performed_checks)
    if "industry_concentration" not in performed:
        inputs.pop("industry_map", None)
    if not {"correlation_crowding", "consecutive_loss"}.intersection(performed):
        inputs.pop("returns_df", None)
        inputs.pop("daily_returns", None)
    if "factor_exposure" not in performed:
        inputs.pop("factor_exposures", None)
    if "liquidity_capacity" not in performed:
        inputs.pop("volume_df", None)
        inputs.pop("price_df", None)
    if "turnover_cost" not in performed:
        inputs.pop("prev_positions", None)
    return inputs


@router.post("/check")
def check_portfolio_constraints(request: PortfolioCheckRequestV1):
    """Check a portfolio while preserving exact model, data, and portfolio identities."""
    try:
        model_artifact = get_model_index().get_version(request.model_artifact_id)
        if model_artifact is None:
            return error_response(
                status_code=404,
                code="MODEL_ARTIFACT_NOT_FOUND",
                message="Model artifact not found",
                details={"model_artifact_id": request.model_artifact_id},
            )

        try:
            portfolio_artifact = _resolve_portfolio_artifact(request.portfolio_artifact_id)
        except FileNotFoundError:
            return error_response(
                status_code=404,
                code="PORTFOLIO_ARTIFACT_NOT_FOUND",
                message="Portfolio artifact not found",
                details={"portfolio_artifact_id": request.portfolio_artifact_id},
            )
        except ValueError:
            return error_response(
                status_code=409,
                code="PORTFOLIO_ARTIFACT_INVALID",
                message="Portfolio artifact could not be validated",
                details={"portfolio_artifact_id": request.portfolio_artifact_id},
            )

        identity_conflicts = _artifact_identity_conflicts(
            request,
            model_artifact,
            portfolio_artifact,
        )
        if identity_conflicts:
            return error_response(
                status_code=409,
                code="ARTIFACT_IDENTITY_CONFLICT",
                message="Artifact identities are not mutually consistent",
                details={"conflicts": identity_conflicts},
            )

        market_data, data_status, data_warnings = _collect_portfolio_market_data(request)
        status, performed_checks, skipped_checks = _check_execution_status(data_status)

        from src.guardrails.portfolio_constraints import PortfolioConstraintEngine

        engine = PortfolioConstraintEngine()
        violations = engine.check_portfolio(
            request.positions,
            _inputs_for_performed_checks(market_data, performed_checks),
        )
        summary = engine.get_summary(violations)

        response: dict[str, Any] = {
            "ok": status == "ready",
            "schema_version": "v1",
            "status": status,
            "market": request.market.value,
            "n_positions": len(request.positions),
            "artifact_identity": {
                "portfolio_artifact_id": request.portfolio_artifact_id,
                "model_artifact_id": request.model_artifact_id,
                "data_snapshot_id": request.data_snapshot_id,
            },
            "performed_checks": performed_checks,
            "skipped_checks": skipped_checks,
            "data_status": data_status,
            "data_warnings": data_warnings,
            **summary,
        }
        if status == "partial":
            response["code"] = "PORTFOLIO_CHECK_PARTIAL"
        elif status == "blocked":
            response["code"] = "PORTFOLIO_CHECK_BLOCKED"
            return JSONResponse(status_code=503, content=jsonable_encoder(response))
        return response
    except FileNotFoundError:
        return error_response(
            status_code=404,
            code="DATA_SNAPSHOT_NOT_FOUND",
            message="Data snapshot not found",
            details={"data_snapshot_id": request.data_snapshot_id},
        )
    except Exception:
        logger.exception(
            "portfolio_check_failed",
            portfolio_artifact_id=request.portfolio_artifact_id,
            model_artifact_id=request.model_artifact_id,
            data_snapshot_id=request.data_snapshot_id,
        )
        return error_response(
            status_code=500,
            code="API_INTERNAL_ERROR",
            message="Unable to evaluate portfolio constraints",
        )


@router.get("/config")
def get_constraint_config():
    """Get the current constraint configuration."""
    from src.guardrails.portfolio_constraints import DEFAULT_CONSTRAINT_CONFIG

    return {
        "ok": True,
        "schema_version": "v1",
        "config": DEFAULT_CONSTRAINT_CONFIG,
    }
