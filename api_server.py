"""Temporary FastAPI host for HTTP adapters awaiting retirement.

The supported Web product is the static/local Research Artifact Studio. This
process no longer serves frontend assets, demo fixtures, browser identity,
operational controls or artifact/report APIs. It exists only while the
remaining domain-heavy routers are extracted under #319 and is deleted in #320.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

try:
    from importlib.metadata import version as _get_pkg_version

    APP_VERSION = _get_pkg_version("trading-assistant")
except Exception:
    APP_VERSION = "2.5.0"

from src.api.routers import (
    backtest,
    data,
    decay,
    evidence,
    factors,
    models,
    portfolio,
    research,
    stock_analysis,
    walk_forward,
    workflow,
)
from src.common.logging import setup_logging
from src.common.runtime_settings import get_runtime_settings

runtime_settings = get_runtime_settings()
setup_logging(development=runtime_settings.env == "development")


class HealthResponse(BaseModel):
    status: str
    version: str


class VersionResponse(BaseModel):
    version: str
    status: str


app = FastAPI(
    title="AlphaEngine Legacy Adapter API",
    version=APP_VERSION,
    description="Temporary migration host. Not a supported Web product.",
)

security = HTTPBasic()


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    settings = get_runtime_settings()
    username = settings.trading_ui_user
    password = settings.trading_ui_password
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Legacy adapter authentication is not configured.",
        )
    if not (
        secrets.compare_digest(credentials.username, username)
        and secrets.compare_digest(credentials.password, password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


AUTH = [Depends(get_current_user)]

# Only adapters awaiting domain extraction remain mounted.
app.include_router(workflow.router, prefix="/api/workflow", dependencies=AUTH)
app.include_router(backtest.router, prefix="/api/backtest", dependencies=AUTH)
app.include_router(walk_forward.router, prefix="/api/backtest", dependencies=AUTH)
app.include_router(data.router, prefix="/api/data", dependencies=AUTH)
app.include_router(evidence.router, prefix="/api/evidence", dependencies=AUTH)
app.include_router(models.router, prefix="/api/models", dependencies=AUTH)
app.include_router(factors.router, prefix="/api", dependencies=AUTH)
app.include_router(stock_analysis.router, prefix="/api", dependencies=AUTH)
app.include_router(research.router, prefix="/api", dependencies=AUTH)
app.include_router(decay.router, prefix="/api", dependencies=AUTH)
app.include_router(portfolio.router, prefix="/api", dependencies=AUTH)


@app.get("/health", response_model=HealthResponse)
@app.head("/health")
@app.get("/api/public/health", response_model=HealthResponse)
@app.head("/api/public/health")
def health_check() -> HealthResponse:
    return HealthResponse(status="deprecated", version=APP_VERSION)


@app.get("/api/public/version", response_model=VersionResponse)
@app.head("/api/public/version")
def get_public_version() -> VersionResponse:
    return VersionResponse(version=APP_VERSION, status="legacy-adapter-retirement")


if __name__ == "__main__":
    import uvicorn

    print(
        "\n>>> [DEPRECATED] Starting temporary Alpha Engine HTTP adapters on "
        f"http://{runtime_settings.api_host}:{runtime_settings.api_port}\n"
    )
    uvicorn.run(app, host=runtime_settings.api_host, port=runtime_settings.api_port)
