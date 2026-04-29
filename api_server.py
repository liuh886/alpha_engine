import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

# Ensure PROJECT_ROOT is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.api.routers import (
    arena,
    backtest,
    chat,
    data,
    jobs,
    models,
    reports,
    strategy,
    system,
    workflow,
)

app = FastAPI(title="AlphaEngine Dashboard API", version="1.0.0")

# CORS Configuration
# Standard security: In production, allow_origins should be limited.
# Defaulting to localhost and internal Docker communication.
# User can override via ALLOWED_ORIGINS env var.
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
if allowed_origins_env:
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost:5173",  # Vite dev
        "http://127.0.0.1:5173",
        "http://localhost:8000",  # Static serve
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)

security = HTTPBasic()


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("TRADING_UI_USER")
    correct_password = os.getenv("TRADING_UI_PASSWORD")

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
    backtest.router,
    prefix="/api/backtest",
    tags=["backtest"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    chat.router, prefix="/api/agent", tags=["agent"], dependencies=[Depends(get_current_user)]
)
app.include_router(
    data.router, prefix="/api/data", tags=["data"], dependencies=[Depends(get_current_user)]
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


# 2. Public Endpoints
@app.get("/health")
@app.head("/health")
@app.get("/api/public/health")
@app.head("/api/public/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/public/version")
@app.head("/api/public/version")
def get_public_version():
    return {"version": "2.5.0-PRO", "status": "stable"}


# 3. Mount Static Files at ROOT
site_path = PROJECT_ROOT / "site"

if site_path.exists():
    # Explicitly serve index.html at root to ensure it's handled
    @app.api_route("/", methods=["GET", "HEAD"])
    async def serve_index():
        return FileResponse(site_path / "index.html")

    # Mount everything else (StaticFiles supports HEAD automatically)
    app.mount("/", StaticFiles(directory=str(site_path)), name="site")

if __name__ == "__main__":
    import uvicorn

    # Use environment variable for port, default to 8000
    target_port = int(os.getenv("PORT", 8000))

    print(f"\n>>> [SERVER] Launching Alpha Engine Dashboard on: http://localhost:{target_port}\n")
    # Listen on 0.0.0.0 for Docker compatibility
    uvicorn.run(app, host="0.0.0.0", port=target_port)
