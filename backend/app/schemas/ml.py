from pydantic import BaseModel
from typing import List, Optional

class MLPrediction(BaseModel):
    report_id: str
    ml_event_category: str
    ml_confidence: float
    fake_probability: float
    duplicate_probability: float
    verification_status: Optional[str] = None  # Model can recommend a verification status

class MLPredictionPayload(BaseModel):
    predictions: List[MLPrediction]

class MLPredictionResponse(BaseModel):
    updated: int
    failed: int
    errors: List[str]
