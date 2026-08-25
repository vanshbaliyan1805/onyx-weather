import enum
from sqlalchemy import Column, String, Float, Boolean, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base

class MLStatusEnum(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class WeatherReport(Base):
    __tablename__ = "weather_reports"

    # Ingestion Fields (Fixed Contract)
    id = Column(String, primary_key=True, index=True)
    source = Column(String, index=True, nullable=False)
    source_post_id = Column(String, nullable=False)
    source_url = Column(String, nullable=True)
    author = Column(String, nullable=True)
    text_raw = Column(Text, nullable=False)
    text_clean = Column(Text, nullable=False)
    hashtags = Column(JSONB, nullable=True)
    posted_at = Column(DateTime(timezone=True), index=True, nullable=False)
    ingested_at = Column(DateTime(timezone=True), index=True, nullable=False)
    city = Column(String, index=True, nullable=True)
    state = Column(String, index=True, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_raw = Column(String, nullable=True)
    media_urls = Column(JSONB, nullable=True)
    media_type = Column(String, nullable=True)
    event_category_guess = Column(String, index=True, nullable=False)
    language = Column(String, nullable=False)
    dedup_hash = Column(String, index=True, nullable=False)
    is_likely_duplicate = Column(Boolean, nullable=False, default=False)
    verification_status = Column(String, index=True, nullable=False, default="unverified")
    raw_json = Column(JSONB, nullable=True)

    # Backend/ML Fields
    ml_status = Column(Enum(MLStatusEnum), default=MLStatusEnum.pending, index=True, nullable=False)
    ml_processed_at = Column(DateTime(timezone=True), nullable=True)
    ml_event_category = Column(String, index=True, nullable=True)
    ml_confidence = Column(Float, nullable=True)
    fake_probability = Column(Float, nullable=True)
    duplicate_probability = Column(Float, nullable=True)
    ml_error = Column(Text, nullable=True)
