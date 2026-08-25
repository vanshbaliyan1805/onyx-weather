from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any
from datetime import datetime
from app.models.weather_report import MLStatusEnum

class WeatherReportBase(BaseModel):
    id: str
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
    language: str
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

    model_config = ConfigDict(from_attributes=True)

class WeatherReportResponse(WeatherReportBase):
    pass

class PaginatedWeatherReports(BaseModel):
    items: List[WeatherReportResponse]
    total: int
    page: int
    limit: int
    pages: int
