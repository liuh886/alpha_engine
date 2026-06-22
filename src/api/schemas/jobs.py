from typing import Literal

from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str
    status: Literal[
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "unknown",
        "succeeded_with_warnings",
    ]
    started_at: float
    source: str
    intent: str
    next_action: str
