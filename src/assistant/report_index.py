from __future__ import annotations

import contextlib
import hashlib
import json
import time
from pathlib import Path

from src.assistant.metadata_db import connect


def _report_id(report_type: str, ref_id: str, date: str | None) -> str:
    key = f"{report_type}\n{ref_id}\n{date or ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class ReportIndex:
    """
    Minimal report index stored in SQLite.

    This is a stepping stone toward the design doc's `reports` table.
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
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    date TEXT,
                    formats_json TEXT,
                    paths_json TEXT,
                    meta_json TEXT,
                    created_ts REAL,
                    updated_ts REAL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_type_date ON reports(type, date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_ref_id ON reports(ref_id)")

    def upsert(
        self,
        *,
        report_type: str,
        ref_id: str,
        date: str | None,
        formats: list[str],
        paths: dict,
        meta: dict | None = None,
    ) -> dict:
        report_type = str(report_type or "").strip()
        if not report_type:
            raise ValueError("report_type is required")
        ref_id = str(ref_id or "").strip()
        if not ref_id:
            raise ValueError("ref_id is required")
        date_s = str(date).strip() if date else ""
        if date_s == "":
            date_s = None

        report_id = _report_id(report_type, ref_id, date_s)
        now = time.time()

        formats_json = json.dumps(list(formats or []), ensure_ascii=False)
        paths_json = json.dumps(paths or {}, ensure_ascii=False)
        meta_json = json.dumps(meta or {}, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (
                    id, type, ref_id, date,
                    formats_json, paths_json, meta_json,
                    created_ts, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    formats_json=excluded.formats_json,
                    paths_json=excluded.paths_json,
                    meta_json=excluded.meta_json,
                    updated_ts=excluded.updated_ts
                """,
                (
                    report_id,
                    report_type,
                    ref_id,
                    date_s,
                    formats_json,
                    paths_json,
                    meta_json,
                    now,
                    now,
                ),
            )
        row = self.get_report(report_id)
        return (
            row if row else {"id": report_id, "type": report_type, "ref_id": ref_id, "date": date_s}
        )

    def get_report(self, report_id: str) -> dict | None:
        report_id = str(report_id or "").strip()
        if not report_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        for k in ("formats_json", "paths_json", "meta_json"):
            raw = out.get(k)
            if not raw:
                continue
            try:
                out[k.replace("_json", "")] = json.loads(raw)
            except Exception:
                out[k.replace("_json", "")] = [] if k == "formats_json" else {}
        return out

    def list_reports(
        self,
        *,
        limit: int = 100,
        report_type: str | None = None,
        ref_id: str | None = None,
    ) -> list[dict]:
        limit = int(limit) if limit is not None else 100
        if limit <= 0:
            return []

        where: list[str] = []
        params: list[object] = []
        if report_type:
            where.append("type = ?")
            params.append(str(report_type))
        if ref_id:
            where.append("ref_id = ?")
            params.append(str(ref_id))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM reports
                {where_sql}
                ORDER BY date DESC, updated_ts DESC, created_ts DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        out = []
        for r in rows:
            out.append({k: r[k] for k in r.keys()})
        return out

    def delete_report(self, report_id: str) -> bool:
        report_id = str(report_id or "").strip()
        if not report_id:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        return bool(cur.rowcount and cur.rowcount > 0)

    def delete_reports_for_ref(self, *, ref_id: str, report_type: str | None = None) -> int:
        ref_id = str(ref_id or "").strip()
        if not ref_id:
            return 0
        report_type_s = str(report_type or "").strip() if report_type else ""
        if report_type_s:
            sql = "DELETE FROM reports WHERE ref_id = ? AND type = ?"
            params = (ref_id, report_type_s)
        else:
            sql = "DELETE FROM reports WHERE ref_id = ?"
            params = (ref_id,)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
        return int(cur.rowcount or 0)
