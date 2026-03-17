import asyncio
import json
import os
import time
import uuid
import signal
import sys

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic import Field

from fastapi.security import HTTPBasic, HTTPBasicCredentials, APIKeyHeader
import secrets

security = HTTPBasic(auto_error=False)
api_key_header = APIKeyHeader(name="X-Developer-Token", auto_error=False)


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_local_request(request: Request) -> bool:
    try:
        host = str((request.client.host if request.client else "") or "").strip().lower()
    except Exception:
        host = ""
    # Add common internal IPs if we are in a container/proxy setup
    return host in {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


def verify_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
    developer_token: str | None = Depends(api_key_header),
):
    # 1. Developer Token Check (Stable mechanism for agents/developers)
    expected_token = os.environ.get("ALPHA_DEVELOPER_TOKEN")
    if expected_token and developer_token == expected_token:
        return HTTPBasicCredentials(username="developer", password="")

    # 2. Localhost trust (for UI and local calls)
    trust_localhost = _is_truthy(os.environ.get("TRADING_UI_TRUST_LOCALHOST"), default=True)
    is_local = _is_local_request(request)
    
    if credentials is None and trust_localhost and is_local:
        return HTTPBasicCredentials(username="local", password="")

    if credentials is None:
        print(f"Auth: Missing credentials. Host: {request.client.host if request.client else 'None'}. Local: {is_local}. URL: {request.url}")
        raise HTTPException(
            status_code=401,
            detail="Missing credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    # 3. Static password check (Basic Auth)
    correct_username = secrets.compare_digest(credentials.username, "agent")
    correct_password = secrets.compare_digest(credentials.password, os.environ.get("TRADING_UI_PASSWORD", "alpha2026"))
    
    if not (correct_username and correct_password):
        # Even if credentials provided, if we are on localhost and trust it, we could fall back.
        if trust_localhost and is_local:
             return HTTPBasicCredentials(username="local", password="")
             
        print(f"Auth: Incorrect credentials for {credentials.username}. Host: {request.client.host if request.client else 'None'}. Local: {is_local}")
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "artifacts")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")

from fastapi.staticfiles import StaticFiles
os.makedirs(ARTIFACTS_DIR, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")

from src.api.routers import data, models, arena, system, reports, strategy, backtest, chat, workflow

app.include_router(data.router, dependencies=[Depends(verify_auth)])
app.include_router(models.router, dependencies=[Depends(verify_auth)])
app.include_router(arena.router, dependencies=[Depends(verify_auth)])
app.include_router(system.router, dependencies=[Depends(verify_auth)])
app.include_router(reports.router, dependencies=[Depends(verify_auth)])
app.include_router(strategy.router, dependencies=[Depends(verify_auth)])
app.include_router(backtest.router, dependencies=[Depends(verify_auth)])
app.include_router(chat.router, dependencies=[Depends(verify_auth)])
app.include_router(workflow.router, dependencies=[Depends(verify_auth)])


if __name__ == "__main__":
    import uvicorn
    import argparse
    
    parser = argparse.ArgumentParser(description="Alpha Engine API Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8001)), help="Port to bind to")
    args = parser.parse_args()
    
    print(f"Starting Alpha Engine API Server on {args.host}:{args.port}")
    uvicorn.run("api_server:app", host=args.host, port=args.port, reload=False)
