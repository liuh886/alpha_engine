from typing import Optional, Literal
from pydantic import BaseModel, Field

class AttributionRequest(BaseModel):
    market: str
    model_version_id: Optional[str] = None
    min_observations: int = Field(default=12, ge=3, le=120)
    regularization: Literal["none", "ridge"] = "none"
