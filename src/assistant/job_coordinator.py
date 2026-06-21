from __future__ import annotations

import threading

from src.assistant.job_service import JobService


class JobCoordinator:
    """
    Coordinates the HTTP-facing job submission flow.

    Routers should build or validate job requests, then hand the resulting job
    to this module. Persistence and process execution stay behind one interface.
    """

    def __init__(self, job_service: JobService):
        self._job_service = job_service

    @property
    def job_service(self) -> JobService:
        return self._job_service

    def submit(self, job: dict) -> str:
        job_id = self._validate_job(job)
        self._job_service.create_job(job)

        thread = threading.Thread(
            target=self._job_service.run_job,
            args=(job_id,),
            daemon=True,
            name=self._thread_name(job),
        )
        thread.start()
        return job_id

    def submit_response(self, job: dict) -> dict:
        job_id = self.submit(job)
        return {
            "job_id": job_id,
            "status": "queued",
            "started_at": job.get("created_at") or 0.0,
            "source": job.get("source", "api"),
            "intent": job.get("type", "unknown"),
            "next_action": "poll_status",
        }

    @staticmethod
    def _validate_job(job: dict) -> str:
        if not isinstance(job, dict):
            raise ValueError("job must be a dict")

        job_id = str(job.get("id") or "").strip()
        if not job_id:
            raise ValueError("job.id is required")

        commands = job.get("commands") or []
        if not isinstance(commands, list) or not commands:
            raise ValueError("job.commands is required")

        return job_id

    @staticmethod
    def _thread_name(job: dict) -> str:
        job_type = str(job.get("type") or "job").strip() or "job"
        job_id = str(job.get("id") or "").strip()
        suffix = job_id[:8] if job_id else "unknown"
        return f"alpha-{job_type}-{suffix}"
