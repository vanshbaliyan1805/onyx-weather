import enum
import uuid
from sqlalchemy import Column, String, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base

class PipelineStatusEnum(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    error = "error"

class PipelineStageEnum(str, enum.Enum):
    ingestion = "ingestion"
    ml = "ml"
    verification = "verification"
    hybrid = "hybrid"
    none = "none"

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    status = Column(Enum(PipelineStatusEnum), default=PipelineStatusEnum.pending, index=True, nullable=False)
    current_stage = Column(Enum(PipelineStageEnum), nullable=True)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    
    error_message = Column(Text, nullable=True)
    
    # Store dynamic progress dicts natively
    stage_progress = Column(JSONB, nullable=True)
