from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str
    status: str
    started_at: float
    source: str
    intent: str
    next_action: str
