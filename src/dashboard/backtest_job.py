from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path

from src.common.paths import RUNS_DIR
from src.dashboard.backtest_runner import build_backtest_commands


def create_backtest_job(
    *,
    market: str,
    model_type: str,
    mode: str = "train",
    model_path: str | None = None,
    start: str = "2025-01-01",
    end: str = "latest",
    project_root: Path,
    python_exe: str,
    profile_path: str,
    tag: str | None = None,
    **kwargs,
) -> dict:
    market = (market or "").lower().strip()
    if market not in {"cn", "us"}:
        raise ValueError("market must be 'cn' or 'us'")

    model_type = (model_type or "lgbm").lower().strip() or "lgbm"
    mode = (mode or "train").lower().strip()
    if mode not in {"train", "rebacktest"}:
        raise ValueError("mode must be 'train' or 'rebacktest'")
    if mode == "rebacktest" and not model_path:
        raise ValueError("model_path is required when mode='rebacktest'")

    # Generate a default tag if none provided (especially for dashboard UI runs)
    if not tag:
        tag = f"DB_{mode.upper()}_{datetime.now().strftime('%Y%m%d_%H%M')}"

    job_id = uuid.uuid4().hex
    log_path = RUNS_DIR / f"dashboard_backtest_{market}_{job_id}.log"

    commands = build_backtest_commands(
        python_exe=python_exe,
        market=market,
        model_type=model_type,
        profile_path=profile_path,
        mode=mode,
        model_path=model_path,
        start=start,
        end=end,
        tag=tag,
    )

    return {
        "id": job_id,
        "type": "backtest",
        "market": market,
        "model_type": model_type,
        "mode": mode,
        "tag": tag,
        "strategy_template": kwargs.get("strategy_template"),
        "cost_params": kwargs.get("cost_params"),
        "status": "queued",
        "created_at": time.time(),
        "log_path": str(log_path),
        "commands": commands,
    }
