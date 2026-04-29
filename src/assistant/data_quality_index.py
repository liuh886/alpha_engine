from __future__ import annotations

import contextlib
import hashlib
import json
import time
from pathlib import Path

from src.assistant.metadata_db import connect


def _quality_id(snapshot_id: str, market: str) -> str:
    key = f"{snapshot_id}\n{market}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class DataQualityIndex:
    """
    Minimal data quality report index stored in SQLite.

    Reports are derived data and can always be regenerated from local datasets.
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
                CREATE TABLE IF NOT EXISTS data_quality_reports (
                    id TEXT PRIMARY KEY,
                    snapshot_id TEXT,
                    dataset_key TEXT,
                    freq TEXT,
                    market TEXT,
                    latest_calendar_day TEXT,
                    summary_json TEXT,
                    created_ts REAL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_data_quality_dataset_market
                ON data_quality_reports(dataset_key, freq, market)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_data_quality_latest_day
                ON data_quality_reports(latest_calendar_day)
                """
            )

    def upsert(
        self,
        *,
        snapshot_id: str,
        dataset_key: str,
        freq: str,
        market: str,
        latest_calendar_day: str,
        summary: dict,
    ) -> dict:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            raise ValueError("snapshot_id is required")
        dataset_key = str(dataset_key or "").strip()
        if not dataset_key:
            raise ValueError("dataset_key is required")
        freq = str(freq or "").strip()
        if not freq:
            raise ValueError("freq is required")
        market = str(market or "").strip().lower()
        if not market:
            raise ValueError("market is required")
        latest_calendar_day = str(latest_calendar_day or "").strip()
        if not latest_calendar_day:
            raise ValueError("latest_calendar_day is required")

        report_id = _quality_id(snapshot_id, market)
        created_ts = time.time()
        summary_json = json.dumps(summary or {}, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO data_quality_reports (
                    id, snapshot_id, dataset_key, freq, market,
                    latest_calendar_day, summary_json, created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    latest_calendar_day=excluded.latest_calendar_day,
                    summary_json=excluded.summary_json,
                    created_ts=excluded.created_ts
                """,
                (
                    report_id,
                    snapshot_id,
                    dataset_key,
                    freq,
                    market,
                    latest_calendar_day,
                    summary_json,
                    created_ts,
                ),
            )
        return self.get_report(report_id) or {"id": report_id}

    def get_report(self, report_id: str) -> dict | None:
        report_id = str(report_id or "").strip()
        if not report_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_quality_reports WHERE id = ?", (report_id,)
            ).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        if out.get("summary_json"):
            try:
                out["summary"] = json.loads(out["summary_json"])
            except Exception:
                out["summary"] = {}
        else:
            out["summary"] = {}
        return out

    def get_latest(self, *, dataset_key: str, freq: str, market: str) -> dict | None:
        dataset_key = str(dataset_key or "").strip()
        freq = str(freq or "").strip()
        market = str(market or "").strip().lower()
        if not dataset_key or not freq or not market:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM data_quality_reports
                WHERE dataset_key = ? AND freq = ? AND market = ?
                ORDER BY latest_calendar_day DESC, created_ts DESC
                LIMIT 1
                """,
                (dataset_key, freq, market),
            ).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        if out.get("summary_json"):
            try:
                out["summary"] = json.loads(out["summary_json"])
            except Exception:
                out["summary"] = {}
        else:
            out["summary"] = {}
        return out
