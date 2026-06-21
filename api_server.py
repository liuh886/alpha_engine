import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure PROJECT_ROOT is in sys.path
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
    arena,
    artifacts,
    backtest,
    chat,
    data,
    decay,
    evidence,
    factors,
    jobs,
    models,
    portfolio,
    reports,
    research,
    stock_analysis,
    strategy,
    system,
    tools,
    walk_forward,
    workflow,
)
from src.common.logging import setup_logging
from src.common.runtime_settings import get_runtime_settings

runtime_settings = get_runtime_settings()
setup_logging(development=runtime_settings.env == "development")


# ---------------------------------------------------------------------------
# Pydantic response contracts for public endpoints
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str


class VersionResponse(BaseModel):
    version: str
    status: str


class ReadinessCheckResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, dict[str, object]]


app = FastAPI(title="AlphaEngine Dashboard API", version=APP_VERSION)


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(runtime_settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)

security = HTTPBasic()


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    settings = get_runtime_settings()
    correct_username = settings.trading_ui_user
    correct_password = settings.trading_ui_password

    if not correct_username or not correct_password:
        # Secure by default: Fail if auth is not configured.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server authentication not configured. Please set TRADING_UI_USER and TRADING_UI_PASSWORD environment variables.",
        )

    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# 1. API Routers (Must come BEFORE static mount)
app.include_router(
    system.router, prefix="/api/system", tags=["system"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    jobs.router, prefix="/api", tags=["jobs"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    workflow.router,
    prefix="/api/workflow",
    tags=["workflow"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    arena.router, prefix="/api/arena", tags=["arena"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    artifacts.router,
    prefix="/api/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    backtest.router,
    prefix="/api/backtest",
    tags=["backtest"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    walk_forward.router,
    prefix="/api/backtest",
    tags=["walk-forward"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    chat.router, prefix="/api/agent", tags=["agent"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    data.router, prefix="/api/data", tags=["data"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    evidence.router,
    prefix="/api/evidence",
    tags=["evidence"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    models.router, prefix="/api/models", tags=["models"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    reports.router,
    prefix="/api/reports",
    tags=["reports"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    strategy.router,
    prefix="/api/strategy",
    tags=["strategy"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    tools.router,
    prefix="/api/tools",
    tags=["tools"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    factors.router,
    prefix="/api",
    tags=["factors"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    stock_analysis.router,
    prefix="/api",
    tags=["stock-analysis"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    research.router,
    prefix="/api",
    tags=["research"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    decay.router,
    prefix="/api",
    tags=["decay"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    portfolio.router,
    prefix="/api",
    tags=["portfolio"],
    dependencies=[Depends(get_current_user)],
)


# 2. Authenticated identity endpoint
@app.get("/api/system/me")
def whoami(username: str = Depends(get_current_user)):
    """Return the authenticated user's username."""
    return {"username": username}


# 3. Public Endpoints
@app.get("/health", response_model=HealthResponse)
@app.head("/health")
@app.get("/api/public/health", response_model=HealthResponse)
@app.head("/api/public/health")
def health_check():
    return HealthResponse(status="ok", version=APP_VERSION)


@app.get("/api/health/live", response_model=HealthResponse)
@app.head("/api/health/live")
def health_live():
    """Basic liveness probe -- always 200 if the process is up."""
    return HealthResponse(status="alive", version=APP_VERSION)


@app.get("/api/health/ready")
def health_ready():
    """Readiness probe that checks real system state.

    Returns HTTP 503 with structured diagnostics when the system is not
    ready to serve traffic (missing snapshot, inaccessible model registry
    or dashboard DB).
    """
    from fastapi.responses import JSONResponse

    checks: dict[str, dict[str, object]] = {}
    all_ok = True

    # 1. Data snapshot availability
    try:
        from src.data.snapshot import DataSnapshot

        snapshot = DataSnapshot.get_latest_snapshot()
        if snapshot is not None and snapshot.manifest.quality_verdict == "pass":
            checks["snapshot"] = {
                "status": "ok",
                "snapshot_id": snapshot.snapshot_id,
                "quality_verdict": snapshot.manifest.quality_verdict,
            }
        else:
            all_ok = False
            checks["snapshot"] = {
                "status": "unavailable",
                "detail": "no published snapshot with quality_verdict=pass",
            }
    except Exception as exc:
        all_ok = False
        checks["snapshot"] = {"status": "error", "detail": str(exc)}

    # 2. Model registry accessibility
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex

        db_path = resolve_metadata_db_path(PROJECT_ROOT)
        index = ModelRegistryIndex(db_path=db_path)
        versions = index.list_versions(limit=1)
        checks["model_registry"] = {
            "status": "ok",
            "db_path": str(db_path),
            "model_count": len(versions),
        }
    except Exception as exc:
        all_ok = False
        checks["model_registry"] = {"status": "error", "detail": str(exc)}

    # 3. Dashboard DB accessibility
    try:
        from src.common import paths as _paths

        dashboard_db = getattr(_paths, "DASHBOARD_DB_PATH", None)
        if dashboard_db is None:
            dashboard_db = PROJECT_ROOT / "artifacts" / "dashboard" / "dashboard_db.json"
        dashboard_db = Path(dashboard_db)
        if dashboard_db.exists():
            checks["dashboard_db"] = {
                "status": "ok",
                "path": str(dashboard_db),
            }
        else:
            # Dashboard DB may not exist yet (first run) -- warn but don't fail
            checks["dashboard_db"] = {
                "status": "missing",
                "path": str(dashboard_db),
                "detail": "dashboard DB not yet created; non-fatal",
            }
    except Exception as exc:
        all_ok = False
        checks["dashboard_db"] = {"status": "error", "detail": str(exc)}

    if all_ok:
        return ReadinessCheckResponse(status="ready", version=APP_VERSION, checks=checks)
    return JSONResponse(
        status_code=503,
        content=ReadinessCheckResponse(
            status="not_ready", version=APP_VERSION, checks=checks
        ).model_dump(),
    )


@app.get("/api/public/version", response_model=VersionResponse)
@app.head("/api/public/version")
def get_public_version():
    return VersionResponse(version=APP_VERSION, status="stable")


# 4. Mount Static Files at ROOT
site_path = runtime_settings.static_site_dir

if site_path.exists():
    # Explicitly serve index.html at root to ensure it's handled
    @app.api_route("/", methods=["GET", "HEAD"])
    async def serve_index():
        import hashlib

        content = (site_path / "index.html").read_bytes()
        etag = hashlib.md5(content).hexdigest()[:12]
        return FileResponse(
            site_path / "index.html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "ETag": f'"{etag}"',
            },
        )

    # Mount everything else (StaticFiles supports HEAD automatically)
    app.mount("/", StaticFiles(directory=str(site_path)), name="site")

if __name__ == "__main__":
    import uvicorn

    target_port = runtime_settings.api_port
    print(f"\n>>> [SERVER] Launching Alpha Engine Dashboard on: http://localhost:{target_port}\n")
    # Listen on 0.0.0.0 for Docker compatibility
    uvicorn.run(app, host=runtime_settings.api_host, port=target_port)
