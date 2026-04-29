from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ENV_METADATA_DB_PATH = "TRADING_ASSISTANT_METADATA_DB_PATH"
DEFAULT_RELATIVE_DB_PATH = Path("artifacts") / "metadata" / "metadata.db"


def resolve_metadata_db_path(project_root: str | Path) -> Path:
    override = os.environ.get(ENV_METADATA_DB_PATH) or ""
    if override.strip():
        return Path(override)
    return Path(project_root) / DEFAULT_RELATIVE_DB_PATH


def connect(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn
