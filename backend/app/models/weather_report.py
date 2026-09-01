import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Text, UniqueConstraint, Index

from app.database import Base

class MLStatusEnum(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"

class WeatherReport(Base):
    __tablename__ = "weather_reports"
    __table_args__ = (
        UniqueConstraint('source', 'source_post_id', name='uq_weather_reports_source_post_id'),
        Index('idx_ml_status_source', 'ml_status', 'source'),
    )

    # Ingestion Fields (Fixed Contract)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    source = Column(String, index=True, nullable=False)
    source_post_id = Column(String, nullable=False)
    source_url = Column(String, nullable=True)
    author = Column(String, nullable=True)
    text_raw = Column(Text, nullable=False)
    text_clean = Column(Text, nullable=False)
    hashtags = Column(Text, nullable=True)
    posted_at = Column(DateTime(timezone=True), index=True, nullable=False)
    ingested_at = Column(DateTime(timezone=True), index=True, nullable=False)
    city = Column(String, index=True, nullable=True)
    state = Column(String, index=True, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_raw = Column(String, nullable=True)
    media_urls = Column(Text, nullable=True)
    media_type = Column(String, nullable=True)
    event_category_guess = Column(String, index=True, nullable=False)
    language = Column(String, nullable=True)
    dedup_hash = Column(String, index=True, nullable=False)
    is_likely_duplicate = Column(Integer, nullable=False, server_default="0")
    verification_status = Column(String, index=True, nullable=False, server_default="unverified")
    raw_json = Column(Text, nullable=True)
    ml_label = Column(
        Integer,
        nullable=False,
        server_default="0",
        index=True,
        comment="Supervised training target: 0 = genuine, 1 = fabricated. Set by ingestion, never by the ML worker.",
    )

    # Backend/ML Fields
    ml_status = Column(Enum(MLStatusEnum), default=MLStatusEnum.pending, server_default="pending", index=True, nullable=False)
    ml_processed_at = Column(DateTime(timezone=True), nullable=True)
    ml_event_category = Column(String, index=True, nullable=True)
    ml_confidence = Column(Float, nullable=True)
    fake_probability = Column(Float, nullable=True)
    duplicate_probability = Column(Float, nullable=True)
    ml_error = Column(Text, nullable=True)

    # Measurement Verification Fields
    measurement_check = Column(String, nullable=True, comment="agrees | contradicted | unverifiable")
    measurement_note = Column(Text, nullable=True)
    measurement_severity = Column(Float, nullable=True, comment="0-1 how badly it missed")
    measurement_checked_at = Column(DateTime(timezone=True), nullable=True)

    # Hybrid Scoring Fields
    hybrid_updated_at = Column(DateTime(timezone=True), nullable=True)
    hybrid_score = Column(Float, index=True, nullable=True, comment="0-1 blend of model, measurement, physics and source")
    hybrid_signals = Column(Text, nullable=True, comment="JSON breakdown of contributing signals")
    verdict = Column(String, index=True, nullable=True, comment="fake | suspect | ok | unchecked")
