"""Versioned release API contracts shared by operational routers."""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import Any, Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.responses import JSONResponse, Response

SCHEMA_VERSION_V1 = "v1"
IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SYMBOL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,31}$"

_IDENTIFIER_RE = re.compile(IDENTIFIER_PATTERN)
_SYMBOL_RE = re.compile(SYMBOL_PATTERN)


class Market(str, Enum):
    CN = "cn"
    US = "us"


class ModelStage(str, Enum):
    STAGING = "STAGING"
    RECOMMENDED = "RECOMMENDED"


class StrictRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["v1"] = SCHEMA_VERSION_V1


def validate_identifier(value: str, *, field_name: str = "identifier") -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{field_name} must be 1-128 path-safe ASCII characters "
            "(letters, digits, '.', '_', ':', or '-')"
        )
    return value


class ModelPromotionRequestV1(StrictRequestV1):
    artifact_id: str
    stage: ModelStage

    @field_validator("artifact_id")
    @classmethod
    def _validate_artifact_id(cls, value: str) -> str:
        return validate_identifier(value, field_name="artifact_id")


class ModelDeleteRequestV1(StrictRequestV1):
    artifact_id: str

    @field_validator("artifact_id")
    @classmethod
    def _validate_artifact_id(cls, value: str) -> str:
        return validate_identifier(value, field_name="artifact_id")


class DataUpdateRequestV1(StrictRequestV1):
    """Request contract for triggering a data update job."""

    full: bool = False
    market: Literal["all", "us", "cn", "hk"] = "all"
    start: str = "2020-01-01"
    lookback_days: int = Field(default=30, ge=0, le=365)


class BacktestRunRequestV1(StrictRequestV1):
    """Request contract for triggering a backtest run."""

    market: Market
    model_type: Literal["lgbm", "xgb"] = "lgbm"
    mode: Literal["train", "rebacktest"] = "train"
    run_id: str | None = None
    start: str = "2025-01-01"
    end: str = "latest"
    tag: str | None = None
    profile_path: str = "configs/strategy_profile.json"
    model_path: str | None = None
    snapshot_id: str | None = Field(
        default=None,
        description="Explicit data snapshot identity for reproducible backtests",
    )

    @field_validator("run_id", "tag", "snapshot_id", "model_path")
    @classmethod
    def _validate_optional_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_identifier(value, field_name="identifier")


class TrainingRunRequestV1(StrictRequestV1):
    """Request contract for triggering a training run."""

    market: Market
    tag: str = Field(min_length=1, max_length=128)
    model_type: Literal["lgbm", "xgb"] = "lgbm"
    profile_path: str = "configs/strategy_profile.json"
    snapshot_id: str | None = Field(
        default=None,
        description="Explicit data snapshot identity for reproducible training",
    )

    @field_validator("tag", "snapshot_id")
    @classmethod
    def _validate_identity(cls, value: str | None, info) -> str | None:
        if value is None:
            return value
        return validate_identifier(value, field_name=info.field_name)


class PortfolioCheckRequestV1(StrictRequestV1):
    portfolio_artifact_id: str
    model_artifact_id: str
    data_snapshot_id: str
    positions: dict[str, float] = Field(min_length=1, max_length=500)
    market: Market
    portfolio_value: float = Field(gt=0, le=1_000_000_000_000)
    industry_map: dict[str, str] | None = Field(default=None, max_length=500)
    factor_exposures: dict[str, dict[str, float]] | None = Field(default=None, max_length=500)
    prev_positions: dict[str, float] | None = Field(default=None, max_length=500)

    @field_validator("portfolio_artifact_id", "model_artifact_id", "data_snapshot_id")
    @classmethod
    def _validate_artifact_identity(cls, value: str, info) -> str:
        return validate_identifier(value, field_name=info.field_name)

    @field_validator("positions", "prev_positions")
    @classmethod
    def _validate_positions(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is None:
            return value
        for symbol, weight in value.items():
            if not _SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"invalid symbol identifier: {symbol!r}")
            if not math.isfinite(weight) or not -1.0 <= weight <= 1.0:
                raise ValueError(f"weight for {symbol!r} must be finite and between -1 and 1")
        return value

    @field_validator("industry_map")
    @classmethod
    def _validate_industry_map(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        for symbol, industry in value.items():
            if not _SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"invalid symbol identifier: {symbol!r}")
            if not industry or len(industry) > 128:
                raise ValueError(f"industry for {symbol!r} must contain 1-128 characters")
        return value

    @field_validator("factor_exposures")
    @classmethod
    def _validate_factor_exposures(
        cls, value: dict[str, dict[str, float]] | None
    ) -> dict[str, dict[str, float]] | None:
        if value is None:
            return value
        for symbol, exposures in value.items():
            if not _SYMBOL_RE.fullmatch(symbol):
                raise ValueError(f"invalid symbol identifier: {symbol!r}")
            if len(exposures) > 200:
                raise ValueError(f"too many factor exposures for {symbol!r}")
            for factor, exposure in exposures.items():
                validate_identifier(factor, field_name="factor name")
                if not math.isfinite(exposure):
                    raise ValueError(f"factor exposure for {symbol!r}/{factor!r} must be finite")
        return value

    @model_validator(mode="after")
    def _validate_related_symbols(self) -> PortfolioCheckRequestV1:
        position_symbols = set(self.positions)
        for field_name in ("industry_map", "factor_exposures", "prev_positions"):
            values = getattr(self, field_name)
            if values is None:
                continue
            unknown = set(values) - position_symbols
            if unknown:
                raise ValueError(
                    f"{field_name} contains symbols absent from positions: {sorted(unknown)!r}"
                )
        return self


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
    recoverable: bool = False,
    next_action: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "ok": False,
        "code": code,
        "message": message,
        "recoverable": recoverable,
    }
    if details is not None:
        payload["detail"] = details
    if next_action is not None:
        payload["next_action"] = next_action
    if extra:
        payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


class ContractAPIRoute(APIRoute):
    """Attach the stable error envelope to FastAPI request validation failures."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def contract_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError as exc:
                details = [
                    {
                        "location": list(error["loc"]),
                        "type": error["type"],
                        "message": error["msg"],
                    }
                    for error in exc.errors()
                ]
                return error_response(
                    status_code=422,
                    code="API_VALIDATION_ERROR",
                    message="Request validation failed",
                    details=details,
                )

        return contract_handler
