from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from src.assistant.metadata_db import connect


def _infer_data_snapshot_id(params: dict | None) -> str | None:
    if not isinstance(params, dict):
        return None
    v = params.get("data_snapshot_id")
    if v:
        return str(v)
    meta = params.get("meta")
    if isinstance(meta, dict) and meta.get("data_snapshot_id"):
        return str(meta.get("data_snapshot_id"))
    return None


class RunIndex:
    """
    Minimal backtest run index stored in SQLite.

    This is a stepping stone toward the design doc's full metadata schema.
    """

    def __init__(self, *, db_path: str | Path):
        self._db_path = Path(db_path)
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    market TEXT,
                    date TEXT,
                    backtest_start TEXT,
                    backtest_end TEXT,
                    data_snapshot_id TEXT,
                    params_json TEXT,
                    feature_importance_json TEXT,
                    created_at REAL
                )
                """
            )
            # Migration for existing DBs
            cursor = conn.execute("PRAGMA table_info(backtest_runs)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "feature_importance_json" not in cols:
                conn.execute("ALTER TABLE backtest_runs ADD COLUMN feature_importance_json TEXT")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_market ON backtest_runs(market)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_date ON backtest_runs(date)")

    def upsert_from_dashboard_db(self, dashboard_db: dict) -> int:
        models = dashboard_db.get("models", [])
        if not isinstance(models, list):
            return 0

        rows: list[tuple] = []
        now = time.time()
        for m in models:
            if not isinstance(m, dict):
                continue
            run_id = str(m.get("id") or "").strip()
            if not run_id:
                continue
            name = str(m.get("name") or "")
            market = str(m.get("market") or "")
            date = str(m.get("date") or "")
            params = m.get("params") if isinstance(m.get("params"), dict) else {}
            backtest_start = str(params.get("backtest_start") or "")
            backtest_end = str(params.get("backtest_end") or "")
            data_snapshot_id = _infer_data_snapshot_id(params) or ""
            params_json = json.dumps(params, ensure_ascii=False)
            
            run_data = m.get("data") or {}
            feature_importance = run_data.get("feature_importance") or {}
            feature_importance_json = json.dumps(feature_importance, ensure_ascii=False)

            rows.append(
                (
                    run_id,
                    name,
                    market,
                    date,
                    backtest_start,
                    backtest_end,
                    data_snapshot_id,
                    params_json,
                    feature_importance_json,
                    now,
                )
            )

        if not rows:
            return 0

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO backtest_runs (
                    id, name, market, date, backtest_start, backtest_end,
                    data_snapshot_id, params_json, feature_importance_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    market=excluded.market,
                    date=excluded.date,
                    backtest_start=excluded.backtest_start,
                    backtest_end=excluded.backtest_end,
                    data_snapshot_id=excluded.data_snapshot_id,
                    params_json=excluded.params_json,
                    feature_importance_json=excluded.feature_importance_json
                """,
                rows,
            )
        return len(rows)

    def upsert_from_dashboard_db_path(self, path: str | Path) -> int:
        path = Path(path)
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        return self.upsert_from_dashboard_db(data if isinstance(data, dict) else {})

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (str(run_id),)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        if out.get("params_json"):
            try:
                out["params"] = json.loads(out["params_json"])
            except Exception:
                out["params"] = {}
        else:
            out["params"] = {}
            
        if out.get("feature_importance_json"):
            try:
                out["feature_importance"] = json.loads(out["feature_importance_json"])
            except Exception:
                out["feature_importance"] = {}
        else:
            out["feature_importance"] = {}
            
        return out

    def list_runs(self, *, limit: int = 100, market: str | None = None) -> list[dict]:
        limit = int(limit) if limit is not None else 100
        if limit <= 0:
            return []
        market = str(market).strip().lower() if market else ""
        if market:
            sql = "SELECT * FROM backtest_runs WHERE market = ? ORDER BY date DESC, created_at DESC LIMIT ?"
            params = (market, limit)
        else:
            sql = "SELECT * FROM backtest_runs ORDER BY date DESC, created_at DESC LIMIT ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def delete_run(self, run_id: str) -> bool:
        run_id = str(run_id or "").strip()
        if not run_id:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM backtest_runs WHERE id = ?", (run_id,))
        return bool(cur.rowcount and cur.rowcount > 0)
