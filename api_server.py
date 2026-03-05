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

from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic(auto_error=False)


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_local_request(request: Request) -> bool:
    try:
        host = str((request.client.host if request.client else "") or "").strip().lower()
    except Exception:
        host = ""
    return host in {"127.0.0.1", "::1", "localhost"}


def verify_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
):
    # Local-first UX: allow localhost calls when explicitly enabled (default: enabled).
    trust_localhost = _is_truthy(os.environ.get("TRADING_UI_TRUST_LOCALHOST"), default=True)
    if credentials is None and trust_localhost and _is_local_request(request):
        return HTTPBasicCredentials(username="local", password="")

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Very basic static password check for prototype phase
    correct_username = secrets.compare_digest(credentials.username, "agent")
    correct_password = secrets.compare_digest(credentials.password, os.environ.get("TRADING_UI_PASSWORD", "alpha2026"))
    if not (correct_username and correct_password):
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

from src.api.routers import data, models, arena, system, reports, strategy, backtest, chat

app.include_router(data.router, dependencies=[Depends(verify_auth)])
app.include_router(models.router, dependencies=[Depends(verify_auth)])
app.include_router(arena.router, dependencies=[Depends(verify_auth)])
app.include_router(system.router, dependencies=[Depends(verify_auth)])
app.include_router(reports.router, dependencies=[Depends(verify_auth)])
app.include_router(strategy.router, dependencies=[Depends(verify_auth)])
app.include_router(backtest.router, dependencies=[Depends(verify_auth)])
app.include_router(chat.router, dependencies=[Depends(verify_auth)])


if __name__ == "__main__":
    import uvicorn
    # Make sure to run on 8001 so the Vite proxy picks it up
    uvicorn.run("api_server:app", host="127.0.0.1", port=8001, reload=False)
