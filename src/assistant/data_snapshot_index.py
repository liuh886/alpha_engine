from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

from src.assistant.metadata_db import connect


class DataSnapshotIndex:
    """
    Minimal data snapshot index stored in SQLite.

    This complements the on-disk marker file written by scripts/update_data.py.
    """

    def __init__(self, *, db_path: str | Path):
        self._db_path = Path(db_path)
        self._ensure_schema()

    @contextlib.contextmanager
    def _connect(self):
        conn = connect(self._db_path)
        try:
            with conn:  # 关键修复：确保事务 Commit
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    dataset_key TEXT,
                    provider_uri TEXT,
                    freq TEXT,
                    latest_calendar_day TEXT,
                    generated_at TEXT,
                    payload_json TEXT,
                    created_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_snapshots_dataset_freq ON data_snapshots(dataset_key, freq)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_snapshots_latest_day ON data_snapshots(latest_calendar_day)"
            )

    def upsert(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        snapshot_id = str(payload.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise ValueError("payload.snapshot_id is required")

        dataset_key = str(payload.get("dataset_key") or "")
        provider_uri = str(payload.get("provider_uri") or "")
        freq = str(payload.get("freq") or "")
        latest_calendar_day = str(payload.get("latest_calendar_day") or "")
        generated_at = str(payload.get("generated_at") or "")
        created_at = float(payload.get("created_at") or time.time())
        payload_json = json.dumps(payload, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO data_snapshots (
                    snapshot_id, dataset_key, provider_uri, freq, latest_calendar_day,
                    generated_at, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    dataset_key=excluded.dataset_key,
                    provider_uri=excluded.provider_uri,
                    freq=excluded.freq,
                    latest_calendar_day=excluded.latest_calendar_day,
                    generated_at=excluded.generated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    snapshot_id,
                    dataset_key,
                    provider_uri,
                    freq,
                    latest_calendar_day,
                    generated_at,
                    payload_json,
                    created_at,
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}

    def get_latest(self, *, dataset_key: str, freq: str) -> dict | None:
        dataset_key = str(dataset_key or "").strip()
        freq = str(freq or "").strip()
        if not dataset_key or not freq:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM data_snapshots
                WHERE dataset_key = ? AND freq = ?
                ORDER BY latest_calendar_day DESC, created_at DESC
                LIMIT 1
                """,
                (dataset_key, freq),
            ).fetchone()
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}
