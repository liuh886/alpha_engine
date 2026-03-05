from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import yaml

from src.assistant.metadata_db import connect


def _safe_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return "{}"


class ModelRegistryIndex:
    """
    Minimal SQLite-backed model registry index.

    Source-of-truth remains `models/model_list.yaml` for now; this index enables fast
    queries and supports dashboard/server features without scanning YAML each time.
    """

    def __init__(self, *, db_path: str | Path):
        self._db_path = Path(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_versions (
                    id TEXT PRIMARY KEY,
                    tag TEXT,
                    name TEXT,
                    market TEXT,
                    model_type TEXT,
                    path TEXT,
                    run_id TEXT,
                    created_at TEXT,
                    description TEXT,
                    params_json TEXT,
                    metrics_json TEXT,
                    feature_importance_json TEXT,
                    payload_json TEXT,
                    created_ts REAL
                )
                """
            )
            # Migration for existing DBs
            cursor = conn.execute("PRAGMA table_info(model_versions)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "feature_importance_json" not in cols:
                conn.execute("ALTER TABLE model_versions ADD COLUMN feature_importance_json TEXT")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_model_versions_run_id ON model_versions(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model_versions_market ON model_versions(market)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model_versions_created_at ON model_versions(created_at)")

    def upsert_entry(self, entry: dict) -> bool:
        if not isinstance(entry, dict):
            return False
        version_id = str(entry.get("id") or "").strip()
        if not version_id:
            return False

        tag = str(entry.get("tag") or "")
        name = str(entry.get("name") or tag or version_id)
        market = str(entry.get("market") or "")
        model_type = str(entry.get("type") or entry.get("model_type") or "")
        path = str(entry.get("path") or "")
        run_id = str(entry.get("run_id") or "")
        created_at = str(entry.get("created_at") or "")
        description = str(entry.get("description") or "")

        params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
        metrics = (
            (entry.get("backtest") or {}).get("metrics")
            if isinstance(entry.get("backtest"), dict)
            else {}
        )
        if not isinstance(metrics, dict):
            metrics = {}
        
        feature_importance = entry.get("feature_importance") or {}
        if not isinstance(feature_importance, dict):
            feature_importance = {}

        now = time.time()
        payload_json = _safe_json(entry)
        params_json = _safe_json(params)
        metrics_json = _safe_json(metrics)
        feature_importance_json = _safe_json(feature_importance)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_versions (
                    id, tag, name, market, model_type, path, run_id, created_at, description,
                    params_json, metrics_json, feature_importance_json, payload_json, created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    tag=excluded.tag,
                    name=excluded.name,
                    market=excluded.market,
                    model_type=excluded.model_type,
                    path=excluded.path,
                    run_id=excluded.run_id,
                    created_at=excluded.created_at,
                    description=excluded.description,
                    params_json=excluded.params_json,
                    metrics_json=excluded.metrics_json,
                    feature_importance_json=excluded.feature_importance_json,
                    payload_json=excluded.payload_json
                """,
                (
                    version_id,
                    tag,
                    name,
                    market,
                    model_type,
                    path,
                    run_id,
                    created_at,
                    description,
                    params_json,
                    metrics_json,
                    feature_importance_json,
                    payload_json,
                    now,
                ),
            )
        return True

    def upsert_from_model_list_yaml(self, yaml_path: str | Path, *, project_root: str | Path | None = None) -> int:
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            return 0
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return 0

        models = data.get("models", [])
        if not isinstance(models, list):
            return 0

        n = 0
        for entry in models:
            if not isinstance(entry, dict):
                continue
            if self.upsert_entry(entry):
                n += 1
        return n

    def list_versions(self, *, limit: int = 100, market: str | None = None) -> list[dict]:
        limit = int(limit) if limit is not None else 100
        if limit <= 0:
            return []

        market_s = str(market).strip().lower() if market else ""
        if market_s:
            sql = "SELECT * FROM model_versions WHERE lower(market) = ? ORDER BY created_at DESC, created_ts DESC LIMIT ?"
            params = (market_s, limit)
        else:
            sql = "SELECT * FROM model_versions ORDER BY created_at DESC, created_ts DESC LIMIT ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_version(self, version_id: str) -> dict | None:
        version_id = str(version_id or "").strip()
        if not version_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE id = ?", (version_id,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        for k in ("formats_json", "paths_json", "meta_json", "params_json", "metrics_json", "feature_importance_json"):
            raw = out.get(k)
            if not raw:
                continue
            try:
                out[k.replace("_json", "")] = json.loads(raw)
            except Exception:
                out[k.replace("_json", "")] = {}
        return out

    def update_stage(self, version_id: str, stage: str) -> bool:
        version_id = str(version_id or "").strip()
        stage = str(stage or "STAGING").upper().strip()
        if not version_id:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE model_versions SET description = ? WHERE id = ?",
                (f"Stage: {stage}", version_id),
            )
        return bool(cur.rowcount and cur.rowcount > 0)

    def delete_version(self, version_id: str) -> bool:
        version_id = str(version_id or "").strip()
        if not version_id:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM model_versions WHERE id = ?", (version_id,))
        return bool(cur.rowcount and cur.rowcount > 0)

    def delete_versions_for_run(self, run_id: str) -> bool:
        run_id = str(run_id or "").strip()
        if not run_id:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM model_versions WHERE run_id = ?", (run_id,))
        return bool(cur.rowcount and cur.rowcount > 0)

