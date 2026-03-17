import datetime
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

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
    details: Dict[str, Any] = field(default_factory=dict)
    governance_action: Dict[str, Any] = field(default_factory=dict)
    
    # Optional context fields
    market: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    model_path: Optional[str] = None
    data_snapshot_id: Optional[str] = None
    cache_key: Optional[str] = None
    attempt: int = 1
    max_attempts: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def with_updates(self, **kwargs) -> "ReliabilityEvent":
        from dataclasses import replace
        return replace(self, **kwargs)
