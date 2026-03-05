from pydantic import BaseModel, Field
from typing import Optional

class StandardizedScore(BaseModel):
    """
    Standardizes output for model predictions so agents and UI consume the same format.
    Ref: Roadmap Item 24
    """
    target: str = Field(..., description="Target variable name (e.g., return_5d)")
    ticker: str = Field(..., description="Instrument identifier (e.g., SH600519)")
    score: float = Field(..., description="Raw output score from the model")
    confidence: Optional[float] = Field(None, description="0.0 to 1.0 confidence interval if available")
    
    class Config:
        json_schema_extra = {
            "example": {
                "target": "return_5d",
                "ticker": "AAPL",
                "score": 0.051,
                "confidence": 0.89
            }
        }
