import datetime
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ReliabilityEvent:
    code: str
    category: str
    severity: str
    retryable: bool
    component: str
    operation: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    status: str = "open"
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    governance_action: dict[str, Any] = field(default_factory=dict)

    # Optional context fields
    market: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    model_path: str | None = None
    data_snapshot_id: str | None = None
    cache_key: str | None = None
    attempt: int = 1
    max_attempts: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_updates(self, **kwargs) -> "ReliabilityEvent":
        from dataclasses import replace

        return replace(self, **kwargs)
