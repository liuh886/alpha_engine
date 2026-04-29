from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from src.assistant.metadata_db import connect

# Global registry for running processes
_RUNNING_PROCS: dict[str, subprocess.Popen] = {}
_PROCS_LOCK = threading.Lock()


class JobService:
    def __init__(self, *, db_path: str | Path, project_root: str | Path):
        self._db_path = Path(db_path)
        self._project_root = Path(project_root)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def project_root(self) -> Path:
        return self._project_root

    @contextlib.contextmanager
    def _connect(self):
        conn = connect(self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT,
                    status TEXT,
                    created_at REAL,
                    started_at REAL,
                    finished_at REAL,
                    exit_code INTEGER,
                    error TEXT,
                    log_path TEXT,
                    job_json TEXT,
                    commands_json TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

    def create_job(self, job: dict) -> None:
        self._ensure_schema()
        job_id = str(job.get("id") or "")
        if not job_id:
            raise ValueError("job.id is required")

        job_type = str(job.get("type") or "")
        status = str(job.get("status") or "queued")
        created_at = float(job.get("created_at") or time.time())
        started_at = job.get("started_at")
        finished_at = job.get("finished_at")
        exit_code = job.get("exit_code")
        error = job.get("error")
        log_path = str(job.get("log_path") or "")

        commands = job.get("commands") or []
        commands_json = json.dumps(commands, ensure_ascii=False)

        job_no_cmd = dict(job)
        job_no_cmd.pop("commands", None)
        job_json = json.dumps(job_no_cmd, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, type, status, created_at, started_at, finished_at,
                    exit_code, error, log_path, job_json, commands_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    status,
                    created_at,
                    float(started_at) if started_at is not None else None,
                    float(finished_at) if finished_at is not None else None,
                    int(exit_code) if exit_code is not None else None,
                    str(error) if error is not None else None,
                    log_path,
                    job_json,
                    commands_json,
                ),
            )

    def get_job(self, job_id: str) -> dict | None:
        self._ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
        if row is None:
            return None

        return self._decode_row(row)

    def list_jobs(self, *, limit: int = 100, status: str | None = None) -> list[dict]:
        self._ensure_schema()
        limit = int(limit) if limit is not None else 100
        if limit <= 0:
            return []

        status_s = str(status).strip().lower() if status else ""
        if status_s:
            sql = "SELECT * FROM jobs WHERE lower(status) = ? ORDER BY created_at DESC LIMIT ?"
            params = (status_s, limit)
        else:
            sql = "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?"
            params = (limit,)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_row(row) for row in rows]

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict:
        out: dict = {}
        if row["job_json"]:
            try:
                out.update(json.loads(row["job_json"]))
            except Exception:
                pass

        out.update(
            {
                "id": row["id"],
                "type": row["type"],
                "status": row["status"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "exit_code": row["exit_code"],
                "error": row["error"],
                "log_path": row["log_path"],
            }
        )

        if row["commands_json"]:
            try:
                out["commands"] = json.loads(row["commands_json"])
            except Exception:
                out["commands"] = []
        else:
            out["commands"] = []

        return out

    def update_job(self, job_id: str, **fields) -> None:
        self._ensure_schema()
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "exit_code",
            "error",
            "log_path",
            "job_json",
            "commands_json",
        }
        updates: list[tuple[str, object]] = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in {"started_at", "finished_at"} and v is not None:
                v = float(v)
            if k == "exit_code" and v is not None:
                v = int(v)
            if k in {"job_json", "commands_json"} and isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            updates.append((k, v))

        if not updates:
            return

        set_sql = ", ".join([f"{k} = ?" for k, _ in updates])
        params = [v for _, v in updates] + [str(job_id)]
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {set_sql} WHERE id = ?", params)

    def _send_webhook_alert(self, job_id: str, error_msg: str):
        webhook_url = os.environ.get("TRADING_WEBHOOK_URL")
        if not webhook_url:
            return
        try:
            payload = {"text": f"🚨 *Job Failed*: `{job_id}`\n```\n{error_msg[:1000]}\n```"}
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    def kill_job(self, job_id: str) -> bool:
        """
        Kill a running job process if it exists in the registry.
        """
        with _PROCS_LOCK:
            proc = _RUNNING_PROCS.get(str(job_id))
            if proc:
                try:
                    if os.name == "nt":
                        proc.terminate()  # Windows
                    else:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    return True
                except Exception:
                    return False
        return False

    def run_job(self, job_id: str) -> None:
        job = self.get_job(str(job_id))
        if not job:
            raise ValueError("job not found")

        self.update_job(
            str(job_id),
            status="running",
            started_at=time.time(),
            finished_at=None,
            exit_code=None,
            error=None,
        )

        log_path = Path(str(job.get("log_path") or ""))
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            for cmd in job.get("commands") or []:
                cmd_str = " ".join([str(x) for x in cmd])

                kwargs = {
                    "cwd": str(self._project_root),
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                }
                if os.name != "nt":
                    kwargs["start_new_session"] = True

                proc = subprocess.Popen(cmd, **kwargs)

                with _PROCS_LOCK:
                    _RUNNING_PROCS[str(job_id)] = proc

                try:
                    stdout, _ = proc.communicate()
                finally:
                    with _PROCS_LOCK:
                        if _RUNNING_PROCS.get(str(job_id)) == proc:
                            del _RUNNING_PROCS[str(job_id)]

                if log_path:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"\n=== {cmd_str} ===\n")
                        f.write(stdout)
                        f.flush()

                if proc.returncode != 0:
                    # Check if it was killed by panic
                    current = self.get_job(str(job_id))
                    if (
                        current
                        and current.get("status") == "failed"
                        and "SYSTEM_PANIC" in str(current.get("error"))
                    ):
                        return

                    error_snippet = stdout[-500:] if stdout else "Process failed with no output"
                    full_error = f"Command failed: {cmd_str}\n\nLast output:\n...{error_snippet}"
                    self._send_webhook_alert(str(job_id), full_error)
                    self.update_job(
                        str(job_id),
                        status="failed",
                        exit_code=proc.returncode,
                        error=full_error,
                        finished_at=time.time(),
                    )
                    return

            self.update_job(
                str(job_id),
                status="succeeded",
                exit_code=0,
                finished_at=time.time(),
            )
        except Exception as e:
            import traceback

            full_error = f"Exception: {str(e)}\n\n{traceback.format_exc()}"
            self._send_webhook_alert(str(job_id), full_error)
            self.update_job(
                str(job_id),
                status="failed",
                exit_code=-1,
                error=full_error,
                finished_at=time.time(),
            )

    def repair_jobs(self, *, timeout_hours: float = 24.0) -> int:
        self._ensure_schema()
        cutoff = time.time() - (float(timeout_hours) * 3600.0)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'failed', error = 'Stale job (likely crashed)' WHERE status = 'running' AND started_at < ?",
                (cutoff,),
            )
            return int(cur.rowcount or 0)
