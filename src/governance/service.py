from __future__ import annotations

import contextlib
import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.common.logging import get_logger
from src.reliability.events import ReliabilityEvent
from src.reliability.failure_log import append_failure_event
from src.reliability.governance_policy import GovernanceReliabilityPolicy

logger = get_logger(__name__)


class GovernanceService:
    """
    Governance/audit storage backed by ``artifacts/engine_state.db``.

    Ownership split:
    - ``engine_state.db``: governance run events, task state, failure audit trail
    - ``jobs.db``: async execution queue state managed by ``src.assistant.job_service.JobService``
    """

    def __init__(self, project_root: str | Path):
        self._project_root = Path(project_root)
        self._db_path = self._project_root / "artifacts" / "engine_state.db"
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @contextlib.contextmanager
    def _connect(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # 关键修复：确保事务 Commit
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        market TEXT,
                        action TEXT,
                        outcome TEXT,
                        metric TEXT,
                        event_type TEXT DEFAULT 'run',
                        task_slug TEXT,
                        source TEXT DEFAULT 'governance',
                        details_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS task_status (
                        task_slug TEXT PRIMARY KEY,
                        status TEXT,
                        updated_at TEXT,
                        source TEXT DEFAULT 'governance',
                        market TEXT,
                        last_outcome TEXT,
                        last_error TEXT,
                        details_json TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflows (
                        workflow_id TEXT PRIMARY KEY,
                        name TEXT,
                        market TEXT,
                        status TEXT,
                        updated_at TEXT,
                        start_time TEXT,
                        end_time TEXT,
                        error TEXT,
                        details_json TEXT
                    )
                    """
                )
                self._ensure_columns(
                    conn,
                    "run_log",
                    {
                        "event_type": "TEXT DEFAULT 'run'",
                        "task_slug": "TEXT",
                        "source": "TEXT DEFAULT 'governance'",
                        "details_json": "TEXT",
                    },
                )
                self._ensure_columns(
                    conn,
                    "task_status",
                    {
                        "source": "TEXT DEFAULT 'governance'",
                        "market": "TEXT",
                        "last_outcome": "TEXT",
                        "last_error": "TEXT",
                        "details_json": "TEXT",
                    },
                )
                self._ensure_columns(
                    conn,
                    "workflows",
                    {
                        "name": "TEXT",
                        "market": "TEXT",
                        "status": "TEXT",
                        "updated_at": "TEXT",
                        "start_time": "TEXT",
                        "end_time": "TEXT",
                        "error": "TEXT",
                        "details_json": "TEXT",
                    },
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_run_log_timestamp ON run_log(timestamp DESC)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_run_log_outcome ON run_log(outcome)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_run_log_task_slug ON run_log(task_slug)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_run_log_event_type ON run_log(event_type)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_task_status_status ON task_status(status)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_task_status_updated_at ON task_status(updated_at DESC)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status)")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_workflows_updated_at ON workflows(updated_at DESC)"
                )
        except Exception as exc:
            logger.error("Failed to initialize governance database", error=str(exc))

    @staticmethod
    def _ensure_columns(
        conn: sqlite3.Connection, table_name: str, column_defs: dict[str, str]
    ) -> None:
        existing = {
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_sql in column_defs.items():
            if column_name in existing:
                continue
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _normalize_market(market: str | None) -> str | None:
        if market is None:
            return None
        market_s = str(market).strip()
        return market_s.upper() if market_s else None

    @staticmethod
    def _encode_details(details: dict[str, Any] | None) -> str | None:
        if not details:
            return None
        return json.dumps(details, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode_details(payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            decoded = json.loads(payload)
        except Exception:
            logger.debug("Failed to decode details JSON payload", exc_info=True)
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def log_run_event(
        self,
        market: str,
        action: str,
        outcome: str,
        metric: str | None = None,
        *,
        event_type: str = "run",
        task_slug: str | None = None,
        source: str = "governance",
        details: dict[str, Any] | None = None,
    ) -> None:
        timestamp = self._now()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO run_log (
                        timestamp, market, action, outcome, metric,
                        event_type, task_slug, source, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        self._normalize_market(market),
                        str(action),
                        str(outcome).upper(),
                        metric,
                        str(event_type).lower(),
                        str(task_slug) if task_slug else None,
                        str(source),
                        self._encode_details(details),
                    ),
                )
        except Exception as exc:
            logger.error("Failed to log governance event to DB", error=str(exc))

    def log_failure_event(
        self,
        market: str,
        action: str,
        *,
        error_message: str,
        metric: str | None = None,
        task_slug: str | None = None,
        source: str = "governance",
        details: dict[str, Any] | None = None,
    ) -> None:
        detail_payload = dict(details or {})
        detail_payload.setdefault("error_message", str(error_message))
        self.log_run_event(
            market,
            action,
            "FAILURE",
            metric=metric or str(error_message),
            event_type="failure",
            task_slug=task_slug,
            source=source,
            details=detail_payload,
        )

    def update_task_status(
        self,
        task_slug: str,
        status: str = "DONE",
        *,
        source: str = "governance",
        market: str | None = None,
        last_outcome: str | None = None,
        last_error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        timestamp = self._now()
        normalized_status = str(status).upper()
        normalized_outcome = str(last_outcome).upper() if last_outcome else None
        if normalized_outcome is None and normalized_status in {"FAILED", "FAILURE"}:
            normalized_outcome = "FAILURE"
        if normalized_outcome is None and normalized_status in {"SUCCEEDED", "SUCCESS", "DONE"}:
            normalized_outcome = "SUCCESS"
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO task_status (
                        task_slug, status, updated_at, source, market,
                        last_outcome, last_error, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_slug) DO UPDATE SET
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        source = excluded.source,
                        market = excluded.market,
                        last_outcome = excluded.last_outcome,
                        last_error = excluded.last_error,
                        details_json = excluded.details_json
                    """,
                    (
                        str(task_slug),
                        normalized_status,
                        timestamp,
                        str(source),
                        self._normalize_market(market),
                        normalized_outcome,
                        str(last_error) if last_error else None,
                        self._encode_details(details),
                    ),
                )
        except Exception as exc:
            logger.error("Failed to update task status in DB", error=str(exc))

    def log_reliability_event(
        self,
        event: ReliabilityEvent,
        *,
        task_slug: str | None = None,
        source: str = "reliability",
    ) -> ReliabilityEvent:
        resolution = GovernanceReliabilityPolicy().resolve_action(event)
        resolved_event = event.with_updates(
            governance_action=resolution,
            status=str(resolution.get("status") or event.status),
        )
        try:
            append_failure_event(
                resolved_event,
                path=self._project_root / "artifacts" / "governance" / "failure_log.json",
            )
        except Exception as exc:
            logger.error("Failed to append reliability event to failure log", error=str(exc))

        self.log_run_event(
            resolved_event.market or "ALL",
            f"{resolved_event.component}:{resolved_event.code}",
            "FAILURE",
            metric=resolved_event.summary,
            event_type="failure",
            task_slug=task_slug,
            source=source,
            details=resolved_event.to_dict(),
        )
        return resolved_event

    def query_history(
        self,
        limit: int = 20,
        *,
        outcome: str | None = None,
        event_type: str | None = None,
        task_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM run_log"
        clauses: list[str] = []
        params: list[Any] = []

        if outcome:
            clauses.append("upper(outcome) = ?")
            params.append(str(outcome).upper())
        if event_type:
            clauses.append("lower(event_type) = ?")
            params.append(str(event_type).lower())
        if task_slug:
            clauses.append("task_slug = ?")
            params.append(str(task_slug))

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))

        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [self._decode_run_log_row(row) for row in rows]
        except Exception as exc:
            logger.error("Failed to query history from DB", error=str(exc))
            return []

    def query_failure_events(
        self, limit: int = 20, *, task_slug: str | None = None
    ) -> list[dict[str, Any]]:
        return self.query_history(
            limit=limit,
            outcome="FAILURE",
            event_type="failure",
            task_slug=task_slug,
        )

    def query_task_statuses(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM task_status"
        params: list[Any] = []
        if status:
            sql += " WHERE upper(status) = ?"
            params.append(str(status).upper())
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))

        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [self._decode_task_status_row(row) for row in rows]
        except Exception as exc:
            logger.error("Failed to query task statuses from DB", error=str(exc))
            return []

    def get_task_status(self, task_slug: str) -> dict[str, Any] | None:
        """Retrieve current status for a specific task slug."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM task_status WHERE task_slug = ?", (str(task_slug),)
                ).fetchone()
                if row:
                    return self._decode_task_status_row(row)
        except Exception as exc:
            logger.error("Failed to get task status", task_slug=task_slug, error=str(exc))
        return None

    def update_workflow_status(
        self,
        workflow_id: str,
        *,
        name: str | None = None,
        market: str | None = None,
        status: str = "RUNNING",
        start_time: str | None = None,
        end_time: str | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        timestamp = self._now()
        try:
            with self._connect() as conn:
                # Check if exists to preserve name/market if not provided in update
                existing = conn.execute(
                    "SELECT name, market, start_time FROM workflows WHERE workflow_id = ?",
                    (str(workflow_id),),
                ).fetchone()

                final_name = name or (existing["name"] if existing else None)
                final_market = self._normalize_market(market) or (
                    existing["market"] if existing else None
                )
                final_start = start_time or (existing["start_time"] if existing else timestamp)

                conn.execute(
                    """
                    INSERT INTO workflows (
                        workflow_id, name, market, status, updated_at,
                        start_time, end_time, error, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        name = COALESCE(excluded.name, name),
                        market = COALESCE(excluded.market, market),
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        start_time = COALESCE(excluded.start_time, start_time),
                        end_time = COALESCE(excluded.end_time, end_time),
                        error = COALESCE(excluded.error, error),
                        details_json = COALESCE(excluded.details_json, details_json)
                    """,
                    (
                        str(workflow_id),
                        final_name,
                        final_market,
                        str(status).upper(),
                        timestamp,
                        final_start,
                        end_time,
                        error,
                        self._encode_details(details),
                    ),
                )
        except Exception as exc:
            logger.error("Failed to update workflow status in DB", error=str(exc))

    def query_workflows(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM workflows"
        params: list[Any] = []
        if status:
            sql += " WHERE upper(status) = ?"
            params.append(str(status).upper())
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))

        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [self._decode_workflow_row(row) for row in rows]
        except Exception as exc:
            logger.error("Failed to query workflows from DB", error=str(exc))
            return []

    def get_workflow_status(self, workflow_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM workflows WHERE workflow_id = ?", (str(workflow_id),)
                ).fetchone()
                if row:
                    return self._decode_workflow_row(row)
        except Exception as exc:
            logger.error("Failed to get workflow status", workflow_id=workflow_id, error=str(exc))
        return None

    @staticmethod
    def _decode_run_log_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["details"] = GovernanceService._decode_details(payload.pop("details_json", None))
        return payload

    @staticmethod
    def _decode_task_status_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["details"] = GovernanceService._decode_details(payload.pop("details_json", None))
        return payload

    @staticmethod
    def _decode_workflow_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["details"] = GovernanceService._decode_details(payload.pop("details_json", None))
        return payload
