from pydantic import BaseModel
from typing import Literal

class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "unknown", "succeeded_with_warnings"]
    started_at: float
    source: str
    intent: str
    next_action: str
