from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List, Any
import json
from datetime import datetime
from app.models.weather_report import MLStatusEnum

class WeatherReportBase(BaseModel):
    id: int
    source: str
    source_post_id: str
    source_url: Optional[str] = None
    author: Optional[str] = None
    text_raw: str
    text_clean: str
    hashtags: Optional[List[str]] = None
    posted_at: datetime
    ingested_at: datetime
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_raw: Optional[str] = None
    media_urls: Optional[List[str]] = None
    media_type: Optional[str] = None
    event_category_guess: str
    language: Optional[str] = None
    dedup_hash: str
    is_likely_duplicate: bool
    verification_status: str
    raw_json: Optional[Any] = None

    # ML Fields
    ml_status: MLStatusEnum
    ml_processed_at: Optional[datetime] = None
    ml_event_category: Optional[str] = None
    ml_confidence: Optional[float] = None
    fake_probability: Optional[float] = None
    duplicate_probability: Optional[float] = None
    ml_error: Optional[str] = None

    # Hybrid & Measurement Fields
    verdict: Optional[str] = None
    hybrid_score: Optional[float] = None
    hybrid_signals: Optional[Any] = None
    measurement_check: Optional[str] = None
    measurement_note: Optional[str] = None
    measurement_severity: Optional[float] = None
    measurement_checked_at: Optional[datetime] = None

    @field_validator('hashtags', 'media_urls', mode='before')
    @classmethod
    def split_comma_separated(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(',') if x.strip()]
        return v
        
    @field_validator('is_likely_duplicate', mode='before')
    @classmethod
    def parse_bool(cls, v):
        return bool(v)

    @field_validator('raw_json', 'hybrid_signals', mode='before')
    @classmethod
    def parse_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    model_config = ConfigDict(from_attributes=True)

class WeatherReportResponse(WeatherReportBase):
    pass

class PaginatedWeatherReports(BaseModel):
    items: List[WeatherReportResponse]
    total: int
    page: int
    limit: int
    pages: int
