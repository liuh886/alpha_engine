from __future__ import annotations

import contextlib
from pathlib import Path

from src.assistant.metadata_db import connect


class BaseIndex:
    """Shared base for SQLite-backed index classes."""

    def __init__(self, *, db_path: str | Path):
        self._db_path = Path(db_path)
        self._ensure_schema()

    @contextlib.contextmanager
    def _connect(self):
        conn = connect(self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        raise NotImplementedError
