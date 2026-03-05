import uuid
import time
import json
import logging
import sqlite3
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime

class ActiveJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending" # pending | running | succeeded | failed
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    task_type: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class JobManager:
    """
    Roadmap Item [48/45] Task Queue Decoupling
    Lightweight SQLite-backed Job Queue for tracking async Agent workflows.
    Replaces need for full Celery/Redis in local-first deployments.
    """
    def __init__(self, db_path: str = "artifacts/jobs.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT,
                    created_at TEXT,
                    completed_at TEXT,
                    task_type TEXT,
                    result TEXT,
                    error TEXT
                )
            ''')
            
    def create_job(self, task_type: str) -> ActiveJob:
        job = ActiveJob(task_type=task_type)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, status, created_at, task_type) VALUES (?, ?, ?, ?)",
                (job.job_id, job.status, job.created_at, job.task_type)
            )
        return job
        
    def update_job(self, job_id: str, status: str, result: dict = None, error: str = None):
        with sqlite3.connect(self.db_path) as conn:
            if status in ["succeeded", "failed"]:
                completed_at = datetime.now().isoformat()
                conn.execute(
                    "UPDATE jobs SET status=?, completed_at=?, result=?, error=? WHERE job_id=?",
                    (status, completed_at, json.dumps(result) if result else None, error, job_id)
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status=?, result=?, error=? WHERE job_id=?",
                    (status, json.dumps(result) if result else None, error, job_id)
                )
                
    def get_job(self, job_id: str) -> Optional[ActiveJob]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row:
                res_dict = dict(row)
                if res_dict['result']:
                    res_dict['result'] = json.loads(res_dict['result'])
                return ActiveJob(**res_dict)
        return None
        
    def list_jobs(self, status: str = None, limit: int = 50) -> list[ActiveJob]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
                
            out = []
            for row in rows:
                res_dict = dict(row)
                if res_dict['result']:
                    res_dict['result'] = json.loads(res_dict['result'])
                out.append(ActiveJob(**res_dict))
            return out
            
    def close(self):
        """Explicitly release any cached resources if needed."""
        pass
        
    def __del__(self):
        self.close()
